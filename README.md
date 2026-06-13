# pos-ia-eng-devops
Projeto de IA / Engenharia de Dados / DevOps

## Ideia Base
- API em Python (FastAPI)
- Podman / Podman Composer
- Ler dados públicos da Receita Federal CNPJ
- Engenharia de Dados e Machine Learning com Isso
- #TODO: Python Buffer
- #TODO: Multistage Build otimizado para Podman (sem privilégios de root)
- #TODO: VirtualEnv Rootless
- #TODO: Diferença de (SLIM) vs (ALPINE) vs (STABLE)
- #TODO: Implementar Requests para Leitura de Dados Públicos
- #TODO: Pesquisarem Requirements.txt vs PyProject.toml vs Poetry
- #TODO: Health Check Endpoint
- #TODO: Configuração ContainerDev // Python Interpreter no VSCode
- #TODO: Linter - Black - Ruff - Flake8
- #TODO: Tradeoff de Gerenciamento de Camadas de uma Imagem (Velocidade // Tamanho // Segurança)
- #TODO: OpenAPI Spec
- #TODO: Garage S3
- #TODO: Compose Spec para Orquestração de Containers
- #TODO: Registro Imagens

## Pipelines

### CD (Continuous Delivery)

- #TODO: Criar pipelines para GitHub Actions.

### CI (Continuous Integration)

- #TODO: Criar pipelines para GitHub Actions.

## Estrutura do Projeto

- `ContainerFile`: Arquivo de definição de container otimizado para Podman (multi-stage build e sem privilégios de root).
- `podman-compose.yml`: Configuração para subir o ambiente usando Podman Composer.
- `requirements.txt`: Dependências Python (FastAPI e Uvicorn).
- `app/main.py`: Código-fonte inicial da API FastAPI com health check integrado.
- #TODO

## Como Executar o Projeto

### Pré-requisitos
- [Podman](https://podman.io/) instalado.
- [Podman Composer](https://github.com/containers/podman-compose) (opcional, para orquestração de containers).

### Opção 1: Executando diretamente com Podman

1. **Construir a imagem**:
   ```bash
   podman build -f ContainerFile -t fastapi-cnpj .
   ```

2. **Executar o container**:
   ```bash
   podman run -d -p 8000:8000 --name fastapi_api fastapi-cnpj
   ```

### Opção 2: Executando com Podman Composer

1. **Subir o serviço**:
   ```bash
   podman-compose up -d --build
   ```

### Acessando a API
A API estará disponível em `http://localhost:8000`.
- **Root Endpoint**: [http://localhost:8000/](http://localhost:8000/)
- **Documentação Interativa Swagger**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Endpoint de Health Check**: [http://localhost:8000/health](http://localhost:8000/health)
