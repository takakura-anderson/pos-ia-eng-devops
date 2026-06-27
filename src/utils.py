"""
Funções utilitárias compartilhadas entre jobs e routers.

Centraliza helpers que eram duplicados em múltiplos módulos:
- format_bytes: formatação de tamanho legível
- get_s3_client: cliente boto3 para o Garage S3
"""

import boto3

from src.config import S3_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY


def format_bytes(size: int) -> str:
    """Formata tamanho em bytes para formato legível (KB, MB, GB)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def get_s3_client():
    """Cria cliente boto3 S3 configurado para o Garage local."""
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )
