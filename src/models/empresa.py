"""
Model SQLAlchemy para a tabela cnpj_empresas.

Representa os dados de empresas da Receita Federal após transformação.
Layout baseado no arquivo Empresas da Receita Federal:
https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf
"""

from sqlalchemy import Column, Integer, String, Numeric

from src.models.database import Base


class Empresa(Base):
    """Dados cadastrais de empresas (tabela Empresas da Receita Federal)."""

    __tablename__ = "cnpj_empresas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cnpj_basico = Column(String(8), nullable=False, index=True, comment="CNPJ base (8 dígitos)")
    razao_social = Column(String(255), nullable=True, comment="Razão social da empresa")
    natureza_juridica = Column(String(4), nullable=True, comment="Código da natureza jurídica")
    qualificacao_responsavel = Column(
        String(2), nullable=True, comment="Qualificação do responsável"
    )
    capital_social = Column(Numeric(15, 2), nullable=True, comment="Capital social em R$")
    porte_empresa = Column(
        String(2), nullable=True, comment="Porte: 00=Não informado, 01=ME, 03=EPP, 05=Demais"
    )
    ente_federativo_responsavel = Column(
        String(255), nullable=True, comment="Ente federativo responsável"
    )

    def __repr__(self):
        return f"<Empresa(cnpj_basico='{self.cnpj_basico}', razao_social='{self.razao_social}')>"
