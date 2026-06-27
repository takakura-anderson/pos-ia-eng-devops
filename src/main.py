"""
API FastAPI — Receita Federal CNPJ.

Endpoints:
- / — Info geral da API
- /health — Healthcheck para orquestradores
- /empresas/* — Consulta de dados CNPJ (router)
- /admin/* — Dashboard e controle de sincronização (router)

Documentação automática: http://localhost:8000/docs
"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.models.database import init_db
from src.routers import empresas, admin, s3_status


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa o banco de dados na startup da API."""
    init_db()
    yield


app = FastAPI(
    title="Receita Federal CNPJ API",
    description=(
        "API para ingestão, processamento e consulta de dados públicos do CNPJ "
        "da Receita Federal do Brasil.\n\n"
        "**Funcionalidades:**\n"
        "- 📊 Consulta de empresas por CNPJ ou razão social\n"
        "- 🔄 Dashboard de sincronização para controle de dados\n"
        "- 📥 Discovery e download seletivo por período\n\n"
        "**Fonte de dados:** [Portal da Receita Federal]"
        "(https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9)"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Registrar routers
app.include_router(empresas.router)
app.include_router(admin.router)
app.include_router(s3_status.router)

# Timestamp de startup para cálculo de uptime
START_TIME = time.time()


@app.get("/", tags=["General"])
async def root():
    """
    Root endpoint com informações básicas da API.
    """
    return {
        "message": "Bem-vindo à API de dados do CNPJ da Receita Federal!",
        "status": "Running",
        "documentation": "/docs",
        "endpoints": {
            "empresas": "/empresas",
            "admin_dashboard": "/admin/sync",
            "health": "/health",
        },
    }


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """
    Health check endpoint para container orchestrators e Podman healthcheck.
    """
    uptime = time.time() - START_TIME
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "uptime_seconds": round(uptime, 2),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )
