"""
Inicialização do pacote models.
Importando todos os models aqui garante que o SQLAlchemy Base os conheça
antes de rodar o Base.metadata.create_all().
"""

from src.models.sync_control import SyncControl
from src.models.empresa import Empresa
from src.models.schema_cnpj import (
    Estabelecimento,
    Socio,
    Simples,
    Pais,
    Municipio,
    Qualificacao,
    NaturezaJuridica,
    Cnae,
    Motivo,
)

__all__ = [
    "SyncControl",
    "Empresa",
    "Estabelecimento",
    "Socio",
    "Simples",
    "Pais",
    "Municipio",
    "Qualificacao",
    "NaturezaJuridica",
    "Cnae",
    "Motivo",
]
