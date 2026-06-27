# pos-ia-eng-devops 🚀

![Python](https://img.shields.io/badge/python-3.14-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.137.0.svg?logo=fastapi)
![Docker](https://img.shields.io/badge/Podman-ready-blue?logo=podman)
![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)
<!-- TODO: Pesquise sobre https://shields.io/ e aprenda a usar badges reais. Eles ajudam a comunicar o status, versão e qualidade do seu projeto de forma profissional! -->

> [!NOTE]
> Este repositório utiliza ferramentas de Inteligência Artificial para apoiar seu desenvolvimento. Durante as aulas para fins educativos, testamos as habilidades de "Vibe Code" e exploramos a preparação do repositório orientada a **Spec Driven Development**.

Repositório base para o curso de **DevOps e MLOps Aplicado a Engenharia de Dados**.
Pipeline completo de dados públicos de CNPJ da Receita Federal — da ingestão ao analytics.

---

## 🎯 Objetivo do Projeto

Criar um pipeline de dados completo e robusto que:
1. Descobre e baixa os dados públicos de CNPJ da Receita Federal (discovery + sync).
2. Transforma CSVs brutos em Parquet otimizado (transform).
3. Carrega dados no PostgreSQL via COPY para consulta e analytics (load-db).
4. Persiste ZIPs originais e Parquets processados no Garage S3 em camadas (load-s3).
5. Expõe API REST (FastAPI) para controle de todo o pipeline.
6. Oferece dashboards via Metabase conectado ao PostgreSQL.
7. É orquestrado e conteinerizado localmente com Podman e Podman-Compose.

---

## 🏗️ Arquitetura

```text
┌──────────────────┐
│  Receita Federal │
│   (WebDAV/HTTP)  │
└────────┬─────────┘
         │ discovery + sync
         ▼
┌──────────────────┐     ┌─────────────────────────────────────┐
│  /tmp/data/raw/  │────▶│  Garage S3 (cnpj-data bucket)       │
│   *.zip (staging)│     │  ├── raw/{ym}/*.zip       (imutável)│
└────────┬─────────┘     │  └── processed/{ym}/*.parquet       │
         │ transform     └─────────────────────────────────────┘
         ▼
┌──────────────────┐     ┌─────────────────────┐
│  /tmp/processed/ │────▶│  PostgreSQL 17       │
│   *.parquet      │     │  cnpj_empresas       │
│  (staging)       │     │  cnpj_estabelecim... │
└──────────────────┘     │  cnpj_socios         │
                         │  cnpj_simples        │
                         │  + lookups            │
                         └────────┬──────────────┘
                                  │
                         ┌────────▼──────────────┐
                         │  Metabase (:3000)      │
                         │  FastAPI  (:8000/docs) │
                         └────────────────────────┘
```

---

## 🏗️ Estrutura do Repositório

```text
├── .github/workflows/     # 🔜 CI/CD GitHub Actions (Lab 2.1)
├── ContainerFile          # Multi-stage build + usuário rootless (appuser)
├── Makefile               # Targets para todo o pipeline
├── compose.yaml           # API, PostgreSQL, Garage S3, Metabase
├── config/garage.toml     # Configuração do Garage S3
├── docs/adr/              # Decisões de Arquitetura (ADRs)
├── k8s/                   # 🔜 Kubernetes Manifests (Lab 2.3)
├── scripts/
│   ├── explore_raw.py     # Exploração de dados raw sem modificar
│   └── init_garage.sh     # Setup manual do Garage (se necessário)
├── src/
│   ├── config.py          # Configurações via variáveis de ambiente (12-Factor)
│   ├── exceptions.py      # Exceções customizadas
│   ├── ingest.py          # Orquestrador do pipeline batch
│   ├── main.py            # API FastAPI com documentação OpenAPI
│   ├── utils.py           # Funções utilitárias compartilhadas
│   ├── jobs/              # Tarefas do pipeline
│   │   ├── discovery.py   # Descobre dados disponíveis na RF via WebDAV
│   │   ├── sync.py        # Download com progresso, SHA-256, hash diff
│   │   ├── transform.py   # CSV → Parquet (chunked, com regras de negócio)
│   │   ├── load_db.py     # Parquet → PostgreSQL via psycopg2 COPY
│   │   └── load_s3.py     # Upload para Garage S3 (raw + processed)
│   ├── models/            # SQLAlchemy
│   │   ├── database.py    # Engine, Session, Base
│   │   ├── empresa.py     # Model Empresas
│   │   ├── schema_cnpj.py # Models: Estabelecimentos, Sócios, Simples, Lookups
│   │   └── sync_control.py# Controle de sincronização (estado do pipeline)
│   └── routers/           # Endpoints HTTP
│       ├── admin.py       # Dashboard, sync, transform, load-db, load-s3
│       ├── empresas.py    # Consulta de empresas por CNPJ/razão social
│       └── s3_status.py   # Status do Garage S3 e gap analysis
└── tests/
    ├── test_unit.py       # Testes unitários (transformação)
    └── test_e2e.py        # Testes E2E (API endpoints)
```

---

## ✅ Checklist de Implementação (Labs)

### Aula 1: Fundamentos DevOps e Ingestão de Dados
- [x] **Lab 1.1**: Multi-stage build e usuário rootless no `ContainerFile`.
- [x] **Lab 1.2**: Serviços `db`, `storage`, `metabase` no `compose.yaml` com volumes e healthchecks.
- [x] **Lab 1.3**: `Makefile` completo com targets para todo o pipeline.
- [x] **Lab 1.4**: Pipeline de ingestão com discovery, sync, transform, load.
- [x] **Bônus**: ADRs, discovery inteligente da RF, Admin Dashboard via API, hash SHA-256, Metabase.

### Aula 2: CI/CD e Data Quality
- [ ] **Lab 2.1**: Pipelines CI/CD com GitHub Actions (linting, testes, build).
- [ ] **Lab 2.2**: Data Quality com Soda Core integrado ao pipeline.
- [ ] **Lab 2.3**: Deploy em Kubernetes local via Kind.

### Aula 3: MLOps
- [ ] **Lab 3.1**: Ambiente MLflow via compose para tracking de experimentos.
- [ ] **Lab 3.2**: DVC para versionamento de dados integrado ao Garage S3.
- [ ] **Lab 3.3**: Model Serving conteinerizado como API REST.

---

## 💻 Como Iniciar

### Pré-requisitos
- [Podman](https://podman.io/) instalado.
- [Podman Compose](https://github.com/containers/podman-compose).
- Make (opcional, porém recomendado).

### Pipeline Completo

```bash
# 1. Subir todos os serviços
make up

# 2. Descobrir dados disponíveis na Receita Federal
make discover

# 3. Sincronizar (baixar) dados de um mês
make sync MONTH=2026-04

# 4. Transformar CSVs em Parquet
make transform MONTH=2026-04

# 5. Carregar no PostgreSQL
make load-db MONTH=2026-04

# 6. Upload para Garage S3 (raw + processed)
make load-s3 MONTH=2026-04
```

### Monitoramento

```bash
# Status do transform
make transform-status MONTH=2026-04

# Status da carga PostgreSQL
make load-db-status MONTH=2026-04

# Listar objetos no S3
make s3-list PREFIX=raw/2026-04/

# Verificar integridade dos downloads
make verify MONTH=2026-04
```

### Acessos

| Serviço | URL |
|---|---|
| **API (Swagger UI)** | http://localhost:8000/docs |
| **Metabase** | http://localhost:3000 |
| **PostgreSQL** | `localhost:5432` (user: postgres, db: cnpj) |
| **Garage S3** | `localhost:3900` |

---

## 📡 API — Endpoints Principais

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/admin/sync` | Dashboard de sincronização |
| `POST` | `/admin/sync/discover` | Descobrir dados na RF |
| `POST` | `/admin/sync/{ym}` | Sincronizar mês (background) |
| `GET` | `/admin/sync/{ym}/diff` | Hash diff: remoto vs local |
| `POST` | `/admin/transform/{ym}` | Transformar mês inteiro |
| `GET` | `/admin/transform/{ym}/status` | Status dos Parquets |
| `POST` | `/admin/load-db/{ym}` | Carregar no PostgreSQL |
| `GET` | `/admin/load-db/{ym}/status` | Status da carga |
| `POST` | `/admin/load-s3/{ym}` | Upload S3 (raw + processed) |
| `GET` | `/s3/objects` | Listar objetos no bucket |
| `GET` | `/empresas/search?razao_social=...` | Buscar empresas |

Documentação completa com exemplos: **http://localhost:8000/docs**

---

## 📐 Decisões de Arquitetura

Consulte os ADRs em `docs/adr/`:
- [ADR 0001](docs/adr/0001-usar-podman-em-vez-de-docker.md) — Podman em vez de Docker
- [ADR 0002](docs/adr/0002-estrutura-api-e-jobs-batch.md) — Estrutura API + Jobs batch
- [ADR 0003](docs/adr/0003-garage-como-object-storage.md) — Garage como Object Storage

---

> 💡 **Dica**: Use `make help` para ver todos os targets disponíveis no Makefile.
