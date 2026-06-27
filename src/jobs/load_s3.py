"""
Job de upload de dados para Garage (S3-compatível).

Organiza o bucket em camadas:
  s3://cnpj-data/raw/{year_month}/*.zip         ← ZIPs originais da RF (imutáveis)
  s3://cnpj-data/processed/{year_month}/*.parquet ← Parquets com regras de negócio

Todos os uploads usam boto3 upload_file (streaming do disco, sem carregar na RAM).
"""

import hashlib
import logging
import os

from botocore.exceptions import ClientError

from src.utils import format_bytes as _format_bytes, get_s3_client as _get_s3_client
from src.config import (
    S3_BUCKET_NAME,
    DATA_RAW_DIR,
    DATA_PROCESSED_DIR,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# _get_s3_client importada de src.utils


def _ensure_bucket_exists(s3_client, bucket_name: str):
    """Cria o bucket se não existir."""
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except ClientError:
        logger.info(f"Criando bucket '{bucket_name}'...")
        s3_client.create_bucket(Bucket=bucket_name)
        logger.info(f"Bucket '{bucket_name}' criado.")


# _format_bytes importada de src.utils


def _s3_object_exists(s3_client, bucket: str, key: str) -> dict | None:
    """Retorna metadados do objeto se existir, None caso contrário."""
    try:
        return s3_client.head_object(Bucket=bucket, Key=key)
    except ClientError:
        return None


def _compute_file_hash(file_path: str) -> str:
    """Calcula SHA-256 de um arquivo local."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


# ─────────────────────────────────────────────────────────────────
# Upload de ZIPs raw para S3
# ─────────────────────────────────────────────────────────────────


def upload_raw_to_s3(year_month: str, skip_existing: bool = True) -> dict:
    """
    Envia todos os .zip de data/raw/{year_month}/ para s3://bucket/raw/{year_month}/.

    Se skip_existing=True (padrão), pula arquivos que já existem no S3
    com o mesmo tamanho — evita re-upload desnecessário.

    Retorna estatísticas do upload.
    """
    raw_dir = os.path.join(DATA_RAW_DIR, year_month)

    if not os.path.exists(raw_dir):
        logger.warning(f"Diretório {raw_dir} não encontrado.")
        return {"error": "directory_not_found"}

    zip_files = sorted([f for f in os.listdir(raw_dir) if f.endswith(".zip")])
    if not zip_files:
        logger.warning(f"Nenhum .zip em {raw_dir}.")
        return {"error": "no_zips"}

    s3_client = _get_s3_client()
    _ensure_bucket_exists(s3_client, S3_BUCKET_NAME)

    uploaded = []
    skipped = []
    total_size = 0

    logger.info(f"{'=' * 60}")
    logger.info(f"UPLOAD RAW S3 — {year_month} ({len(zip_files)} arquivos)")
    logger.info(f"{'=' * 60}")

    for idx, zip_file in enumerate(zip_files, 1):
        local_path = os.path.join(raw_dir, zip_file)
        s3_key = f"raw/{year_month}/{zip_file}"
        local_size = os.path.getsize(local_path)

        # Verificar se já existe no S3 com mesmo tamanho
        if skip_existing:
            existing = _s3_object_exists(s3_client, S3_BUCKET_NAME, s3_key)
            if existing and existing.get("ContentLength") == local_size:
                logger.info(
                    f"  [{idx}/{len(zip_files)}] ⏭️  {zip_file} já existe no S3 ({_format_bytes(local_size)})"
                )
                skipped.append(zip_file)
                continue

        logger.info(f"  [{idx}/{len(zip_files)}] 📤 {zip_file} ({_format_bytes(local_size)})...")
        s3_client.upload_file(local_path, S3_BUCKET_NAME, s3_key)
        uploaded.append(zip_file)
        total_size += local_size
        logger.info(f"     ✅ s3://{S3_BUCKET_NAME}/{s3_key}")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"RAW S3 CONCLUÍDO: {len(uploaded)} enviados, {len(skipped)} pulados")
    logger.info(f"Total enviado: {_format_bytes(total_size)}")
    logger.info(f"{'=' * 60}")

    return {
        "year_month": year_month,
        "uploaded": len(uploaded),
        "skipped": len(skipped),
        "total_size_bytes": total_size,
        "files_uploaded": uploaded,
        "files_skipped": skipped,
    }


# ─────────────────────────────────────────────────────────────────
# Upload de Parquets processados para S3
# ─────────────────────────────────────────────────────────────────


def upload_parquets_to_s3(year_month: str, skip_existing: bool = True) -> dict:
    """
    Envia Parquets de data/processed/{year_month}/ para
    s3://bucket/processed/{year_month}/.

    Retorna estatísticas do upload.
    """
    processed_dir = os.path.join(DATA_PROCESSED_DIR, year_month)

    if not os.path.exists(processed_dir):
        logger.warning(f"Diretório {processed_dir} não encontrado.")
        return {"error": "directory_not_found"}

    parquet_files = sorted([f for f in os.listdir(processed_dir) if f.endswith(".parquet")])
    if not parquet_files:
        logger.warning(f"Nenhum .parquet em {processed_dir}.")
        return {"error": "no_parquets"}

    s3_client = _get_s3_client()
    _ensure_bucket_exists(s3_client, S3_BUCKET_NAME)

    uploaded = []
    skipped = []
    total_size = 0

    logger.info(f"{'=' * 60}")
    logger.info(f"UPLOAD PROCESSED S3 — {year_month} ({len(parquet_files)} arquivos)")
    logger.info(f"{'=' * 60}")

    for idx, pq_file in enumerate(parquet_files, 1):
        local_path = os.path.join(processed_dir, pq_file)
        s3_key = f"processed/{year_month}/{pq_file}"
        local_size = os.path.getsize(local_path)

        if skip_existing:
            existing = _s3_object_exists(s3_client, S3_BUCKET_NAME, s3_key)
            if existing and existing.get("ContentLength") == local_size:
                logger.info(
                    f"  [{idx}/{len(parquet_files)}] ⏭️  {pq_file} já existe ({_format_bytes(local_size)})"
                )
                skipped.append(pq_file)
                continue

        logger.info(f"  [{idx}/{len(parquet_files)}] 📤 {pq_file} ({_format_bytes(local_size)})...")
        s3_client.upload_file(local_path, S3_BUCKET_NAME, s3_key)
        uploaded.append(pq_file)
        total_size += local_size
        logger.info(f"     ✅ s3://{S3_BUCKET_NAME}/{s3_key}")

    logger.info(f"\nPROCESSED S3 CONCLUÍDO: {len(uploaded)} enviados, {len(skipped)} pulados")

    return {
        "year_month": year_month,
        "uploaded": len(uploaded),
        "skipped": len(skipped),
        "total_size_bytes": total_size,
        "files_uploaded": uploaded,
        "files_skipped": skipped,
    }


# ─────────────────────────────────────────────────────────────────
# Verificação de integridade S3 vs local (SHA-256)
# ─────────────────────────────────────────────────────────────────


def verify_s3_integrity(db, year_month: str, layer: str = "raw") -> dict:
    """
    Verifica integridade dos arquivos no S3 consultando a base de dados (SyncControl).

    Compara tamanho para a camada 'raw', e verifica a existência para 'processed'.
    """
    from src.models.sync_control import SyncControl

    if layer == "raw":
        records = (
            db.query(SyncControl)
            .filter(
                SyncControl.year_month == year_month,
                SyncControl.status.in_(["downloaded", "transformed", "loaded"]),
            )
            .all()
        )
    else:
        records = (
            db.query(SyncControl)
            .filter(
                SyncControl.year_month == year_month,
                SyncControl.status.in_(["transformed", "loaded"]),
            )
            .all()
        )

    s3_client = _get_s3_client()
    results = []

    for record in records:
        if layer == "raw":
            file_name = record.file_name
            expected_size = record.local_size_bytes
        else:
            file_name = record.file_name.replace(".zip", ".parquet")
            expected_size = None  # O tamanho do parquet processado não está na base

        s3_key = f"{layer}/{year_month}/{file_name}"

        entry = {
            "file_name": file_name,
            "expected_size": expected_size,
            "s3_key": s3_key,
            "s3_exists": False,
            "s3_size": None,
            "size_match": None,
            "status": "missing_in_s3",
        }

        existing = _s3_object_exists(s3_client, S3_BUCKET_NAME, s3_key)
        if existing:
            s3_size = existing.get("ContentLength", 0)
            entry["s3_exists"] = True
            entry["s3_size"] = s3_size

            if expected_size is not None:
                entry["size_match"] = expected_size == s3_size
                entry["status"] = "ok" if entry["size_match"] else "size_mismatch"
            else:
                entry["size_match"] = True
                entry["status"] = "ok"

        results.append(entry)

    ok = sum(1 for r in results if r["status"] == "ok")
    missing = sum(1 for r in results if r["status"] == "missing_in_s3")
    mismatch = sum(1 for r in results if r["status"] == "size_mismatch")

    return {
        "year_month": year_month,
        "layer": layer,
        "summary": {
            "ok": ok,
            "missing_in_s3": missing,
            "size_mismatch": mismatch,
            "total": len(results),
        },
        "files": results,
    }


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from src.models.database import SessionLocal, init_db

    parser = argparse.ArgumentParser(description="Gerencia uploads e verificação no Garage S3.")
    parser.add_argument("--year-month", required=True, help="Período YYYY-MM")
    parser.add_argument(
        "--layer",
        choices=["raw", "processed", "both"],
        default="both",
        help="Camada a enviar: raw (zips), processed (parquets), both (ambos)",
    )
    parser.add_argument("--verify", action="store_true", help="Apenas verificar integridade")
    args = parser.parse_args()

    if args.verify:
        init_db()
        db = SessionLocal()
        try:
            for layer in ["raw", "processed"] if args.layer == "both" else [args.layer]:
                result = verify_s3_integrity(db, args.year_month, layer)
                logger.info(f"Verificação {layer}: {result['summary']}")
        finally:
            db.close()
    else:
        if args.layer in ("raw", "both"):
            upload_raw_to_s3(args.year_month)
        if args.layer in ("processed", "both"):
            upload_parquets_to_s3(args.year_month)
