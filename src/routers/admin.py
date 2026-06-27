"""
Router de administração e dashboard de sincronização.

Permite visualizar o universo completo de dados da Receita Federal,
verificar o que já foi sincronizado, disparar syncs seletivos,
acompanhar progresso de downloads e verificar integridade.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.models.database import get_db
from src.models.sync_control import SyncControl

router = APIRouter(prefix="/admin", tags=["Admin — Sincronização"])


@router.get(
    "/sync",
    summary="Dashboard de sincronização",
    description=(
        "Visão geral do universo de dados da Receita Federal. "
        "Mostra todos os meses disponíveis, quantos arquivos cada um contém "
        "e o status de sincronização (pendente, baixado, processado, etc.)."
    ),
    response_description="Resumo do universo de dados por mês.",
)
async def dashboard_sync(db: Session = Depends(get_db)):
    """
    Retorna o estado completo da sincronização agrupado por mês.

    Para cada `year_month`, exibe:
    - Total de arquivos descobertos e tamanho estimado
    - Quantos estão pendentes, baixados, transformados, carregados ou com erro
    """
    # Agrupa por year_month e status, somando os tamanhos
    stats = (
        db.query(
            SyncControl.year_month,
            SyncControl.status,
            func.count(SyncControl.id).label("count"),
            func.sum(SyncControl.file_size_bytes).label("total_size_bytes"),
        )
        .group_by(SyncControl.year_month, SyncControl.status)
        .order_by(SyncControl.year_month.desc())
        .all()
    )

    # Monta a visão agrupada
    months = {}
    for row in stats:
        ym = row.year_month
        if ym not in months:
            months[ym] = {
                "year_month": ym,
                "total_files": 0,
                "total_size_bytes": 0,
                "by_status": {},
            }
        months[ym]["by_status"][row.status] = row.count
        months[ym]["total_files"] += row.count
        months[ym]["total_size_bytes"] += row.total_size_bytes or 0

    # Totais globais
    total_files = sum(m["total_files"] for m in months.values())
    total_size_bytes = sum(m["total_size_bytes"] for m in months.values())
    total_pending = sum(m["by_status"].get("pending", 0) for m in months.values())
    total_loaded = sum(m["by_status"].get("loaded", 0) for m in months.values())

    return {
        "summary": {
            "total_months": len(months),
            "total_files": total_files,
            "total_size_bytes": total_size_bytes,
            "total_size_gb": round(total_size_bytes / (1024**3), 2),
            "total_pending": total_pending,
            "total_loaded": total_loaded,
        },
        "months": [
            {
                **m,
                "total_size_gb": round(m["total_size_bytes"] / (1024**3), 2),
            }
            for m in months.values()
        ],
    }


@router.get(
    "/sync/{year_month}",
    summary="Detalhes de sincronização de um mês",
    description="Lista todos os arquivos de um mês específico com seu status detalhado.",
    response_description="Lista de arquivos do mês com status individual.",
)
async def detalhes_sync_mes(
    year_month: str,
    db: Session = Depends(get_db),
):
    """
    Detalhes de sincronização para um mês específico.

    - **year_month**: Período no formato YYYY-MM (ex: 2023-05)
    """
    files = (
        db.query(SyncControl)
        .filter(SyncControl.year_month == year_month)
        .order_by(SyncControl.file_name)
        .all()
    )

    if not files:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum dado encontrado para o período '{year_month}'. Execute /admin/sync/discover primeiro.",
        )

    return {
        "year_month": year_month,
        "total": len(files),
        "files": [
            {
                "file_name": f.file_name,
                "file_size_bytes": f.file_size_bytes,
                "local_size_bytes": f.local_size_bytes,
                "local_hash": f.local_hash,
                "etag": f.etag,
                "status": f.status,
                "download_progress": f.download_progress,
                "discovered_at": f.discovered_at.isoformat() if f.discovered_at else None,
                "synced_at": f.synced_at.isoformat() if f.synced_at else None,
                "error_message": f.error_message,
            }
            for f in files
        ],
    }


@router.post(
    "/sync/discover",
    summary="Descobrir dados disponíveis",
    description=(
        "Faz scraping do índice da Receita Federal para descobrir "
        "novas pastas (meses) e arquivos disponíveis para download."
    ),
    response_description="Resultado da descoberta.",
)
async def trigger_discovery(db: Session = Depends(get_db)):
    """
    Dispara o processo de descoberta de dados na Receita Federal.

    Conecta ao portal, lista as pastas YYYY-MM disponíveis,
    e para cada pasta lista os arquivos .zip. Registra tudo
    na tabela sync_control com status 'pending'.
    """
    from src.jobs.discovery import discover_available_data

    try:
        result = discover_available_data(db)
        return {
            "status": "success",
            "message": "Descoberta concluída.",
            "new_months": result.get("new_months", 0),
            "new_files": result.get("new_files", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na descoberta: {str(e)}")


@router.post(
    "/sync/{year_month}",
    summary="Sincronizar dados de um mês (assíncrono)",
    description=(
        "Dispara o download dos arquivos de um mês específico em segundo plano. "
        "O processamento ocorre de forma assíncrona para não travar a API."
    ),
    response_description="Confirmação do agendamento.",
)
async def trigger_sync(
    year_month: str,
    background_tasks: BackgroundTasks,
    first_only: bool = False,
    db: Session = Depends(get_db),
):
    """
    Dispara a sincronização (download) de um mês específico em background.

    - **year_month**: Período no formato YYYY-MM (ex: 2023-05)
    - **first_only**: Se True, baixa apenas o primeiro arquivo de cada tipo.
    """
    # Verifica se o mês existe no sync_control
    exists = db.query(SyncControl).filter(SyncControl.year_month == year_month).first()

    if not exists:
        raise HTTPException(
            status_code=404,
            detail=f"Mês '{year_month}' não encontrado. Execute /admin/sync/discover primeiro.",
        )

    # Cria wrapper para criar a própria sessão de banco rodando em bg
    def run_sync_in_background(target_month: str, f_only: bool):
        from src.jobs.sync import sync_month
        from src.models.database import SessionLocal

        bg_db = SessionLocal()
        try:
            sync_month(bg_db, target_month, first_only=f_only)
        finally:
            bg_db.close()

    # Adiciona a tarefa na fila do FastAPI
    background_tasks.add_task(run_sync_in_background, year_month, first_only)

    return {
        "status": "accepted",
        "message": f"Sincronização para {year_month} agendada em segundo plano.",
        "year_month": year_month,
        "first_only": first_only,
    }


@router.post(
    "/sync/{year_month}/file/{file_name}",
    summary="Baixar arquivo individual",
    description=(
        "Dispara o download de um arquivo específico de um mês em segundo plano. "
        "Útil para testes parciais e para baixar apenas parte dos dados."
    ),
    response_description="Confirmação do agendamento do download individual.",
)
async def trigger_sync_file(
    year_month: str,
    file_name: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Dispara o download de um único arquivo específico.

    - **year_month**: Período no formato YYYY-MM (ex: 2025-06)
    - **file_name**: Nome exato do arquivo (ex: Empresas0.zip)
    """
    record = (
        db.query(SyncControl)
        .filter(
            SyncControl.year_month == year_month,
            SyncControl.file_name == file_name,
        )
        .first()
    )

    if not record:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Arquivo '{file_name}' não encontrado para {year_month}. "
                "Execute /admin/sync/discover primeiro."
            ),
        )

    def run_file_sync_bg(target_month: str, target_file: str):
        from src.jobs.sync import sync_file
        from src.models.database import SessionLocal

        bg_db = SessionLocal()
        try:
            sync_file(bg_db, target_month, target_file)
        finally:
            bg_db.close()

    background_tasks.add_task(run_file_sync_bg, year_month, file_name)

    return {
        "status": "accepted",
        "message": f"Download de {file_name} ({year_month}) agendado em segundo plano.",
        "year_month": year_month,
        "file_name": file_name,
        "current_status": record.status,
    }


@router.get(
    "/sync/{year_month}/progress",
    summary="Progresso de downloads",
    description="Mostra o progresso em tempo real dos downloads em andamento para um mês.",
    response_description="Lista de arquivos com progresso de download.",
)
async def sync_progress(
    year_month: str,
    db: Session = Depends(get_db),
):
    """
    Retorna o progresso de download de todos os arquivos de um mês.

    Inclui porcentagem, tamanho baixado vs total, e status.
    """
    records = (
        db.query(SyncControl)
        .filter(SyncControl.year_month == year_month)
        .order_by(SyncControl.file_name)
        .all()
    )

    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum dado encontrado para '{year_month}'.",
        )

    downloading = []
    completed = []
    pending = []
    errored = []

    for r in records:
        entry = {
            "file_name": r.file_name,
            "status": r.status,
            "progress": r.download_progress,
            "remote_size_bytes": r.file_size_bytes,
            "local_size_bytes": r.local_size_bytes,
        }

        if r.status == "downloading":
            downloading.append(entry)
        elif r.status in ("downloaded", "transformed", "loaded"):
            completed.append(entry)
        elif r.status == "error":
            entry["error_message"] = r.error_message
            errored.append(entry)
        else:
            pending.append(entry)

    return {
        "year_month": year_month,
        "summary": {
            "downloading": len(downloading),
            "completed": len(completed),
            "pending": len(pending),
            "errored": len(errored),
        },
        "downloading": downloading,
        "completed": completed,
        "pending": pending,
        "errored": errored,
    }


@router.post(
    "/sync/{year_month}/verify",
    summary="Verificar integridade dos arquivos no S3",
    description=(
        "Verifica se os arquivos existem no S3 e se o tamanho confere. "
        "Use ?full_check=true para forçar o download e recálculo do SHA-256 (lento)."
    ),
    response_description="Lista de inconsistências encontradas.",
)
async def verify_integrity(
    year_month: str,
    full_check: bool = False,
    db: Session = Depends(get_db),
):
    """
    Verifica integridade dos arquivos baixados para um mês.

    Por padrão, verifica apenas o metadata no S3 (tamanho e existência).
    Se full_check=True, recalcula SHA-256 baixando via streaming.
    """
    from src.jobs.sync import verify_file_integrity

    issues = verify_file_integrity(db, year_month, full_check=full_check)

    return {
        "year_month": year_month,
        "integrity": "ok" if not issues else "issues_found",
        "issues_count": len(issues),
        "issues": issues,
    }


@router.get(
    "/sync/{year_month}/diff",
    summary="Hash diff: remoto vs local",
    description=(
        "Compara o ETag remoto (obtido no discovery) com o hash local (SHA-256). "
        "Mostra quais arquivos mudaram remotamente, quais estão em sincronia, "
        "e quais nunca foram baixados."
    ),
    response_description="Análise comparativa remoto vs local.",
)
async def hash_diff(
    year_month: str,
    db: Session = Depends(get_db),
):
    """
    Compara estado remoto vs local para um mês.

    Mostra quais arquivos estão sincronizados, quais mudaram
    remotamente e quais nunca foram baixados.
    """
    from src.jobs.sync import compare_remote_vs_local

    result = compare_remote_vs_local(db, year_month)

    return {
        **result,
        "summary": {
            "synced": len(result["synced"]),
            "changed_remote": len(result["changed_remote"]),
            "never_downloaded": len(result["never_downloaded"]),
            "missing_hash": len(result["missing_hash"]),
        },
    }


# ─────────────────────────────────────────────────────────────────
# Transform — controle via API
# ─────────────────────────────────────────────────────────────────


@router.post(
    "/transform/{year_month}",
    summary="Transformar dados de um mês (zip → parquet)",
    description=(
        "Dispara a transformação de todos os arquivos raw em segundo plano. "
        "Os .zip NUNCA são deletados. "
        "Use ?first_only=true para processar apenas 1 de cada tipo (teste rápido)."
    ),
)
async def trigger_transform(
    year_month: str,
    background_tasks: BackgroundTasks,
    first_only: bool = False,
    db: Session = Depends(get_db),
):
    from src.models.sync_control import SyncControl

    records = (
        db.query(SyncControl)
        .filter(
            SyncControl.year_month == year_month,
            SyncControl.status.in_(["downloaded", "transformed", "loaded"]),
        )
        .all()
    )

    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum arquivo pendente/baixado em {year_month}. Rode o sync primeiro.",
        )

    def run_transform_bg(month: str, f_only: bool):
        from src.jobs.transform import transform_data
        from src.models.database import SessionLocal

        bg_db = SessionLocal()
        try:
            transform_data(bg_db, month, first_only=f_only)
        finally:
            bg_db.close()

    background_tasks.add_task(run_transform_bg, year_month, first_only)

    return {
        "status": "accepted",
        "message": f"Transform para {year_month} agendado em segundo plano.",
        "year_month": year_month,
        "zip_files_found": len(records),
        "first_only": first_only,
        "tip": f"Acompanhe em GET /admin/transform/{year_month}/status",
    }


@router.post(
    "/transform/{year_month}/file/{file_name}",
    summary="Transformar arquivo individual (zip → parquet)",
    description=(
        "Transforma um único arquivo em segundo plano. "
        "Use ?force=true para reprocessar mesmo que o parquet já exista."
    ),
)
async def trigger_transform_file(
    year_month: str,
    file_name: str,
    background_tasks: BackgroundTasks,
    force: bool = False,
    db: Session = Depends(get_db),
):
    import os
    from src.config import DATA_RAW_DIR, DATA_PROCESSED_DIR
    from src.models.sync_control import SyncControl

    record = (
        db.query(SyncControl)
        .filter(SyncControl.year_month == year_month, SyncControl.file_name == file_name)
        .first()
    )

    if not record or record.status not in ["downloaded", "transformed", "loaded"]:
        raise HTTPException(
            status_code=404,
            detail=f"Arquivo {file_name} não encontrado ou não baixado para {year_month}.",
        )

    output_path = os.path.join(
        DATA_PROCESSED_DIR, year_month, file_name.replace(".zip", ".parquet")
    )

    if record.status in ["transformed", "loaded"] and not force:
        return {
            "status": "skipped",
            "message": f"Parquet já processado no S3. Use ?force=true para reprocessar.",
        }

    def run_file_transform_bg(zip_name: str, month: str, force_flag: bool):
        import os as _os
        from src.jobs.transform import process_file
        from src.config import DATA_RAW_DIR, DATA_PROCESSED_DIR

        zip_p = _os.path.join(DATA_RAW_DIR, month, zip_name)
        out_p = _os.path.join(DATA_PROCESSED_DIR, month, zip_name.replace(".zip", ".parquet"))

        if force_flag and _os.path.exists(out_p):
            _os.remove(out_p)
        _os.makedirs(_os.path.dirname(out_p), exist_ok=True)

        from src.models.database import SessionLocal

        bg_db = SessionLocal()
        try:
            process_file(bg_db, zip_p, out_p, month)
        finally:
            bg_db.close()

    background_tasks.add_task(run_file_transform_bg, file_name, year_month, force)

    return {
        "status": "accepted",
        "message": f"Transform de {file_name} ({year_month}) agendado.",
        "year_month": year_month,
        "file_name": file_name,
        "output_path": output_path,
        "force": force,
    }


@router.get(
    "/transform/{year_month}/status",
    summary="Status dos parquets transformados",
    description=(
        "Cruza os .zip de data/raw com os .parquet de data/processed. "
        "Mostra contagem de linhas, tamanho e status de cada arquivo."
    ),
)
async def transform_status(year_month: str, db: Session = Depends(get_db)):
    import os
    import pyarrow.parquet as pq
    from src.config import DATA_PROCESSED_DIR
    from src.jobs.transform import LAYOUTS, _get_file_type
    from src.models.sync_control import SyncControl

    processed_dir = os.path.join(DATA_PROCESSED_DIR, year_month)

    records = (
        db.query(SyncControl)
        .filter(
            SyncControl.year_month == year_month,
            SyncControl.status.in_(["downloaded", "transformed", "loaded"]),
        )
        .all()
    )

    if not records:
        raise HTTPException(
            status_code=404, detail=f"Nenhum arquivo baixado para o mês {year_month}."
        )

    files_status = []
    total_rows = 0
    total_parquet_mb = 0.0

    for record in records:
        zip_name = record.file_name
        parquet_path = os.path.join(processed_dir, zip_name.replace(".zip", ".parquet"))
        file_type = _get_file_type(zip_name)
        mapped = file_type in LAYOUTS

        entry = {
            "file_name": zip_name,
            "file_type": file_type,
            "mapped": mapped,
            "zip_size_mb": round(record.local_size_bytes / (1024 * 1024), 1)
            if record.local_size_bytes
            else None,
            "parquet_exists_local": False,
            "parquet_size_mb_local": None,
            "row_count": None,
            "status": "not_mapped" if not mapped else record.status,
        }

        if os.path.exists(parquet_path):
            parquet_mb = os.path.getsize(parquet_path) / (1024 * 1024)
            entry["parquet_exists_local"] = True
            entry["parquet_size_mb_local"] = round(parquet_mb, 1)
            total_parquet_mb += parquet_mb
            try:
                rows = pq.read_metadata(parquet_path).num_rows
                entry["row_count"] = rows
                total_rows += rows
            except Exception:
                entry["row_count"] = None

        files_status.append(entry)

    return {
        "year_month": year_month,
        "summary": {
            "total_zips": len(records),
            "transformed": sum(1 for f in files_status if f["status"] in ("transformed", "loaded")),
            "pending": sum(1 for f in files_status if f["status"] == "downloaded"),
            "not_mapped": sum(1 for f in files_status if f["status"] == "not_mapped"),
            "total_rows_local": total_rows,
            "total_parquet_gb_local": round(total_parquet_mb / 1024, 2),
        },
        "files": files_status,
    }


# ─────────────────────────────────────────────────────────────────
# Load S3 — controle via API
# ─────────────────────────────────────────────────────────────────


@router.post(
    "/load-s3/{year_month}",
    summary="Upload para Garage S3 (raw + processed)",
    description=(
        "Envia arquivos para o S3 organizados em camadas:\n"
        "- `raw/{ym}/*.zip` — ZIPs originais da RF\n"
        "- `processed/{ym}/*.parquet` — Parquets processados\n\n"
        "Use ?layer=raw para enviar apenas ZIPs, ?layer=processed para Parquets, "
        "ou ?layer=both (padrão) para ambos. Pula arquivos que já existem no S3."
    ),
)
async def trigger_load_s3(
    year_month: str,
    background_tasks: BackgroundTasks,
    layer: str = "both",
):
    if layer not in ("raw", "processed", "both"):
        raise HTTPException(status_code=400, detail="layer deve ser 'raw', 'processed' ou 'both'.")

    def run_s3_bg(month: str, target_layer: str):
        from src.jobs.load_s3 import upload_raw_to_s3, upload_parquets_to_s3

        if target_layer in ("raw", "both"):
            upload_raw_to_s3(month)
        if target_layer in ("processed", "both"):
            upload_parquets_to_s3(month)

    background_tasks.add_task(run_s3_bg, year_month, layer)

    return {
        "status": "accepted",
        "message": f"Upload S3 para {year_month} agendado (layer={layer}).",
        "year_month": year_month,
        "layer": layer,
        "tip": f"Acompanhe em GET /s3/objects?prefix=raw/{year_month}/",
    }


@router.get(
    "/load-s3/{year_month}/status",
    summary="Status do S3 por camada",
    description="Verifica se os arquivos esperados estão presentes no S3 consultando a base de controle.",
)
async def load_s3_status(
    year_month: str,
    layer: str = "raw",
    db: Session = Depends(get_db),
):
    from src.jobs.load_s3 import verify_s3_integrity

    if layer not in ("raw", "processed"):
        raise HTTPException(status_code=400, detail="layer deve ser 'raw' ou 'processed'.")

    return verify_s3_integrity(db, year_month, layer)


# ─────────────────────────────────────────────────────────────────
# Load DB — controle via API
# ─────────────────────────────────────────────────────────────────


@router.post(
    "/load-db/{year_month}",
    summary="Carregar Parquets no PostgreSQL (COPY)",
    description=(
        "Carrega todos os Parquets de data/processed/{year_month}/ no PostgreSQL "
        "via COPY (streaming, sem carregar tudo na memória). "
        "Use ?if_exists=replace para truncar tabelas antes da carga, "
        "?if_exists=skip para pular tabelas que já têm dados, "
        "ou ?if_exists=append (padrão) para acumular."
    ),
)
async def trigger_load_db(
    year_month: str,
    background_tasks: BackgroundTasks,
    if_exists: str = "append",
    db: Session = Depends(get_db),
):
    from src.models.sync_control import SyncControl

    if if_exists not in ("append", "replace", "skip"):
        raise HTTPException(
            status_code=400, detail="if_exists deve ser 'append', 'replace' ou 'skip'."
        )

    records = (
        db.query(SyncControl)
        .filter(
            SyncControl.year_month == year_month, SyncControl.status.in_(["transformed", "loaded"])
        )
        .all()
    )

    if not records:
        raise HTTPException(
            status_code=404,
            detail="Nenhum arquivo transformado/carregado encontrado. Rode o transform primeiro.",
        )

    def run_load_db_bg(month: str, mode: str):
        from src.jobs.load_db import load_to_postgres
        from src.models.database import SessionLocal

        bg_db = SessionLocal()
        try:
            load_to_postgres(year_month=month, db=bg_db, if_exists=mode)
        finally:
            bg_db.close()

    background_tasks.add_task(run_load_db_bg, year_month, if_exists)

    return {
        "status": "accepted",
        "message": f"Carga PostgreSQL para {year_month} agendada em segundo plano.",
        "year_month": year_month,
        "parquets_found": len(records),
        "if_exists": if_exists,
        "tip": f"Acompanhe em GET /admin/load-db/{year_month}/status",
    }


@router.post(
    "/load-db/{year_month}/file/{file_name}",
    summary="Carregar Parquet individual no PostgreSQL",
    description=(
        "Carrega um único Parquet em segundo plano. "
        "Use ?if_exists=replace para truncar a tabela correspondente antes. "
        "Use ?if_exists=skip para pular se a tabela já tem dados."
    ),
)
async def trigger_load_db_file(
    year_month: str,
    file_name: str,
    background_tasks: BackgroundTasks,
    if_exists: str = "append",
    db: Session = Depends(get_db),
):
    from src.models.sync_control import SyncControl

    # Aceitar tanto .parquet quanto sem extensão
    if not file_name.endswith(".parquet"):
        file_name = file_name.replace(".zip", "") + ".parquet"

    original_zip_name = file_name.replace(".parquet", ".zip")

    if if_exists not in ("append", "replace", "skip"):
        raise HTTPException(
            status_code=400, detail="if_exists deve ser 'append', 'replace' ou 'skip'."
        )

    record = (
        db.query(SyncControl)
        .filter(SyncControl.year_month == year_month, SyncControl.file_name == original_zip_name)
        .first()
    )

    if not record or record.status not in ["transformed", "loaded"]:
        raise HTTPException(
            status_code=404,
            detail=f"Parquet correspondente a {file_name} não encontrado ou não transformado.",
        )

    if record.status == "loaded" and if_exists == "skip":
        return {
            "status": "skipped",
            "message": f"Parquet já carregado no banco. Use if_exists=replace ou append para forçar.",
        }

    def run_load_file_bg(month: str, target: str, mode: str):
        from src.jobs.load_db import load_to_postgres
        from src.models.database import SessionLocal

        bg_db = SessionLocal()
        try:
            load_to_postgres(year_month=month, db=bg_db, if_exists=mode, target_file=target)
        finally:
            bg_db.close()

    background_tasks.add_task(run_load_file_bg, year_month, file_name, if_exists)

    return {
        "status": "accepted",
        "message": f"Carga de {file_name} ({year_month}) agendada.",
        "year_month": year_month,
        "file_name": file_name,
        "if_exists": if_exists,
    }


@router.get(
    "/load-db/{year_month}/status",
    summary="Status da carga PostgreSQL",
    description=(
        "Mostra quantas linhas cada tabela CNPJ tem no PostgreSQL. "
        "Cruza com os Parquets existentes para indicar o que já foi carregado "
        "e o que ainda falta."
    ),
)
async def load_db_status(year_month: str, db: Session = Depends(get_db)):
    import os
    import pyarrow.parquet as pq
    from src.config import DATA_PROCESSED_DIR
    from src.jobs.load_db import _resolve_table_name
    from src.models.sync_control import SyncControl

    processed_dir = os.path.join(DATA_PROCESSED_DIR, year_month)

    records = (
        db.query(SyncControl)
        .filter(
            SyncControl.year_month == year_month, SyncControl.status.in_(["transformed", "loaded"])
        )
        .all()
    )

    if not records:
        raise HTTPException(
            status_code=404, detail="Nenhum arquivo transformado encontrado para o mês."
        )

    parquets = sorted([r.file_name.replace(".zip", ".parquet") for r in records])

    # Contagem real de linhas no PostgreSQL
    table_counts = {}
    tables_to_check = set()
    for pq_file in parquets:
        table_name = _resolve_table_name(pq_file)
        tables_to_check.add(table_name)

    for table_name in tables_to_check:
        try:
            result = db.execute(__import__("sqlalchemy").text(f"SELECT COUNT(*) FROM {table_name}"))
            table_counts[table_name] = result.scalar()
        except Exception:
            table_counts[table_name] = None

    # Cruzar Parquets com PostgreSQL
    files_status = []
    total_parquet_rows = 0
    total_db_rows = 0

    for pq_file in parquets:
        table_name = _resolve_table_name(pq_file)
        pq_path = os.path.join(processed_dir, pq_file)

        # Linhas no Parquet - só contamos se o arquivo estiver localmente disponivel no /tmp,
        # senao mantemos row count nulo pq nao foi pedido para contar direto do s3
        parquet_rows = None
        try:
            if os.path.exists(pq_path):
                parquet_rows = pq.read_metadata(pq_path).num_rows
                total_parquet_rows += parquet_rows
        except Exception:
            pass

        db_rows = table_counts.get(table_name)
        if db_rows:
            total_db_rows += db_rows

        loaded = db_rows is not None and db_rows > 0

        # Pega status original
        status = "loaded" if loaded else "pending"

        files_status.append(
            {
                "file_name": pq_file,
                "table_name": table_name,
                "parquet_rows": parquet_rows,
                "db_rows": db_rows,
                "status": status,
            }
        )

    # Resumo por tabela (desduplicar — múltiplos Parquets mesma tabela)
    table_summary = {}
    for f in files_status:
        tn = f["table_name"]
        if tn not in table_summary:
            table_summary[tn] = {"parquet_rows": 0, "db_rows": f["db_rows"] or 0}
        if f["parquet_rows"]:
            table_summary[tn]["parquet_rows"] += f["parquet_rows"]

    return {
        "year_month": year_month,
        "summary": {
            "total_parquets": len(parquets),
            "total_parquet_rows": total_parquet_rows,
            "total_db_rows": total_db_rows,
            "coverage_pct": round(total_db_rows / total_parquet_rows * 100, 1)
            if total_parquet_rows
            else 0,
            "tables_with_data": sum(1 for v in table_summary.values() if v["db_rows"] > 0),
            "tables_total": len(table_summary),
        },
        "tables": table_summary,
        "files": files_status,
    }
