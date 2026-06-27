"""
Configuração do banco de dados com SQLAlchemy.

Fornece engine, session factory e Base declarativa para uso em
models, routers e jobs batch.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from src.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """
    Dependency injection para FastAPI.
    Gera uma sessão de banco por request e fecha ao final.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Cria todas as tabelas no banco de dados.
    Deve ser chamado na inicialização da API ou antes de rodar jobs.
    """
    Base.metadata.create_all(bind=engine)
