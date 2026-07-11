.PHONY: help build up down test clean clean-volumes explore discover sync ingest logs lint format s3-status s3-list verify sync-file transform transform-file transform-status load-db load-db-file load-db-status load-s3
.DEFAULT_GOAL := help

# Detecta se podman está disponível, caso contrário usa docker (útil para CI)
DOCKER_CMD ?= $(shell command -v podman 2> /dev/null || echo docker)
COMPOSE_CMD ?= $(shell command -v podman-compose 2> /dev/null || echo "$(DOCKER_CMD) compose")

help: ## Mostra os comandos disponíveis
	@echo "Uso: make [comando]"
	@echo ""
	@echo "Comandos Disponíveis:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST) | sort
	@echo ""

build: ## Constrói a imagem do container
	@echo "🔨 Construindo a imagem com $(DOCKER_CMD)..."
	$(DOCKER_CMD) build -f ContainerFile -t fastapi-cnpj .

up: ## Sobe o ambiente completo (API + PostgreSQL + Garage)
	@echo "🚀 Subindo o ambiente..."
	$(COMPOSE_CMD) up -d --build

down: ## Derruba o ambiente local
	@echo "🛑 Derrubando o ambiente..."
	$(COMPOSE_CMD) down

test: ## Executa os testes automatizados (requer 'make up' antes)
	@echo "🧪 Executando testes (certifique-se que executou 'make up' antes)..."
	$(COMPOSE_CMD) exec api python -m pytest tests/ -v

lint: ## Executa análise estática de código e formatação com Ruff (modo check)
	@echo "🧹 Executando Ruff (Linter & Formatter Check)..."
	$(COMPOSE_CMD) exec -u root api ruff check .
	$(COMPOSE_CMD) exec -u root api ruff format --check .

format: ## Aplica as formatações recomendadas pelo Ruff
	@echo "✨ Formatando código com Ruff..."
	$(COMPOSE_CMD) exec -u root api ruff format .
	$(COMPOSE_CMD) exec -u root api ruff check --fix .

clean: ## Para containers e remove imagens órfãs (NÃO apaga volumes/dados)
	@echo "🧹 Parando containers e removendo imagens órfãs..."
	$(COMPOSE_CMD) down --remove-orphans
	$(DOCKER_CMD) image prune -f
	@echo "ℹ️  Volumes preservados. Use 'make clean-volumes' para apagar dados."

clean-volumes: ## ⚠️  DESTRÓI todos os volumes (postgres + garage). DADOS SERÃO PERDIDOS!
	@echo "⚠️  ATENÇÃO: Isso vai apagar TODOS os dados (PostgreSQL + Garage S3)."
	@read -p "Digite 'sim' para confirmar: " confirm && [ "$$confirm" = "sim" ] || (echo "Cancelado." && exit 1)
	$(COMPOSE_CMD) down -v --remove-orphans
	$(DOCKER_CMD) system prune -f
	@echo "✅ Volumes e dados removidos."

discover: ## Descobre o universo de dados disponíveis na Receita Federal
	@echo "🔍 Descobrindo dados disponíveis na Receita Federal..."
	$(COMPOSE_CMD) exec api python -m src.jobs.discovery

sync: ## Sincroniza dados de um mês específico (ex: make sync MONTH=2023-05)
	@echo "📥 Sincronizando dados do mês $(MONTH)..."
	$(COMPOSE_CMD) exec api python -m src.jobs.sync --year-month $(MONTH)

sync-file: ## Baixa um arquivo individual (ex: make sync-file MONTH=2025-06 FILE=Empresas0.zip)
	@echo "📥 Baixando arquivo individual: $(FILE) de $(MONTH)..."
	$(COMPOSE_CMD) exec api python -m src.jobs.sync --year-month $(MONTH) --file $(FILE)

ingest: ## Executa o pipeline completo de ingestão
	@echo "⚙️ Executando pipeline de ingestão..."
	$(COMPOSE_CMD) exec api python -m src.ingest $(if $(MONTH),--year-month $(MONTH),)

s3-status: ## Mostra status de conectividade do Garage S3
	@echo "🪣 Verificando status do Garage S3..."
	@curl -s http://localhost:8000/s3/status | python3 -m json.tool

s3-list: ## Lista objetos no bucket S3 (ex: make s3-list PREFIX=2025-06/)
	@echo "📋 Listando objetos no S3..."
	@curl -s "http://localhost:8000/s3/objects$(if $(PREFIX),?prefix=$(PREFIX),)" | python3 -m json.tool

verify: ## Verifica integridade dos downloads de um mês (ex: make verify MONTH=2025-06)
	@echo "🔒 Verificando integridade dos downloads de $(MONTH)..."
	@curl -s -X POST http://localhost:8000/admin/sync/$(MONTH)/verify | python3 -m json.tool

transform: ## Roda transform para um mês via API (ex: make transform MONTH=2026-04)
	@echo "⚙️  Disparando transform para $(MONTH) via API..."
	@curl -s -X POST "http://localhost:8000/admin/transform/$(MONTH)" | python3 -m json.tool

transform-file: ## Transforma arquivo individual via API (ex: make transform-file MONTH=2026-04 FILE=Simples.zip)
	@echo "⚙️  Disparando transform de $(FILE) ($(MONTH)) via API..."
	@curl -s -X POST "http://localhost:8000/admin/transform/$(MONTH)/file/$(FILE)" | python3 -m json.tool

transform-status: ## Status dos Parquets transformados (ex: make transform-status MONTH=2026-04)
	@echo "📊 Status do transform para $(MONTH)..."
	@curl -s "http://localhost:8000/admin/transform/$(MONTH)/status" | python3 -m json.tool

load-db: ## Carrega Parquets no PostgreSQL via COPY (ex: make load-db MONTH=2026-04 MODE=append)
	@echo "🐘 Disparando carga PostgreSQL para $(MONTH) [mode=$(or $(MODE),append)]..."
	@curl -s -X POST "http://localhost:8000/admin/load-db/$(MONTH)?if_exists=$(or $(MODE),append)" | python3 -m json.tool

load-db-file: ## Carrega Parquet individual no PostgreSQL (ex: make load-db-file MONTH=2026-04 FILE=Empresas0.parquet)
	@echo "🐘 Carregando $(FILE) no PostgreSQL [mode=$(or $(MODE),append)]..."
	@curl -s -X POST "http://localhost:8000/admin/load-db/$(MONTH)/file/$(FILE)?if_exists=$(or $(MODE),append)" | python3 -m json.tool

load-db-status: ## Status da carga PostgreSQL (ex: make load-db-status MONTH=2026-04)
	@echo "📊 Status da carga PostgreSQL para $(MONTH)..."
	@curl -s "http://localhost:8000/admin/load-db/$(MONTH)/status" | python3 -m json.tool

load-s3: ## Upload Parquets para Garage S3 (ex: make load-s3 MONTH=2026-04)
	@echo "☁️  Disparando upload S3 para $(MONTH)..."
	@curl -s -X POST "http://localhost:8000/admin/load-s3/$(MONTH)" | python3 -m json.tool

explore: ## Explora dados raw sem modificá-los (ex: make explore MONTH=2026-04)
	@echo "🔍 Explorando dados raw de $(MONTH)..."
	$(COMPOSE_CMD) exec api python -m scripts.explore_raw --year-month $(MONTH) $(if $(FILE),--file $(FILE),) $(if $(NROWS),--nrows $(NROWS),)

logs: ## Mostra logs em tempo real
	$(COMPOSE_CMD) logs -f

data-quality: ## Executa testes de qualidade de dados com Great Expectations
	@echo "🧪 Executando Great Expectations Checks..."
	$(COMPOSE_CMD) exec api python -m src.jobs.data_quality
