import os
import logging
import mlflow
import pandas as pd
from sqlalchemy import text
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from src.models.database import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_data():
    """
    Busca os dados do PostgreSQL juntando Empresas, Simples e Estabelecimentos 
    para prever o porte da empresa.
    """
    db = SessionLocal()
    try:
        query = text("""
            SELECT 
                e.capital_social, 
                e.natureza_juridica,
                s.opcao_simples,
                est.cnae_fiscal_principal,
                e.porte_empresa
            FROM cnpj_empresas e
            LEFT JOIN cnpj_simples s ON e.cnpj_basico = s.cnpj_basico
            LEFT JOIN cnpj_estabelecimentos est ON e.cnpj_basico = est.cnpj_basico
            WHERE e.porte_empresa IS NOT NULL 
              AND e.porte_empresa != ''
              AND est.identificador_matriz_filial = '1'
            LIMIT 100000;
        """)
        df = pd.read_sql(query, db.bind)
        return df
    finally:
        db.close()

def preprocess_data(df):
    """Prepara as features para treinamento"""
    df = df.copy()
    
    # Target: porte_empresa (00=Não informado, 01=Micro, 03=EPP, 05=Demais)
    # Vamos considerar apenas 01, 03 e 05
    df = df[df["porte_empresa"].isin(["01", "03", "05"])]
    
    # Fill NAs
    df["opcao_simples"] = df["opcao_simples"].fillna("N")
    df["capital_social"] = pd.to_numeric(df["capital_social"], errors="coerce").fillna(0)
    
    # One-Hot Encoding simples (ideal seria Target Encoding para CNAE por causa da cardinalidade)
    features = pd.get_dummies(df[["capital_social", "natureza_juridica", "opcao_simples"]], drop_first=True)
    target = df["porte_empresa"]
    
    return features, target

def train_model():
    mlflow_url = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    mlflow.set_tracking_uri(mlflow_url)
    mlflow.set_experiment("classificacao-porte-empresa")
    
    logger.info("Buscando dados no banco de dados...")
    df = fetch_data()
    
    if len(df) == 0:
        logger.error("Nenhum dado retornado. Rode o pipeline de carga (load-db) primeiro.")
        return
        
    logger.info(f"Pré-processando {len(df)} linhas...")
    X, y = preprocess_data(df)
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    with mlflow.start_run():
        n_estimators = 100
        max_depth = 10
        
        mlflow.log_param("n_estimators", n_estimators)
        mlflow.log_param("max_depth", max_depth)
        mlflow.log_param("train_size", len(X_train))
        
        logger.info("Treinando modelo RandomForest...")
        clf = RandomForestClassifier(n_estimators=n_estimators, max_depth=max_depth, random_state=42)
        clf.fit(X_train, y_train)
        
        preds = clf.predict(X_test)
        acc = accuracy_score(y_test, preds)
        
        logger.info(f"Acurácia: {acc:.4f}")
        mlflow.log_metric("accuracy", acc)
        
        # Log model
        mlflow.sklearn.log_model(clf, "random_forest_model")
        
        logger.info("Modelo registrado com sucesso no MLFlow!")

if __name__ == "__main__":
    train_model()
