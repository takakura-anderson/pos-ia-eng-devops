"""
Job de carga de dados transformados para PostgreSQL.

Lê os Parquets de data/processed/{year_month}/ e persiste nas tabelas
via COPY (psycopg2 binary) — significativamente mais rápido que to_sql.

Estratégia:
- Arquivos pequenos (< LARGE_FILE_THRESHOLD_MB): leitura direta
- Arquivos grandes (>= threshold): leitura em chunks via PyArrow +
  copy_from por lote — mantém RAM constante

A flag `if_exists` controla o comportamento:
  - "append" (padrão): insere sem truncar (idempotente apenas se não há duplicatas)
  - "replace": TRUNCATE TABLE antes de inserir (para reprocessamento)
  - "skip": se a tabela já tem dados, pula o arquivo
"""

import csv
import io
import logging
import os
import re

import pandas as pd
from psycopg2 import sql as psql
import pyarrow.parquet as pq
from sqlalchemy.orm import Session

from src.config import DATA_PROCESSED_DIR
from src.models.database import engine, SessionLocal
from src.models.empresa import Empresa
from src.models.sync_control import SyncControl

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Threshold para leitura em chunks (MB do arquivo Parquet)
LARGE_FILE_THRESHOLD_MB = 50
CHUNK_ROWS = 100_000  # linhas por batch no COPY


# ─────────────────────────────────────────────────────────────────
# Resolução de nomes de tabela
# ─────────────────────────────────────────────────────────────────


def _resolve_table_name(parquet_filename: str) -> str:
    """Determina a tabela destino a partir do nome do Parquet."""
    base = re.sub(r"\d*\.parquet", "", parquet_filename, flags=re.IGNORECASE).lower()

    table_map = {
        "empresas": Empresa.__tablename__,
        "estabelecimentos": "cnpj_estabelecimentos",
        "socios": "cnpj_socios",
        "simples": "cnpj_simples",
        "paises": "cnpj_paises",
        "municipios": "cnpj_municipios",
        "qualificacoes": "cnpj_qualificacoes",
        "naturezas": "cnpj_naturezas",
        "cnaes": "cnpj_cnaes",
        "motivos": "cnpj_motivos",
    }

    for key, table in table_map.items():
        if base.startswith(key):
            return table

    return f"cnpj_{base}"


# ─────────────────────────────────────────────────────────────────
# Funções de inserção via COPY
# ─────────────────────────────────────────────────────────────────


def _df_to_copy_buffer(df: pd.DataFrame) -> io.StringIO:
    """Serializa DataFrame em buffer CSV para uso com COPY FROM."""
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="\\N", quoting=csv.QUOTE_MINIMAL)
    buf.seek(0)
    return buf


def _copy_df_to_table(df: pd.DataFrame, table_name: str, conn) -> int:
    """
    Insere um DataFrame numa tabela via psycopg2 COPY FROM.
    Retorna o número de linhas inseridas.
    """
    columns = list(df.columns)
    buf = _df_to_copy_buffer(df)

    cursor = conn.cursor()
    cursor.copy_expert(
        sql=f"COPY {table_name} ({', '.join(columns)}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')",
        file=buf,
    )
    rows = cursor.rowcount
    cursor.close()
    return rows if rows and rows > 0 else len(df)


def _table_has_data(table_name: str, raw_conn) -> bool:
    """Verifica rapidamente se a tabela tem ao menos 1 linha."""
    cursor = raw_conn.cursor()
    cursor.execute(
        psql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1)").format(psql.Identifier(table_name))
    )
    result = cursor.fetchone()[0]
    cursor.close()
    return result


# ─────────────────────────────────────────────────────────────────
# Carga de um único arquivo Parquet
# ─────────────────────────────────────────────────────────────────


def _load_parquet_file(pq_path: str, table_name: str, if_exists: str, raw_conn) -> int:
    """
    Carrega um único arquivo Parquet na tabela via COPY.

    Decide entre leitura direta ou chunked com base no tamanho.
    Retorna o total de linhas inseridas.
    """
    file_name = os.path.basename(pq_path)
    file_mb = os.path.getsize(pq_path) / (1024 * 1024)

    # --- Modo skip ---
    if if_exists == "skip" and _table_has_data(table_name, raw_conn):
        logger.info(f"  ⏭️  {file_name} → {table_name} já tem dados. Pulando.")
        return 0

    # --- Modo replace: truncate antes ---
    if if_exists == "replace":
        cursor = raw_conn.cursor()
        cursor.execute(
            psql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                psql.Identifier(table_name)
            )
        )
        cursor.close()
        logger.info(f"  🗑️  {table_name} truncada.")

    use_chunks = file_mb >= LARGE_FILE_THRESHOLD_MB
    strategy = "chunked" if use_chunks else "direct"
    logger.info(f"  📄 {file_name} ({file_mb:.0f} MB) → {table_name} [{strategy}]")

    total_rows = 0

    if use_chunks:
        # Leitura em batches via PyArrow
        pq_file = pq.ParquetFile(pq_path)
        batch_count = 0
        for batch in pq_file.iter_batches(batch_size=CHUNK_ROWS):
            chunk_df = batch.to_pandas()
            inserted = _copy_df_to_table(chunk_df, table_name, raw_conn)
            total_rows += inserted
            batch_count += 1
            if batch_count % 10 == 0:
                logger.info(f"     batch {batch_count}: {total_rows:,} linhas inseridas...")
    else:
        df = pd.read_parquet(pq_path)
        total_rows = _copy_df_to_table(df, table_name, raw_conn)

    return total_rows


# ─────────────────────────────────────────────────────────────────
# Função principal
# ─────────────────────────────────────────────────────────────────


def load_to_postgres(
    year_month: str,
    db: Session = None,
    if_exists: str = "append",
    target_file: str = None,
) -> dict:
    """
    Carrega todos os Parquets de um mês no PostgreSQL.

    Parâmetros:
    - year_month : Período YYYY-MM (ex: 2026-04)
    - db         : Sessão SQLAlchemy (para atualizar sync_control)
    - if_exists  : 'append' | 'replace' | 'skip'
    - target_file: Se informado, carrega apenas esse arquivo (ex: 'Empresas1.parquet')

    Retorna dicionário com estatísticas.
    """
    processed_dir = os.path.join(DATA_PROCESSED_DIR, year_month)

    os.makedirs(processed_dir, exist_ok=True)

    if not db:
        raise ValueError("Uma sessão de banco de dados (db) é necessária.")

    records = (
        db.query(SyncControl)
        .filter(
            SyncControl.year_month == year_month, SyncControl.status.in_(["transformed", "loaded"])
        )
        .order_by(SyncControl.file_name)
        .all()
    )

    if not records:
        logger.warning(f"Nenhum arquivo transformado no banco para {year_month}.")
        return {"error": "no_parquets"}

    parquet_files = [r.file_name.replace(".zip", ".parquet") for r in records]

    if target_file:
        parquet_files = [f for f in parquet_files if f == target_file]
        if not parquet_files:
            logger.warning(f"Arquivo '{target_file}' não encontrado no banco para {year_month}.")
            return {"error": "file_not_found"}

    logger.info(f"{'=' * 60}")
    logger.info(f"LOAD DB — {year_month} ({len(parquet_files)} arquivos) [if_exists={if_exists}]")
    logger.info(f"{'=' * 60}")

    results = []
    total_loaded = 0
    errors = 0

    # Usar conexão raw (psycopg2) para COPY
    raw_conn = engine.raw_connection()

    try:
        for idx, pq_file in enumerate(parquet_files, 1):
            pq_path = os.path.join(processed_dir, pq_file)
            table_name = _resolve_table_name(pq_file)

            logger.info(f"\n[{idx}/{len(parquet_files)}] {pq_file} → {table_name}")

            if not os.path.exists(pq_path):
                from src.utils import _get_s3_client, S3_BUCKET_NAME

                s3_client = _get_s3_client()
                s3_key = f"processed/{year_month}/{pq_file}"
                logger.info(f"  ⬇️  Arquivo não encontrado localmente. Baixando do S3: {s3_key}")
                try:
                    s3_client.download_file(S3_BUCKET_NAME, s3_key, pq_path)
                except Exception as e:
                    logger.error(f"  ❌ Erro ao baixar {s3_key} do S3: {e}")
                    results.append(
                        {
                            "file": pq_file,
                            "table": table_name,
                            "error": f"s3_download_failed: {e}",
                            "status": "error",
                        }
                    )
                    errors += 1
                    continue

            try:
                rows = _load_parquet_file(pq_path, table_name, if_exists, raw_conn)
                raw_conn.commit()
                total_loaded += rows
                logger.info(f"  ✅ {rows:,} linhas inseridas em {table_name}")
                results.append({"file": pq_file, "table": table_name, "rows": rows, "status": "ok"})

            except Exception as e:
                raw_conn.rollback()
                errors += 1
                logger.error(f"  ❌ Erro ao carregar {pq_file}: {e}")
                results.append(
                    {"file": pq_file, "table": table_name, "error": str(e), "status": "error"}
                )

        # Atualiza sync_control
        if db and not target_file:
            records = (
                db.query(SyncControl)
                .filter(
                    SyncControl.year_month == year_month,
                    SyncControl.status.in_(["downloaded", "transformed"]),
                )
                .all()
            )
            for record in records:
                record.status = "loaded"
            db.commit()
            logger.info(f"sync_control: {len(records)} registros marcados como 'loaded'.")

    finally:
        raw_conn.close()

    logger.info(f"\n{'=' * 60}")
    logger.info(f"LOAD DB {year_month} CONCLUÍDO")
    logger.info(f"  Arquivos: {len(parquet_files)} | Erros: {errors}")
    logger.info(f"  Total linhas inseridas: {total_loaded:,}")
    logger.info(f"{'=' * 60}")

    return {
        "year_month": year_month,
        "total_files": len(parquet_files),
        "total_loaded": total_loaded,
        "errors": errors,
        "details": results,
    }


# ─────────────────────────────────────────────────────────────────
# CLI standalone
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Carrega Parquets no PostgreSQL via COPY.",
        epilog="Exemplo: python -m src.jobs.load_db --year-month 2026-04",
    )
    parser.add_argument("--year-month", required=True, help="Período YYYY-MM")
    parser.add_argument(
        "--if-exists",
        choices=["append", "replace", "skip"],
        default="append",
        help="Comportamento se tabela já tem dados (padrão: append)",
    )
    parser.add_argument("--file", help="Carregar apenas um Parquet específico")
    args = parser.parse_args()

    from src.models.database import init_db

    init_db()

    db = SessionLocal()
    try:
        result = load_to_postgres(
            year_month=args.year_month,
            db=db,
            if_exists=args.if_exists,
            target_file=args.file,
        )
        logger.info(f"Resultado: {result}")
    finally:
        db.close()
