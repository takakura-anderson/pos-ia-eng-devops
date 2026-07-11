import os
import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import pandas as pd
import mlflow.pyfunc

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/predict",
    tags=["Model Serving"]
)

MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

# Global variable to store the loaded model
model = None

class PredictionRequest(BaseModel):
    natureza_juridica: int
    capital_social: float
    porte_empresa: int

class PredictionResponse(BaseModel):
    is_simples: bool
    message: str

def load_model():
    """Load model from MLflow registry on startup."""
    global model
    model_name = "SimplesClassifier"
    # Carrega a versão mais recente em Production ou Staging, ou a última
    # Aqui usaremos latest para simplificar o laboratório
    model_uri = f"models:/{model_name}/latest"
    try:
        logger.info(f"Loading MLflow model from {model_uri}")
        model = mlflow.pyfunc.load_model(model_uri)
        logger.info("Model loaded successfully.")
    except Exception as e:
        logger.error(f"Failed to load MLflow model: {e}")
        # A API pode subir mesmo se o modelo não estiver treinado ainda

@router.on_event("startup")
async def startup_event():
    load_model()

@router.post("/", response_model=PredictionResponse)
async def predict(request: PredictionRequest):
    """
    Realiza uma predição usando o modelo classificador de Optante pelo Simples.
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Modelo de Machine Learning não está disponível no momento.")
        
    try:
        # Create a dataframe for the model
        data = pd.DataFrame([{
            "natureza_juridica": request.natureza_juridica,
            "capital_social": request.capital_social,
            "porte_empresa": request.porte_empresa
        }])
        
        # Predict class
        prediction = model.predict(data)[0]
        is_simples = bool(prediction == 1)
        
        return PredictionResponse(
            is_simples=is_simples,
            message="Predição realizada com sucesso."
        )
    except Exception as e:
        logger.error(f"Erro durante predição: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao processar a predição.")
