"""
Model SQLAlchemy para a tabela sync_control.

Controla o estado de sincronização dos dados da Receita Federal.
Cada registro representa um arquivo disponível no portal, com seu
status atual no pipeline (pendente, baixado, transformado, carregado, erro).
"""

from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Enum, Float
from sqlalchemy.sql import func

from src.models.database import Base


class SyncControl(Base):
    """Controle de sincronização de arquivos da Receita Federal."""

    __tablename__ = "sync_control"

    id = Column(Integer, primary_key=True, autoincrement=True)
    year_month = Column(
        String(7), nullable=False, index=True, comment="Período no formato YYYY-MM (ex: 2023-05)"
    )
    file_name = Column(String(255), nullable=False, comment="Nome do arquivo (ex: Empresas0.zip)")
    file_size_bytes = Column(
        BigInteger, nullable=True, comment="Tamanho do arquivo em bytes (remoto)"
    )
    etag = Column(String(255), nullable=True, comment="Hash/ETag do arquivo no WebDAV")
    local_hash = Column(String(64), nullable=True, comment="SHA-256 do arquivo baixado localmente")
    local_size_bytes = Column(
        BigInteger, nullable=True, comment="Tamanho real do arquivo no disco local"
    )
    download_progress = Column(
        Float,
        nullable=True,
        default=0.0,
        comment="Progresso do download (0.0 a 100.0). NULL se não iniciado.",
    )
    discovered_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="Timestamp de quando o arquivo foi descoberto",
    )
    synced_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp de quando o arquivo foi baixado (NULL = pendente)",
    )
    status = Column(
        Enum(
            "pending",
            "downloading",
            "downloaded",
            "transforming",
            "transformed",
            "loaded",
            "error",
            name="sync_status",
        ),
        nullable=False,
        default="pending",
        comment="Estado atual do arquivo no pipeline",
    )
    error_message = Column(String(1000), nullable=True, comment="Mensagem de erro, se houver")

    def __repr__(self):
        return (
            f"<SyncControl(year_month='{self.year_month}', "
            f"file_name='{self.file_name}', status='{self.status}')>"
        )
