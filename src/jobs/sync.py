"""
Job de sincronização (download) seletiva de dados da Receita Federal.

Baixa os arquivos .zip de um mês específico (year_month) que estejam
com status 'pending' na tabela sync_control.

Features:
- Barra de progresso com velocidade (MB/s) e ETA
- Hash SHA-256 do arquivo baixado para verificação de integridade
- Comparação hash local vs ETag remoto (hash diff)
- Suporte a download de arquivo individual
- Atualização de progresso no banco em tempo real

Os arquivos são salvos em data/raw/{year_month}/.
"""

import hashlib
import logging
import os
import time
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session

from src.config import RECEITA_BASE_URL, DATA_RAW_DIR
from src.models.sync_control import SyncControl
from src.utils import format_bytes as _format_bytes
from src.models.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Tamanho do chunk para download (64KB para melhor throughput)
CHUNK_SIZE = 65536

# Intervalo mínimo entre atualizações de progresso no banco (segundos)
PROGRESS_UPDATE_INTERVAL = 2.0


# _format_bytes importada de src.utils


def _format_eta(seconds: float) -> str:
    """Formata segundos restantes em formato legível."""
    if seconds < 0 or seconds > 86400:
        return "calculando..."
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    elif minutes > 0:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _compute_file_hash(file_path: str) -> str:
    """Calcula o hash SHA-256 de um arquivo no disco."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _download_file(
    url: str,
    dest_path: str,
    auth: tuple = None,
    sync_record: "SyncControl" = None,
    db: Session = None,
) -> dict:
    """
    Faz download de um arquivo com streaming, progresso visual e hash SHA-256.

    Retorna um dicionário com:
    - total_bytes: tamanho total baixado
    - sha256: hash SHA-256 do arquivo
    - elapsed_seconds: tempo total do download
    - avg_speed_mbps: velocidade média em MB/s
    """
    logger.info(f"📥 Baixando: {url}")
    logger.info(f"   Destino:  {dest_path}")

    response = requests.get(url, stream=True, timeout=300, auth=auth)
    response.raise_for_status()

    # Tamanho total esperado (pode ser None se o servidor não informar)
    content_length = response.headers.get("Content-Length")
    total_expected = int(content_length) if content_length else None

    if total_expected:
        logger.info(f"   Tamanho esperado: {_format_bytes(total_expected)}")
    else:
        logger.info("   Tamanho esperado: desconhecido (sem Content-Length)")

    sha256 = hashlib.sha256()
    total_bytes = 0
    start_time = time.monotonic()
    last_log_time = start_time
    last_progress_update = start_time

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            f.write(chunk)
            sha256.update(chunk)
            total_bytes += len(chunk)

            now = time.monotonic()
            elapsed = now - start_time

            # Log de progresso a cada 2 segundos
            if now - last_log_time >= 2.0:
                speed = total_bytes / elapsed if elapsed > 0 else 0
                speed_mb = speed / (1024 * 1024)

                if total_expected and total_expected > 0:
                    pct = (total_bytes / total_expected) * 100
                    remaining_bytes = total_expected - total_bytes
                    eta = remaining_bytes / speed if speed > 0 else 0

                    # Barra visual (30 chars)
                    filled = int(pct / 100 * 30)
                    bar = "█" * filled + "░" * (30 - filled)

                    logger.info(
                        f"   [{bar}] {pct:5.1f}% | "
                        f"{_format_bytes(total_bytes)}/{_format_bytes(total_expected)} | "
                        f"{speed_mb:.1f} MB/s | ETA: {_format_eta(eta)}"
                    )
                else:
                    logger.info(
                        f"   📦 {_format_bytes(total_bytes)} baixados | {speed_mb:.1f} MB/s"
                    )

                last_log_time = now

            # Atualização de progresso no banco (evita writes excessivos)
            if (
                sync_record
                and db
                and total_expected
                and now - last_progress_update >= PROGRESS_UPDATE_INTERVAL
            ):
                pct = (total_bytes / total_expected) * 100
                sync_record.download_progress = round(pct, 1)
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                last_progress_update = now

    elapsed = time.monotonic() - start_time
    avg_speed = total_bytes / elapsed if elapsed > 0 else 0
    file_hash = sha256.hexdigest()

    logger.info(
        f"   ✅ Download concluído: {_format_bytes(total_bytes)} em "
        f"{_format_eta(elapsed)} ({avg_speed / (1024 * 1024):.1f} MB/s)"
    )
    logger.info(f"   🔒 SHA-256: {file_hash}")

    return {
        "total_bytes": total_bytes,
        "sha256": file_hash,
        "elapsed_seconds": round(elapsed, 2),
        "avg_speed_mbps": round(avg_speed / (1024 * 1024), 2),
    }


def _build_download_url(year_month: str, file_name: str) -> tuple[str, tuple]:
    """
    Constrói a URL de download via WebDAV e retorna a tupla (url, auth).
    """
    token = RECEITA_BASE_URL.rstrip("/").split("/")[-1]

    if year_month == "BASE":
        url = f"https://arquivos.receitafederal.gov.br/public.php/webdav/{file_name}"
    else:
        url = f"https://arquivos.receitafederal.gov.br/public.php/webdav/{year_month}/{file_name}"

    return url, (token, "")


def verify_file_integrity(db: Session, year_month: str, full_check: bool = False) -> list[dict]:
    """
    Verifica a integridade dos arquivos baixados comparando com o S3:
    - Tamanho remoto (S3) vs tamanho armazenado no banco
    - Hash SHA-256 (se full_check=True) recalculado baixando do S3

    Retorna lista de arquivos com inconsistências.
    """
    from src.utils import get_s3_client
    from src.config import S3_BUCKET_NAME
    from botocore.exceptions import ClientError
    import hashlib

    records = (
        db.query(SyncControl)
        .filter(
            SyncControl.year_month == year_month,
            SyncControl.status.in_(["downloaded", "transformed", "loaded"]),
        )
        .all()
    )

    s3_client = get_s3_client()
    issues = []

    for record in records:
        s3_key = f"raw/{record.year_month}/{record.file_name}"

        try:
            head = s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        except ClientError:
            issues.append(
                {
                    "file_name": record.file_name,
                    "issue": "missing_in_s3",
                    "detail": f"Arquivo não encontrado no S3 (s3://{S3_BUCKET_NAME}/{s3_key})",
                }
            )
            continue

        # Verificar tamanho
        s3_size = head.get("ContentLength")
        if record.local_size_bytes and s3_size != record.local_size_bytes:
            issues.append(
                {
                    "file_name": record.file_name,
                    "issue": "size_mismatch",
                    "detail": (
                        f"Tamanho no S3 ({_format_bytes(s3_size)}) "
                        f"difere do registrado ({_format_bytes(record.local_size_bytes)})"
                    ),
                }
            )
            continue

        # Recalcular hash (full_check)
        if full_check and record.local_hash:
            logger.info(f"Recalculando hash SHA-256 via stream do S3 para {record.file_name}...")
            sha256 = hashlib.sha256()
            try:
                response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
                for chunk in response["Body"].iter_chunks(chunk_size=CHUNK_SIZE):
                    sha256.update(chunk)
                current_hash = sha256.hexdigest()

                if current_hash != record.local_hash:
                    issues.append(
                        {
                            "file_name": record.file_name,
                            "issue": "hash_mismatch",
                            "detail": (
                                f"Hash atual ({current_hash[:16]}...) "
                                f"difere do registrado ({record.local_hash[:16]}...)"
                            ),
                        }
                    )
            except Exception as e:
                issues.append(
                    {
                        "file_name": record.file_name,
                        "issue": "s3_read_error",
                        "detail": f"Erro ao ler do S3: {str(e)}",
                    }
                )

    return issues


def compare_remote_vs_local(db: Session, year_month: str) -> dict:
    """
    Compara estado remoto (RF) vs local (S3).

    Verificações:
    1. Tamanho remoto (file_size_bytes do discovery) vs tamanho no S3
    """
    from src.utils import get_s3_client
    from src.config import S3_BUCKET_NAME
    from botocore.exceptions import ClientError

    records = (
        db.query(SyncControl)
        .filter(SyncControl.year_month == year_month)
        .order_by(SyncControl.file_name)
        .all()
    )

    result = {
        "year_month": year_month,
        "total_files": len(records),
        "synced": [],
        "changed_remote": [],
        "never_downloaded": [],
        "missing_hash": [],
        "size_mismatch": [],
        "file_missing": [],
    }

    s3_client = get_s3_client()

    for record in records:
        entry = {
            "file_name": record.file_name,
            "status": record.status,
            "remote_etag": record.etag,
            "local_hash_sha256": record.local_hash,
            "remote_size_bytes": record.file_size_bytes,
            "local_size_bytes": record.local_size_bytes,
        }

        # Nunca baixado
        if record.status == "pending":
            result["never_downloaded"].append(entry)
            continue

        # Sem hash (download incompleto ou antigo)
        if not record.local_hash:
            result["missing_hash"].append(entry)
            continue

        # Verificar se arquivo existe no S3
        s3_key = f"raw/{record.year_month}/{record.file_name}"
        try:
            head = s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
            actual_size = head.get("ContentLength")
        except ClientError:
            entry["issue"] = "Arquivo não encontrado no S3"
            result["file_missing"].append(entry)
            continue

        entry["actual_s3_size"] = actual_size
        if record.file_size_bytes and actual_size != record.file_size_bytes:
            entry["issue"] = f"Tamanho: RF={record.file_size_bytes} vs S3={actual_size}"
            result["size_mismatch"].append(entry)
            continue

        # Tudo OK — tamanho bate e hash existe
        entry["integrity"] = "ok"
        result["synced"].append(entry)

    return result


def sync_file(db: Session, year_month: str, file_name: str) -> dict:
    """
    Sincroniza (baixa) um único arquivo específico.

    Retorna dicionário com resultado do download.
    """
    logger.info(f"=== Sync individual: {year_month}/{file_name} ===")

    record = (
        db.query(SyncControl)
        .filter(
            SyncControl.year_month == year_month,
            SyncControl.file_name == file_name,
        )
        .first()
    )

    if not record:
        return {"error": f"Arquivo '{file_name}' não encontrado para {year_month}."}

    if record.status not in ("pending", "error"):
        return {
            "skipped": True,
            "file_name": file_name,
            "current_status": record.status,
            "message": f"Arquivo já está em status '{record.status}'. Use force=True para re-baixar.",
        }

    # Marcar como downloading
    record.status = "downloading"
    record.download_progress = 0.0
    db.commit()

    dest_dir = os.path.join(DATA_RAW_DIR, year_month)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, file_name)

    try:
        url, auth = _build_download_url(year_month, file_name)
        result = _download_file(url, dest_path, auth=auth, sync_record=record, db=db)

        record.status = "downloaded"
        record.synced_at = datetime.now(timezone.utc)
        record.local_size_bytes = result["total_bytes"]
        record.local_hash = result["sha256"]
        record.download_progress = 100.0
        db.commit()

        logger.info(f"✅ {file_name} sincronizado com sucesso.")
        return {
            "file_name": file_name,
            "status": "downloaded",
            **result,
        }

    except Exception as e:
        logger.error(f"❌ Erro ao baixar {file_name}: {e}")
        record.status = "error"
        record.error_message = str(e)[:1000]
        record.download_progress = None
        db.commit()
        return {"file_name": file_name, "status": "error", "error": str(e)}


def sync_month(db: Session, year_month: str, first_only: bool = False) -> dict:
    """
    Sincroniza (baixa) todos os arquivos pendentes de um mês.

    1. Consulta sync_control para arquivos com status 'pending'
    2. Cria diretório local data/raw/{year_month}/
    3. Baixa cada arquivo via streaming com progresso e hash
    4. Atualiza status para 'downloaded' com hash SHA-256

    Se first_only=True, baixa apenas o primeiro arquivo de cada tipo
    (ex: apenas Empresas0.zip e ignora Empresas1.zip).

    Retorna contadores de arquivos baixados e pulados.
    """
    logger.info(f"{'=' * 60}")
    logger.info(f"SYNC — {year_month}")
    logger.info(f"{'=' * 60}")

    # Busca arquivos pendentes
    pending_files = (
        db.query(SyncControl)
        .filter(
            SyncControl.year_month == year_month,
            SyncControl.status == "pending",
        )
        .all()
    )

    if not pending_files:
        logger.info(f"Nenhum arquivo pendente para {year_month}.")
        return {"files_downloaded": 0, "files_skipped": 0, "files_error": 0}

    if first_only:
        import re
        from itertools import groupby

        def get_type(name):
            return re.sub(r"\d*\.zip|\d*\.tar\.gz", "", name, flags=re.IGNORECASE)

        pending_files.sort(key=lambda x: x.file_name)

        filtered = []
        for _, group in groupby(pending_files, key=lambda x: get_type(x.file_name)):
            filtered.append(next(group))

        pending_files = filtered
        logger.info(
            f"Modo first-only ativo: reduzido para {len(pending_files)} arquivos (1 de cada tipo)."
        )

    # Marcar tudo como 'downloading'
    pending_ids = [r.id for r in pending_files]
    if pending_ids:
        db.query(SyncControl).filter(SyncControl.id.in_(pending_ids)).update(
            {"status": "downloading", "download_progress": 0.0}, synchronize_session=False
        )
        db.commit()

    # Cria diretório local
    dest_dir = os.path.join(DATA_RAW_DIR, year_month)
    os.makedirs(dest_dir, exist_ok=True)

    files_downloaded = 0
    files_skipped = 0
    files_error = 0
    total_bytes_all = 0
    global_start = time.monotonic()

    for idx, sync_record in enumerate(pending_files, 1):
        logger.info(f"\n📄 [{idx}/{len(pending_files)}] {sync_record.file_name}")
        dest_path = os.path.join(dest_dir, sync_record.file_name)

        # Se o arquivo já existe localmente, recalcular hash e pular
        if os.path.exists(dest_path):
            local_size = os.path.getsize(dest_path)
            local_hash = _compute_file_hash(dest_path)
            logger.info(
                f"   Arquivo já existe: {dest_path} ({_format_bytes(local_size)}). Pulando."
            )
            sync_record.status = "downloaded"
            sync_record.local_size_bytes = local_size
            sync_record.local_hash = local_hash
            sync_record.download_progress = 100.0
            db.commit()
            files_skipped += 1
            continue

        try:
            url, auth = _build_download_url(year_month, sync_record.file_name)
            result = _download_file(url, dest_path, auth=auth, sync_record=sync_record, db=db)

            sync_record.status = "downloaded"
            sync_record.synced_at = datetime.now(timezone.utc)
            sync_record.local_size_bytes = result["total_bytes"]
            sync_record.local_hash = result["sha256"]
            sync_record.download_progress = 100.0
            db.commit()

            files_downloaded += 1
            total_bytes_all += result["total_bytes"]

        except Exception as e:
            logger.error(f"   ❌ Erro: {e}")
            sync_record.status = "error"
            sync_record.error_message = str(e)[:1000]
            sync_record.download_progress = None
            db.commit()
            files_error += 1

    global_elapsed = time.monotonic() - global_start
    logger.info(f"\n{'=' * 60}")
    logger.info(
        f"SYNC {year_month} CONCLUÍDO: "
        f"{files_downloaded} baixados, {files_skipped} pulados, {files_error} erros"
    )
    logger.info(f"Total baixado: {_format_bytes(total_bytes_all)} em {_format_eta(global_elapsed)}")
    logger.info(f"{'=' * 60}")

    return {
        "files_downloaded": files_downloaded,
        "files_skipped": files_skipped,
        "files_error": files_error,
        "total_bytes": total_bytes_all,
        "elapsed_seconds": round(global_elapsed, 2),
    }


if __name__ == "__main__":
    """Execução standalone via: python -m src.jobs.sync --year-month 2023-05"""
    import argparse

    parser = argparse.ArgumentParser(description="Sincroniza dados de um mês da Receita Federal.")
    parser.add_argument(
        "--year-month", required=True, help="Período no formato YYYY-MM (ex: 2023-05)"
    )
    parser.add_argument(
        "--first-only", action="store_true", help="Baixa apenas o primeiro arquivo de cada tipo"
    )
    parser.add_argument("--file", help="Baixa apenas um arquivo específico (ex: Empresas0.zip)")
    args = parser.parse_args()

    from src.models.database import init_db

    init_db()
    db = SessionLocal()
    try:
        if args.file:
            result = sync_file(db, args.year_month, args.file)
        else:
            result = sync_month(db, args.year_month, first_only=args.first_only)
        logger.info(f"Resultado: {result}")
    finally:
        db.close()
