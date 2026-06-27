"""
Models SQLAlchemy para o schema completo do CNPJ da Receita Federal.

Define todas as tabelas auxiliares (Estabelecimentos, Sócios, Simples,
Países, Municípios, Qualificações, Naturezas Jurídicas, CNAEs).

A tabela principal de Empresas está em empresa.py (single source of truth).
"""

from sqlalchemy import Column, String, Integer, Date
from src.models.database import Base


class Estabelecimento(Base):
    __tablename__ = "cnpj_estabelecimentos"

    # Composite PK: basico + ordem + dv
    cnpj_basico = Column(String(8), primary_key=True)
    cnpj_ordem = Column(String(4), primary_key=True)
    cnpj_dv = Column(String(2), primary_key=True)

    identificador_matriz_filial = Column(Integer)
    nome_fantasia = Column(String(255))
    situacao_cadastral = Column(Integer)
    data_situacao_cadastral = Column(Date)
    motivo_situacao_cadastral = Column(Integer)
    nome_cidade_exterior = Column(String(255))
    pais = Column(Integer)
    data_inicio_atividade = Column(Date)
    cnae_fiscal_principal = Column(String(7))
    cnae_fiscal_secundaria = Column(String(1000))
    tipo_logradouro = Column(String(50))
    logradouro = Column(String(255))
    numero = Column(String(50))
    complemento = Column(String(255))
    bairro = Column(String(255))
    cep = Column(String(8))
    uf = Column(String(2))
    municipio = Column(Integer)
    ddd_1 = Column(String(4))
    telefone_1 = Column(String(8))
    ddd_2 = Column(String(4))
    telefone_2 = Column(String(8))
    ddd_fax = Column(String(4))
    fax = Column(String(8))
    correio_eletronico = Column(String(255))
    situacao_especial = Column(String(255))
    data_situacao_especial = Column(Date)


class Socio(Base):
    __tablename__ = "cnpj_socios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cnpj_basico = Column(String(8), index=True)
    identificador_socio = Column(Integer)
    nome_socio_razao_social = Column(String(255))
    cnpj_cpf_socio = Column(String(14))
    qualificacao_socio = Column(Integer)
    data_entrada_sociedade = Column(Date)
    pais = Column(Integer)
    representante_legal = Column(String(11))
    nome_representante = Column(String(255))
    qualificacao_representante_legal = Column(Integer)
    faixa_etaria = Column(Integer)


class Simples(Base):
    __tablename__ = "cnpj_simples"

    cnpj_basico = Column(String(8), primary_key=True)
    opcao_pelo_simples = Column(String(1))
    data_opcao_simples = Column(Date)
    data_exclusao_simples = Column(Date)
    opcao_mei = Column(String(1))
    data_opcao_mei = Column(Date)
    data_exclusao_mei = Column(Date)


class Pais(Base):
    __tablename__ = "cnpj_paises"

    codigo = Column(Integer, primary_key=True)
    descricao = Column(String(255))


class Municipio(Base):
    __tablename__ = "cnpj_municipios"

    codigo = Column(Integer, primary_key=True)
    descricao = Column(String(255))


class Qualificacao(Base):
    __tablename__ = "cnpj_qualificacoes"

    codigo = Column(Integer, primary_key=True)
    descricao = Column(String(255))


class NaturezaJuridica(Base):
    __tablename__ = "cnpj_naturezas"

    codigo = Column(Integer, primary_key=True)
    descricao = Column(String(255))


class Cnae(Base):
    __tablename__ = "cnpj_cnaes"

    codigo = Column(String(7), primary_key=True)
    descricao = Column(String(255))


class Motivo(Base):
    __tablename__ = "cnpj_motivos"

    codigo = Column(Integer, primary_key=True)
    descricao = Column(String(255))
