"""
Script de exploração e validação dos dados raw da Receita Federal.

NÃO modifica nenhum arquivo raw.
Lê apenas uma amostra (nrows=500) de cada zip para:
  1. Verificar se o layout (colunas) bate com o esperado
  2. Detectar surpresas: colunas extras, encoding errado, separador diferente
  3. Estatísticas básicas: nulls, valores únicos, ranges
  4. Identificar arquivos sem mapeamento (ex: Motivos.zip)
  5. Estimar RAM necessária para transform completo
  6. Verificar espaço em disco disponível para processados

Uso:
    python -m scripts.explore_raw --year-month 2026-04
    python -m scripts.explore_raw --year-month 2026-04 --file Empresas0.zip
    python -m scripts.explore_raw --year-month 2026-04 --nrows 1000
"""

import argparse
import io
import logging
import os
import re
import sys
import zipfile

import pandas as pd

# Adiciona raiz ao path para importar src.*
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import DATA_RAW_DIR
from src.jobs.transform import LAYOUTS, _get_file_type
from src.utils import format_bytes as fmt_bytes

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Helpers de formatação
# ─────────────────────────────────────────────

# fmt_bytes importada de src.utils


def fmt_pct(v, total) -> str:
    if total == 0:
        return "N/A"
    return f"{100 * v / total:.1f}%"


SEPARATOR = "─" * 70


# ─────────────────────────────────────────────
# Exploração de um único arquivo zip
# ─────────────────────────────────────────────


def explore_zip(zip_path: str, nrows: int = 500) -> dict:
    """
    Lê amostra do zip e retorna relatório de qualidade.
    NÃO extrai nem modifica nada.
    """
    file_name = os.path.basename(zip_path)
    file_type = _get_file_type(file_name)
    expected_columns = LAYOUTS.get(file_type)
    zip_size = os.path.getsize(zip_path)

    report = {
        "file_name": file_name,
        "file_type": file_type,
        "zip_size_bytes": zip_size,
        "mapped": file_type in LAYOUTS,
        "issues": [],
        "warnings": [],
        "sample_rows": 0,
        "columns_found": [],
        "columns_expected": expected_columns or [],
    }

    if not report["mapped"]:
        report["warnings"].append(
            f"Tipo '{file_type}' NÃO está no LAYOUTS — será IGNORADO no transform!"
        )
        return report

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            internal = z.namelist()
            if not internal:
                report["issues"].append("ZIP VAZIO — nenhum arquivo interno encontrado!")
                return report

            csv_name = internal[0]
            report["internal_file"] = csv_name

            # Verificar se tem mais de 1 arquivo interno (inesperado)
            if len(internal) > 1:
                report["warnings"].append(
                    f"ZIP contém {len(internal)} arquivos internos (esperado: 1): {internal}"
                )

            # Leitura de amostra — sem extrair para disco
            with z.open(csv_name) as f:
                try:
                    df = pd.read_csv(
                        f,
                        sep=";",
                        encoding="latin-1",
                        header=None,
                        names=expected_columns,
                        dtype=str,
                        na_values=["", "NA"],
                        nrows=nrows,
                    )
                except Exception as e:
                    report["issues"].append(f"Erro ao ler CSV: {e}")
                    return report

        report["sample_rows"] = len(df)
        report["columns_found"] = list(df.columns)

        # ── Análise coluna a coluna ──
        col_stats = []
        for col in df.columns:
            series = df[col]
            null_count = series.isna().sum()
            non_null = series.dropna()

            stat = {
                "col": col,
                "null_count": int(null_count),
                "null_pct": fmt_pct(null_count, len(df)),
                "unique_count": int(non_null.nunique()),
                "sample_values": non_null.head(3).tolist(),
            }

            # Tentar inferir tipo numérico
            if col in ("capital_social",):
                try:
                    numeric = non_null.str.replace(",", ".").astype(float)
                    stat["min"] = float(numeric.min())
                    stat["max"] = float(numeric.max())
                    stat["zeros"] = int((numeric == 0).sum())
                    stat["negatives"] = int((numeric < 0).sum())
                    if stat["negatives"] > 0:
                        report["issues"].append(
                            f"{col}: {stat['negatives']} valores NEGATIVOS inesperados"
                        )
                except Exception:
                    pass

            col_stats.append(stat)

        report["col_stats"] = col_stats

        # ── Checks de qualidade ──
        if "cnpj_basico" in df.columns:
            cnpj_nulls = df["cnpj_basico"].isna().sum()
            if cnpj_nulls > 0:
                report["issues"].append(f"cnpj_basico: {cnpj_nulls} NULLs inesperados na amostra")

            cnpj_lengths = df["cnpj_basico"].dropna().str.len().value_counts().to_dict()
            expected_lens = {8}
            found_lens = set(cnpj_lengths.keys())
            if not found_lens.issubset(expected_lens):
                report["warnings"].append(
                    f"cnpj_basico: comprimentos inesperados encontrados: {found_lens}. "
                    f"Distribuição: {cnpj_lengths}"
                )

        # Razão social encoding check
        if "razao_social" in df.columns:
            # Checar se há caracteres não-Latin visíveis (encoding problem)
            sample_rs = df["razao_social"].dropna().head(10)
            weird = [v for v in sample_rs if any(ord(c) > 0x00FF for c in str(v))]
            if weird:
                report["issues"].append(
                    f"razao_social: possível problema de encoding em {len(weird)} amostras: {weird[:3]}"
                )

        # Estimativa de RAM: tamanho do zip * fator de expansão típico (~6-8x para CSV)
        expansion_factor = 7
        report["estimated_ram_mb"] = round((zip_size * expansion_factor) / (1024**2), 1)

    except zipfile.BadZipFile:
        report["issues"].append("ARQUIVO ZIP CORROMPIDO!")
    except Exception as e:
        report["issues"].append(f"Erro inesperado: {e}")

    return report


# ─────────────────────────────────────────────
# Relatório consolidado de um mês inteiro
# ─────────────────────────────────────────────


def explore_month(year_month: str, nrows: int = 500, target_file: str = None) -> None:
    input_dir = os.path.join(DATA_RAW_DIR, year_month)

    if not os.path.exists(input_dir):
        logger.error(f"Diretório não encontrado: {input_dir}")
        logger.error(f"DATA_RAW_DIR={DATA_RAW_DIR}")
        sys.exit(1)

    all_zips = sorted([f for f in os.listdir(input_dir) if f.endswith(".zip")])

    if target_file:
        all_zips = [f for f in all_zips if f == target_file]
        if not all_zips:
            logger.error(f"Arquivo '{target_file}' não encontrado em {input_dir}")
            sys.exit(1)

    # Espaço disponível
    stat = os.statvfs(input_dir)
    free_bytes = stat.f_bavail * stat.f_frsize
    total_raw = sum(os.path.getsize(os.path.join(input_dir, f)) for f in all_zips)

    print(f"\n{SEPARATOR}")
    print(f"  EXPLORAÇÃO DE DADOS — {year_month}")
    print(f"  Diretório: {input_dir}")
    print(f"  Arquivos encontrados: {len(all_zips)}")
    print(f"  Total raw: {fmt_bytes(total_raw)}")
    print(f"  Espaço livre em disco: {fmt_bytes(free_bytes)}")
    print(f"  Amostra por arquivo: {nrows} linhas")
    print(SEPARATOR)

    all_reports = []
    unmapped = []
    total_issues = 0
    total_warnings = 0
    total_estimated_ram = 0

    for fname in all_zips:
        zip_path = os.path.join(input_dir, fname)
        print(f"\n📦 {fname}  ({fmt_bytes(os.path.getsize(zip_path))})")

        r = explore_zip(zip_path, nrows=nrows)
        all_reports.append(r)

        if not r["mapped"]:
            unmapped.append(fname)
            for w in r["warnings"]:
                print(f"   ⚠️  {w}")
            continue

        print(f"   Tipo detectado : {r['file_type']}")
        print(f"   Arquivo interno: {r.get('internal_file', 'N/A')}")
        print(
            f"   Colunas esperadas ({len(r['columns_expected'])}): {', '.join(r['columns_expected'])}"
        )
        print(f"   Linhas na amostra: {r['sample_rows']}")
        print(f"   RAM estimada p/ transform completo: {r.get('estimated_ram_mb', '?')} MB")

        total_estimated_ram += r.get("estimated_ram_mb", 0)

        # Issues
        for issue in r.get("issues", []):
            print(f"   ❌ ISSUE: {issue}")
            total_issues += 1

        for w in r.get("warnings", []):
            print(f"   ⚠️  WARNING: {w}")
            total_warnings += 1

        # Stats de colunas
        print(f"   {'Coluna':<35} {'Nulls':>8}  {'Únicos':>8}  {'Amostras'}")
        print(f"   {'─' * 35} {'─' * 8}  {'─' * 8}  {'─' * 20}")
        for cs in r.get("col_stats", []):
            sample_str = str(cs["sample_values"])[:40]
            print(f"   {cs['col']:<35} {cs['null_pct']:>8}  {cs['unique_count']:>8}  {sample_str}")
            # Flag colunas 100% null
            if cs["null_count"] == r["sample_rows"] and r["sample_rows"] > 0:
                print(f"   ⚠️  WARNING: '{cs['col']}' está 100% NULL na amostra!")
                total_warnings += 1

    # ── Sumário Final ──
    print(f"\n{SEPARATOR}")
    print(f"  SUMÁRIO")
    print(SEPARATOR)
    print(f"  Total de arquivos analisados  : {len(all_reports)}")
    print(f"  Arquivos mapeados (transform) : {len(all_reports) - len(unmapped)}")
    print(f"  Arquivos SEM mapeamento       : {len(unmapped)}")
    if unmapped:
        print(f"    → Serão IGNORADOS: {', '.join(unmapped)}")
    print(f"  Issues críticos               : {total_issues}")
    print(f"  Warnings                      : {total_warnings}")
    print(
        f"  RAM estimada total (todos)    : {total_estimated_ram:.0f} MB ({total_estimated_ram / 1024:.1f} GB)"
    )
    print(f"  Espaço livre disponível       : {fmt_bytes(free_bytes)}")

    # Estimar espaço necessário para parquets (Parquet ~20-30% do CSV descomprimido)
    estimated_parquet_gb = (total_raw * 7 * 0.25) / (1024**3)
    print(f"  Espaço estimado p/ Parquets   : {estimated_parquet_gb:.1f} GB")
    print()

    if total_issues > 0:
        print("  ❌ ATENÇÃO: Issues críticos encontrados. Revise antes de rodar transform!")
    elif total_warnings > 0:
        print("  ⚠️  Warnings encontrados. Verifique antes de prosseguir.")
    else:
        print("  ✅ Dados parecem consistentes com o layout esperado.")

    print(SEPARATOR)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Explora dados raw da RF sem modificar nada.",
        epilog="Exemplo: python -m scripts.explore_raw --year-month 2026-04",
    )
    parser.add_argument("--year-month", required=True, help="Período YYYY-MM")
    parser.add_argument("--file", help="Analisar apenas um arquivo específico (ex: Empresas0.zip)")
    parser.add_argument(
        "--nrows", type=int, default=500, help="Linhas de amostra por arquivo (padrão: 500)"
    )
    args = parser.parse_args()

    explore_month(args.year_month, nrows=args.nrows, target_file=args.file)
