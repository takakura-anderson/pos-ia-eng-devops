"""
Job de transformação dos dados raw da Receita Federal.

Lê os arquivos .zip de data/raw/{year_month}/ e escreve .parquet em
data/processed/{year_month}/. Os arquivos raw NUNCA são deletados.

Estratégia de processamento:
- Arquivos pequenos (< LARGE_FILE_THRESHOLD_MB): leitura direta na RAM
- Arquivos grandes (>= LARGE_FILE_THRESHOLD_MB): leitura em chunks via
  PyArrow ParquetWriter — mantém uso de RAM constante independente do
  tamanho do arquivo

Suporte a todos os tipos de arquivo da RF:
    Empresas, Estabelecimentos, Socios, Simples,
    Paises, Municipios, Qualificacoes, Naturezas, Cnaes, Motivos
"""

import logging
import os
import zipfile
from itertools import groupby

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.config import DATA_RAW_DIR, DATA_PROCESSED_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Layout de colunas conforme documentação da Receita Federal
# ─────────────────────────────────────────────────────────────────

LAYOUTS = {
    "Empresas": [
        "cnpj_basico",
        "razao_social",
        "natureza_juridica",
        "qualificacao_responsavel",
        "capital_social",
        "porte_empresa",
        "ente_federativo_responsavel",
    ],
    "Estabelecimentos": [
        "cnpj_basico",
        "cnpj_ordem",
        "cnpj_dv",
        "identificador_matriz_filial",
        "nome_fantasia",
        "situacao_cadastral",
        "data_situacao_cadastral",
        "motivo_situacao_cadastral",
        "nome_cidade_exterior",
        "pais",
        "data_inicio_atividade",
        "cnae_fiscal_principal",
        "cnae_fiscal_secundaria",
        "tipo_logradouro",
        "logradouro",
        "numero",
        "complemento",
        "bairro",
        "cep",
        "uf",
        "municipio",
        "ddd_1",
        "telefone_1",
        "ddd_2",
        "telefone_2",
        "ddd_fax",
        "fax",
        "correio_eletronico",
        "situacao_especial",
        "data_situacao_especial",
    ],
    "Socios": [
        "cnpj_basico",
        "identificador_socio",
        "nome_socio_razao_social",
        "cnpj_cpf_socio",
        "qualificacao_socio",
        "data_entrada_sociedade",
        "pais",
        "representante_legal",
        "nome_representante",
        "qualificacao_representante_legal",
        "faixa_etaria",
    ],
    "Simples": [
        "cnpj_basico",
        "opcao_pelo_simples",
        "data_opcao_simples",
        "data_exclusao_simples",
        "opcao_mei",
        "data_opcao_mei",
        "data_exclusao_mei",
    ],
    "Paises": ["codigo", "descricao"],
    "Municipios": ["codigo", "descricao"],
    "Qualificacoes": ["codigo", "descricao"],
    "Naturezas": ["codigo", "descricao"],
    "Cnaes": ["codigo", "descricao"],
    "Motivos": ["codigo", "descricao"],  # Motivos de situação cadastral
}

# Threshold em MB: arquivos maiores que isso serão processados em chunks
LARGE_FILE_THRESHOLD_MB = 200

# Número de linhas por chunk (ajuste conforme RAM disponível)
CHUNK_SIZE = 50_000


# ─────────────────────────────────────────────────────────────────
# Normalização e regras de negócio
# ─────────────────────────────────────────────────────────────────


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalização genérica aplicada a DataFrames de Empresas.

    Regras:
    - cnpj_basico: zero-padded para 8 dígitos
    - razao_social: strip de espaços nas bordas
    - capital_social: vírgula → ponto → float64
    """
    df = df.copy()

    if "cnpj_basico" in df.columns:
        df["cnpj_basico"] = df["cnpj_basico"].astype(str).str.zfill(8)

    if "razao_social" in df.columns:
        df["razao_social"] = df["razao_social"].astype(str).str.strip()

    if "capital_social" in df.columns:
        # Converter de string com vírgula decimal para float64
        # Fazemos sempre a tentativa, independente do dtype atual
        try:
            df["capital_social"] = (
                df["capital_social"].astype(str).str.strip().str.replace(",", ".").astype(float)
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Não foi possível converter capital_social para float: {e}")

    return df


def _normalize_date_field(value) -> object:
    """
    Converte datas da RF para formato ISO (YYYY-MM-DD) ou None.
    A RF usa '00000000' para datas nulas e '20230101' para datas válidas.
    PostgreSQL rejeita '00000000' em campos de data via COPY.
    """
    if value is None:
        return None
    s = str(value).strip()
    if s in ("", "None", "nan", "0", "00000000", "00/00/0000"):
        return None
    if len(s) == 8 and s.isdigit():
        try:
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        except Exception:
            return None
    return s


def apply_business_rules(df: pd.DataFrame, file_type: str) -> pd.DataFrame:
    """Aplica regras de negócio e limpezas por tipo de arquivo."""

    if file_type == "Empresas":
        df = _normalize_dataframe(df)

    elif file_type == "Estabelecimentos":
        if "cnpj_basico" in df.columns:
            df["cnpj_basico"] = df["cnpj_basico"].astype(str).str.zfill(8)
        if "cnae_fiscal_secundaria" in df.columns:
            df["cnae_fiscal_secundaria"] = (
                df["cnae_fiscal_secundaria"].astype(str).str.replace(r"[^0-9,]", "", regex=True)
            )
        # Datas vêm como strings tipo "00000000" ou "20230101"
        # NULL as datas inválidas antes do COPY no PostgreSQL
        for date_col in (
            "data_situacao_cadastral",
            "data_inicio_atividade",
            "data_situacao_especial",
        ):
            if date_col in df.columns:
                df[date_col] = df[date_col].apply(_normalize_date_field)

    elif file_type == "Socios":
        if "cnpj_basico" in df.columns:
            df["cnpj_basico"] = df["cnpj_basico"].astype(str).str.zfill(8)
        for date_col in ("data_entrada_sociedade",):
            if date_col in df.columns:
                df[date_col] = df[date_col].apply(_normalize_date_field)

    elif file_type == "Simples":
        if "cnpj_basico" in df.columns:
            df["cnpj_basico"] = df["cnpj_basico"].astype(str).str.zfill(8)
        for date_col in (
            "data_opcao_simples",
            "data_exclusao_simples",
            "data_opcao_mei",
            "data_exclusao_mei",
        ):
            if date_col in df.columns:
                df[date_col] = df[date_col].apply(_normalize_date_field)

    return df


def _get_file_type(file_name: str) -> str:
    """Extrai o tipo de arquivo a partir do nome (ex: Empresas0.zip → Empresas)."""
    import re

    base_name = re.sub(r"\d*\.zip|\d*\.tar\.gz", "", file_name, flags=re.IGNORECASE)
    for k in LAYOUTS.keys():
        if base_name.lower().startswith(k.lower()):
            return k
    return base_name


def _file_size_mb(path: str) -> float:
    """Retorna o tamanho do arquivo em MB."""
    return os.path.getsize(path) / (1024 * 1024)


# ─────────────────────────────────────────────────────────────────
# Processamento de um único arquivo
# ─────────────────────────────────────────────────────────────────


def _process_small_file(
    zip_path: str,
    csv_name: str,
    columns: list,
    file_type: str,
    output_path: str,
) -> int:
    """
    Lê o CSV inteiro na memória (para arquivos pequenos).
    Seguro para arquivos com menos de LARGE_FILE_THRESHOLD_MB.
    """
    with zipfile.ZipFile(zip_path, "r") as z:
        with z.open(csv_name) as f:
            df = pd.read_csv(
                f,
                sep=";",
                encoding="latin-1",
                header=None,
                names=columns,
                dtype=str,
                na_values=["", "NA"],
            )

    df = apply_business_rules(df, file_type)
    df.to_parquet(output_path, index=False, compression="snappy")
    return len(df)


def _process_large_file(
    zip_path: str,
    csv_name: str,
    columns: list,
    file_type: str,
    output_path: str,
) -> int:
    """
    Lê o CSV em chunks usando PyArrow ParquetWriter para escrita incremental.

    Mantém uso de RAM constante independente do tamanho do arquivo.
    O arquivo raw NÃO é deletado nem modificado.
    """
    writer = None
    total_rows = 0
    chunk_count = 0

    with zipfile.ZipFile(zip_path, "r") as z:
        with z.open(csv_name) as f:
            reader = pd.read_csv(
                f,
                sep=";",
                encoding="latin-1",
                header=None,
                names=columns,
                dtype=str,
                na_values=["", "NA"],
                chunksize=CHUNK_SIZE,
            )

            for chunk_df in reader:
                chunk_df = apply_business_rules(chunk_df, file_type)

                # Converter para PyArrow Table
                table = pa.Table.from_pandas(chunk_df, preserve_index=False)

                # Inicializar writer com o schema do primeiro chunk
                if writer is None:
                    schema = table.schema
                    writer = pq.ParquetWriter(
                        output_path,
                        schema,
                        compression="snappy",
                    )
                else:
                    # Forçar schema consistente entre chunks
                    # (evita mismatch quando colunas de data ficam all-null)
                    table = table.cast(schema)

                writer.write_table(table)
                total_rows += len(chunk_df)
                chunk_count += 1

                if chunk_count % 10 == 0:
                    logger.info(f"   chunk {chunk_count}: {total_rows:,} linhas processadas...")

    if writer:
        writer.close()

    return total_rows


def process_file(db, zip_path: str, output_path: str, year_month: str) -> dict:
    """
    Processa um único arquivo zip → parquet.

    Decide automaticamente entre leitura direta ou chunked
    com base no tamanho do arquivo. Baixa do S3 se não existir localmente.

    Retorna dicionário com resultado do processamento.
    """
    file_name = os.path.basename(zip_path)
    file_type = _get_file_type(file_name)

    if file_type not in LAYOUTS:
        logger.warning(f"Tipo '{file_type}' não mapeado — {file_name} será ignorado.")
        return {"file_name": file_name, "skipped": True, "reason": "not_mapped"}

    if not os.path.exists(zip_path):
        from src.utils import _get_s3_client, S3_BUCKET_NAME

        s3_client = _get_s3_client()
        s3_key = f"raw/{year_month}/{file_name}"
        logger.info(f"Arquivo não encontrado localmente. Baixando do S3: {s3_key}")
        try:
            s3_client.download_file(S3_BUCKET_NAME, s3_key, zip_path)
        except Exception as e:
            logger.error(f"Erro ao baixar {s3_key} do S3: {e}")
            return {"file_name": file_name, "skipped": True, "reason": "s3_download_failed"}

    size_mb = _file_size_mb(zip_path)

    if os.path.exists(output_path):
        logger.info(f"Já processado: {output_path}. Pulando.")
        return {"file_name": file_name, "skipped": True, "reason": "already_exists"}

    columns = LAYOUTS[file_type]

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            internal_files = z.namelist()
            if not internal_files:
                logger.warning(f"ZIP vazio: {file_name}. Pulando.")
                return {"file_name": file_name, "skipped": True, "reason": "empty_zip"}
            csv_name = internal_files[0]

        use_chunks = size_mb >= LARGE_FILE_THRESHOLD_MB
        strategy = "chunked" if use_chunks else "direct"
        logger.info(
            f"  📄 {file_name} ({size_mb:.0f} MB) → {file_type} "
            f"[{strategy}, chunksize={CHUNK_SIZE if use_chunks else 'N/A'}]"
        )

        if use_chunks:
            total_rows = _process_large_file(zip_path, csv_name, columns, file_type, output_path)
        else:
            total_rows = _process_small_file(zip_path, csv_name, columns, file_type, output_path)

        output_size_mb = _file_size_mb(output_path)
        logger.info(
            f"  ✅ {file_name} → {total_rows:,} linhas | "
            f"Parquet: {output_size_mb:.1f} MB (vs {size_mb:.0f} MB zip)"
        )

        return {
            "file_name": file_name,
            "file_type": file_type,
            "skipped": False,
            "total_rows": total_rows,
            "zip_size_mb": round(size_mb, 1),
            "parquet_size_mb": round(output_size_mb, 1),
            "strategy": strategy,
        }

    except Exception as e:
        logger.error(f"  ❌ Erro ao processar {file_name}: {e}")
        # Remove parquet parcial se existir (para permitir reprocessamento)
        if os.path.exists(output_path):
            os.remove(output_path)
            logger.info(f"  🗑️  Parquet parcial removido: {output_path}")
        return {
            "file_name": file_name,
            "file_type": file_type,
            "skipped": False,
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────
# Processamento de um mês completo
# ─────────────────────────────────────────────────────────────────


def transform_data(db, year_month: str, first_only: bool = False) -> dict:
    """
    Processa todos os arquivos raw de um mês consultando o banco.

    Os parquets resultantes ficam em data/processed/{year_month}/.
    Se os ZIPs não estiverem localmente, serão baixados do S3 no momento do processamento.

    Parâmetros:
    - db: Sessão do banco
    - year_month: Período YYYY-MM (ex: 2026-04)
    - first_only: Se True, processa apenas o primeiro arquivo de cada tipo

    Retorna estatísticas do processamento.
    """
    from src.models.sync_control import SyncControl

    input_dir = os.path.join(DATA_RAW_DIR, year_month)
    output_dir = os.path.join(DATA_PROCESSED_DIR, year_month)
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    records = (
        db.query(SyncControl)
        .filter(
            SyncControl.year_month == year_month,
            SyncControl.status.in_(["downloaded", "transformed", "loaded"]),
        )
        .order_by(SyncControl.file_name)
        .all()
    )

    if not records:
        logger.warning(f"Nenhum arquivo no DB para {year_month}.")
        return {}

    files = [r.file_name for r in records]

    if first_only:
        filtered = []
        for _, group in groupby(files, key=_get_file_type):
            filtered.append(next(group))
        files = filtered
        logger.info(f"Modo first_only: {len(files)} arquivos (1 de cada tipo)")

    logger.info(f"{'=' * 60}")
    logger.info(f"TRANSFORM — {year_month} ({len(files)} arquivos)")
    logger.info(f"  Input : {input_dir}")
    logger.info(f"  Output: {output_dir}")
    logger.info(f"  Threshold chunks: {LARGE_FILE_THRESHOLD_MB} MB")
    logger.info(f"{'=' * 60}")

    results = []
    total_rows = 0
    errors = 0
    skipped = 0

    for idx, file_name in enumerate(files, 1):
        logger.info(f"\n[{idx}/{len(files)}] {file_name}")
        zip_path = os.path.join(input_dir, file_name)
        output_path = os.path.join(output_dir, file_name.replace(".zip", ".parquet"))

        result = process_file(db, zip_path, output_path, year_month)
        results.append(result)

        if result.get("skipped"):
            skipped += 1
        elif "error" in result:
            errors += 1
        else:
            total_rows += result.get("total_rows", 0)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"TRANSFORM {year_month} CONCLUÍDO")
    logger.info(f"  Processados : {len(files) - skipped - errors}")
    logger.info(f"  Pulados     : {skipped}")
    logger.info(f"  Erros       : {errors}")
    logger.info(f"  Total linhas: {total_rows:,}")
    logger.info(f"{'=' * 60}")

    return {
        "year_month": year_month,
        "processed": len(files) - skipped - errors,
        "skipped": skipped,
        "errors": errors,
        "total_rows": total_rows,
        "details": results,
    }


# ─────────────────────────────────────────────────────────────────
# CLI standalone
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Transforma dados raw (zip) em Parquet.",
        epilog="Exemplo: python -m src.jobs.transform --year-month 2026-04",
    )
    parser.add_argument("--year-month", required=True, help="Período YYYY-MM")
    parser.add_argument(
        "--first-only", action="store_true", help="Processa apenas 1 arquivo de cada tipo"
    )
    parser.add_argument("--file", help="Processa apenas um arquivo específico (ex: Empresas0.zip)")
    args = parser.parse_args()

    from src.models.database import SessionLocal, init_db

    init_db()
    db = SessionLocal()

    try:
        if args.file:
            input_dir = os.path.join(DATA_RAW_DIR, args.year_month)
            output_dir = os.path.join(DATA_PROCESSED_DIR, args.year_month)
            os.makedirs(input_dir, exist_ok=True)
            os.makedirs(output_dir, exist_ok=True)
            zip_path = os.path.join(input_dir, args.file)
            output_path = os.path.join(output_dir, args.file.replace(".zip", ".parquet"))
            result = process_file(db, zip_path, output_path, args.year_month)
            logger.info(f"Resultado: {result}")
        else:
            result = transform_data(db, args.year_month, first_only=args.first_only)
            logger.info(f"Total de linhas processadas: {result.get('total_rows', 0):,}")
    finally:
        db.close()
