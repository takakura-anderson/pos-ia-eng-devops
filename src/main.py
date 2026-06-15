import time
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Receita Federal CNPJ API",
    description="API para processamento e engenharia de dados públicos do CNPJ da Receita Federal.",
    version="1.0.0"
)

# Record application startup time for uptime calculation
START_TIME = time.time()

@app.get("/", tags=["General"])
async def root():
    """
    Root endpoint returning basic API info.
    """
    return {
        "message": "Bem-vindo à API de dados do CNPJ da Receita Federal!",
        "status": "Running",
        "documentation": "/docs"
    }

@app.get("/health", tags=["Monitoring"])
async def health_check():
    """
    Health check endpoint for container orchestrators and Podman healthcheck.
    """
    uptime = time.time() - START_TIME
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "uptime_seconds": round(uptime, 2),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }
    )
