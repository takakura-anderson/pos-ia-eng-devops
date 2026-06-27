"""
Router de consulta de empresas CNPJ.

Endpoints para listar, buscar e filtrar empresas carregadas no PostgreSQL.
Documentação automática via OpenAPI (FastAPI).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.models.database import get_db
from src.models.empresa import Empresa

router = APIRouter(prefix="/empresas", tags=["Empresas"])


@router.get(
    "/",
    summary="Listar empresas",
    description="Retorna uma lista paginada de empresas cadastradas no banco de dados.",
    response_description="Lista de empresas com paginação.",
)
async def listar_empresas(
    limit: int = Query(default=20, ge=1, le=100, description="Quantidade de registros por página"),
    offset: int = Query(default=0, ge=0, description="Deslocamento para paginação"),
    db: Session = Depends(get_db),
):
    """
    Lista empresas com paginação.

    - **limit**: Quantidade máxima de registros (1-100, padrão: 20)
    - **offset**: Ponto de início da página (padrão: 0)
    """
    total = db.query(Empresa).count()
    empresas = db.query(Empresa).offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "data": [
            {
                "cnpj_basico": e.cnpj_basico,
                "razao_social": e.razao_social,
                "natureza_juridica": e.natureza_juridica,
                "capital_social": float(e.capital_social) if e.capital_social else None,
                "porte_empresa": e.porte_empresa,
            }
            for e in empresas
        ],
    }


@router.get(
    "/search",
    summary="Buscar empresas por razão social",
    description="Realiza busca textual (ILIKE) na razão social das empresas.",
    response_description="Lista de empresas que correspondem à busca.",
)
async def buscar_empresas(
    razao_social: str = Query(
        ..., min_length=3, description="Termo de busca na razão social (mínimo 3 caracteres)"
    ),
    limit: int = Query(default=20, ge=1, le=100, description="Quantidade de registros"),
    db: Session = Depends(get_db),
):
    """
    Busca empresas pelo nome (razão social).

    - **razao_social**: Termo de busca (case-insensitive, mínimo 3 caracteres)
    - **limit**: Quantidade máxima de resultados (1-100, padrão: 20)
    """
    empresas = (
        db.query(Empresa).filter(Empresa.razao_social.ilike(f"%{razao_social}%")).limit(limit).all()
    )

    return {
        "query": razao_social,
        "count": len(empresas),
        "data": [
            {
                "cnpj_basico": e.cnpj_basico,
                "razao_social": e.razao_social,
                "natureza_juridica": e.natureza_juridica,
                "capital_social": float(e.capital_social) if e.capital_social else None,
                "porte_empresa": e.porte_empresa,
            }
            for e in empresas
        ],
    }


@router.get(
    "/{cnpj_basico}",
    summary="Buscar empresa por CNPJ básico",
    description="Retorna os dados cadastrais de uma empresa pelo CNPJ básico (8 dígitos).",
    response_description="Dados completos da empresa.",
)
async def buscar_por_cnpj(
    cnpj_basico: str,
    db: Session = Depends(get_db),
):
    """
    Busca uma empresa pelo CNPJ básico (8 dígitos).

    - **cnpj_basico**: Os 8 primeiros dígitos do CNPJ
    """
    empresa = db.query(Empresa).filter(Empresa.cnpj_basico == cnpj_basico).first()

    if not empresa:
        raise HTTPException(
            status_code=404, detail=f"Empresa com CNPJ básico '{cnpj_basico}' não encontrada."
        )

    return {
        "cnpj_basico": empresa.cnpj_basico,
        "razao_social": empresa.razao_social,
        "natureza_juridica": empresa.natureza_juridica,
        "qualificacao_responsavel": empresa.qualificacao_responsavel,
        "capital_social": float(empresa.capital_social) if empresa.capital_social else None,
        "porte_empresa": empresa.porte_empresa,
        "ente_federativo_responsavel": empresa.ente_federativo_responsavel,
    }
