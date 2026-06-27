"""
Configurações centralizadas do projeto.

Todas as variáveis de ambiente são lidas aqui e expostas como constantes
para uso tanto pela API (live) quanto pelos jobs batch.

Referência: 12-Factor App — https://12factor.net/config
"""

import os


# === Banco de Dados (PostgreSQL) ===
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/cnpj")

# === Object Storage (Garage S3) ===
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "http://localhost:3900")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "cnpj-data")

# === Receita Federal ===
RECEITA_BASE_URL = os.getenv(
    "RECEITA_BASE_URL", "https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9"
)

# === Diretórios Locais ===
DATA_RAW_DIR = os.getenv("DATA_RAW_DIR", "data/raw")
DATA_PROCESSED_DIR = os.getenv("DATA_PROCESSED_DIR", "data/processed")

# === Aplicação ===
ENV = os.getenv("ENV", "development")
