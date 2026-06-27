"""
Orquestrador do pipeline de ingestão de dados.

Coordena a execução dos jobs na ordem correta:
1. Discovery — descobre dados disponíveis na Receita Federal
2. Sync — baixa arquivos de um mês específico
3. Transform — transforma os dados com pandas
4. Load DB — carrega dados no PostgreSQL
5. Load S3 — envia Parquet para Garage S3

Uso:
    # Pipeline completo para um mês:
    python -m src.ingest --year-month 2023-05

    # Apenas discovery (sem download):
    python -m src.ingest --discover-only

    # Pipeline com apenas o primeiro arquivo de cada tipo:
    python -m src.ingest --year-month 2023-05 --first-only
"""

import argparse
import logging

from src.models.database import init_db, SessionLocal
from src.jobs.discovery import discover_available_data
from src.jobs.sync import sync_month
from src.jobs.transform import transform_data
from src.jobs.load_db import load_to_postgres
from src.jobs.load_s3 import upload_parquets_to_s3

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def run_pipeline(
    year_month: str = None,
    discover_only: bool = False,
    first_only: bool = False,
):
    """
    Executa o pipeline completo de ingestão.

    Parâmetros:
    - year_month: Período a sincronizar (ex: 2023-05). Se None, faz apenas discovery.
    - discover_only: Se True, executa apenas o discovery sem download.
    - first_only: Se True, baixa/processa apenas o primeiro arquivo de cada tipo.
    """
    logger.info("=" * 60)
    logger.info("PIPELINE DE INGESTÃO — RECEITA FEDERAL CNPJ")
    logger.info("=" * 60)

    # Inicializa banco de dados (cria tabelas se não existirem)
    init_db()
    logger.info("✅ Banco de dados inicializado.")

    db = SessionLocal()

    try:
        # Step 1: Discovery
        logger.info("\n📌 Step 1/5 — Discovery")
        discovery_result = discover_available_data(db)
        logger.info(f"Discovery: {discovery_result}")

        if discover_only:
            logger.info("Flag --discover-only ativada. Parando aqui.")
            return

        if not year_month:
            logger.info(
                "Nenhum --year-month especificado. Execute novamente com um mês para sincronizar."
            )
            return

        # Step 2: Sync
        logger.info(f"\n📌 Step 2/5 — Sync ({year_month})")
        sync_result = sync_month(db, year_month, first_only=first_only)
        logger.info(f"Sync: {sync_result}")

        # Step 3: Transform
        logger.info(f"\n📌 Step 3/5 — Transform ({year_month})")
        transform_data(year_month, first_only=first_only)
        logger.info("Transform concluído.")

        # Step 4: Load DB
        logger.info(f"\n📌 Step 4/5 — Load PostgreSQL ({year_month})")
        rows = load_to_postgres(year_month=year_month, db=db)
        logger.info(f"Load DB: {rows:,} registros inseridos")

        # Step 5: Load S3
        logger.info(f"\n📌 Step 5/5 — Load S3 ({year_month})")
        s3_result = upload_parquets_to_s3(year_month)
        logger.info(f"Load S3: {s3_result.get('uploaded', 0)} arquivos enviados")

        logger.info("\n" + "=" * 60)
        logger.info("✅ PIPELINE CONCLUÍDO COM SUCESSO")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ PIPELINE FALHOU: {e}")
        raise

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pipeline de ingestão de dados CNPJ da Receita Federal.",
        epilog="Exemplo: python -m src.ingest --year-month 2023-05",
    )
    parser.add_argument(
        "--year-month",
        help="Período a sincronizar no formato YYYY-MM (ex: 2023-05)",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Executa apenas discovery (sem download/transformação/carga)",
    )
    parser.add_argument(
        "--first-only",
        action="store_true",
        help="Baixa/processa apenas o primeiro arquivo de cada tipo",
    )
    args = parser.parse_args()

    run_pipeline(
        year_month=args.year_month,
        discover_only=args.discover_only,
        first_only=args.first_only,
    )
