import os
import logging
import pandas as pd
from sqlalchemy import create_engine
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from sklearn.preprocessing import LabelEncoder
import mlflow
import mlflow.sklearn

from src.config import DATABASE_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# MLflow tracking URL - no compose tá mapeado pra localhost:5001, mas internamente no container da api podemos usar http://mlflow:5001 (se estiver na rede) 
# Vamos ler do .env ou usar o host do compose. No compose tá services.mlflow com porta 5001?
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")

def load_data():
    """Carrega dados das empresas e opções pelo simples do PostgreSQL."""
    logger.info("Conectando ao banco de dados e extraindo amostra para treino...")
    engine = create_engine(DATABASE_URL)
    
    query = """
        SELECT 
            e.natureza_juridica,
            e.capital_social,
            e.porte_empresa,
            s.opcao_pelo_simples
        FROM cnpj_empresas e
        JOIN cnpj_simples s ON e.cnpj_basico = s.cnpj_basico
        WHERE s.opcao_pelo_simples IN ('S', 'N')
        LIMIT 50000;
    """
    df = pd.read_sql(query, engine)
    logger.info(f"Dados carregados: {df.shape[0]} linhas.")
    return df

def preprocess_data(df):
    """Realiza pré-processamento simples para o modelo."""
    df = df.dropna()
    
    # Label encoding
    le_nat = LabelEncoder()
    df['natureza_juridica'] = le_nat.fit_transform(df['natureza_juridica'])
    
    le_porte = LabelEncoder()
    df['porte_empresa'] = le_porte.fit_transform(df['porte_empresa'])
    
    # Target: 1 para 'S' (Simples), 0 para 'N'
    df['target'] = df['opcao_pelo_simples'].apply(lambda x: 1 if x == 'S' else 0)
    
    X = df[['natureza_juridica', 'capital_social', 'porte_empresa']]
    y = df['target']
    
    return X, y

def run_training():
    logger.info("Iniciando pipeline de treinamento...")
    
    # Configurar MLflow
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("CNPJ_Simples_Classification")
    
    df = load_data()
    if df.empty:
        logger.error("Nenhum dado retornado do banco de dados!")
        return
        
    X, y = preprocess_data(df)
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Hiperparâmetros
    n_estimators = 100
    max_depth = 10
    
    with mlflow.start_run() as run:
        logger.info("Treinando modelo RandomForest...")
        model = RandomForestClassifier(n_estimators=n_estimators, max_depth=max_depth, random_state=42)
        model.fit(X_train, y_train)
        
        y_pred = model.predict(X_test)
        
        acc = accuracy_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred, zero_division=0)
        rec = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        
        logger.info(f"Métricas do modelo: Acurácia={acc:.4f}, F1={f1:.4f}")
        
        # Log no MLflow
        mlflow.log_param("n_estimators", n_estimators)
        mlflow.log_param("max_depth", max_depth)
        mlflow.log_metric("accuracy", acc)
        mlflow.log_metric("precision", prec)
        mlflow.log_metric("recall", rec)
        mlflow.log_metric("f1_score", f1)
        
        # Logar o modelo
        logger.info("Salvando modelo no MLflow...")
        model_info = mlflow.sklearn.log_model(
            sk_model=model,
            artifact_path="random_forest_model"
        )
        
        logger.info("Registrando modelo no MLflow Registry...")
        mlflow.register_model(
            model_uri=model_info.model_uri,
            name="SimplesClassifier"
        )
        
        logger.info(f"Treinamento finalizado com sucesso! Run ID: {run.info.run_id}")
        logger.info(f"URI do Modelo: {model_info.model_uri}")

if __name__ == "__main__":
    run_training()
