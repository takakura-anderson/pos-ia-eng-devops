import logging

# Configuração básica de logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def download_cnpj_data():
    """
    Realiza o download dos arquivos CNPJ (EmpresasN.zip, EstabelecimentosN.zip) da Receita Federal.
    """
    logger.info("Iniciando download dos dados da Receita Federal...")
    # TODO: Implementar lógica de download (ex: requests ou urllib)
    # Recomendação: Baixar para um diretório local temporário ou 'data/raw/'
    pass

def transform_data():
    """
    Transforma os dados brutos utilizando a biblioteca escolhida (ex: pandas).
    Requisitos:
      - Tratar encoding latin-1
      - Separador ';'
      - Arquivos vêm sem header (necessário mapear as colunas)
      - Normalizar datas e valores (ex: capital social)
    """
    logger.info("Iniciando transformação dos dados...")
    # TODO: Implementar leitura e transformação dos dados (pandas/polars)
    pass

def load_to_database():
    """
    Carrega os dados transformados para o banco de dados PostgreSQL.
    """
    logger.info("Iniciando carga de dados no PostgreSQL...")
    # TODO: Implementar conexão (psycopg2/sqlalchemy) e inserção na tabela tratada
    pass

def load_to_storage():
    """
    (Opcional/Avançado) Salva o resultado em formato Parquet no Object Storage (Garage/S3).
    """
    logger.info("Iniciando carga de dados no Object Storage...")
    # TODO: Implementar upload usando boto3 ou minio SDK
    pass

def run_pipeline():
    """
    Função principal que orquestra as etapas do pipeline.
    """
    logger.info("Pipeline Batch Iniciado")
    
    download_cnpj_data()
    transform_data()
    load_to_database()
    # load_to_storage()
    
    logger.info("Pipeline Batch Finalizado com Sucesso")

if __name__ == "__main__":
    run_pipeline()
