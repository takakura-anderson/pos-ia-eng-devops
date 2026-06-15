# pos-ia-eng-devops 🚀

![Python](https://img.shields.io/badge/python-3.14-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688.svg?logo=fastapi)
![Docker](https://img.shields.io/badge/Podman-ready-blue?logo=podman)
![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)
<!-- TODO: Pesquise sobre https://shields.io/ e aprenda a usar badges reais. Eles ajudam a comunicar o status, versão e qualidade do seu projeto de forma profissional! -->

Repositório base para o curso de **DevOps e MLOps Aplicado a Engenharia de Dados**.
Este projeto contém o esqueleto inicial da arquitetura. Durante os laboratórios de cada encontro, você será guiado para completar os **TODOs** espalhados pelo código, evoluindo a infraestrutura e o pipeline de dados de ponta a ponta.

---

## 🎯 Objetivo do Projeto

Criar um pipeline de dados completo e robusto que:
1. Faz a ingestão dos dados públicos de CNPJ da Receita Federal.
2. Trata e carrega esses dados (Data Engineering).
3. Armazena as informações em um Data Warehouse local (PostgreSQL).
4. Persiste artefatos brutos/processados em um Object Storage compatível com S3 (Garage S3).
5. É orquestrado e conteinerizado localmente com Podman e Podman-Compose.
6. Possui CI/CD com verificações de qualidade automatizadas e deploy em Kubernetes (Kind).
7. Versiona os dados com DVC e gerencia modelos com MLflow.

---

## 🏗️ Estrutura do Repositório (Base)

```text
├── src/                   # Código fonte Python
│   ├── main.py            # API FastAPI (esqueleto)
│   └── ingest.py          # Script de ingestão batch (TODO)
├── ContainerFile          # Arquivo de construção da imagem (TODO: multistage)
├── compose.yaml           # Orquestração local (TODO: db e storage)
├── Makefile               # Automação de tarefas locais (TODO)
├── requirements.txt       # Dependências do projeto (TODO: libs de dados)
├── .gitignore             # Arquivos ignorados no Git (TODO)
└── .containerignore       # O que não deve ir para a imagem de container (TODO)
```

> 💡 **Dica de Ouro**: Se você está em dúvida sobre o que ignorar no Git, use o site [gitignore.io](https://www.toptal.com/developers/gitignore) para gerar templates automáticos. Nunca suba credenciais ou arquivos inúteis pro repositório! Além disso, lembre-se que o `.containerignore` faz o mesmo trabalho, mas focando em impedir que arquivos desnecessários inchem sua imagem do container durante o `podman build`.

---

## ✅ Checklist de Implementação (Labs)

À medida que avançamos nas aulas, você deverá implementar as seguintes melhorias:

### Aula 1: Fundamentos DevOps e Ingestão de Dados
- [ ] **Lab 1.1**: Implementar `Multi-stage build` e usuário *rootless* no `ContainerFile`.
- [ ] **Lab 1.2**: Adicionar serviços `db` (PostgreSQL) e `storage` (Garage) no `compose.yaml`, incluindo configuração de volumes locais e *healthchecks*.
- [ ] **Lab 1.3**: Completar o `Makefile` com comandos práticos (`build`, `up`, `down`, `test`, `clean`).
- [ ] **Lab 1.4**: Desenvolver a rotina em `src/ingest.py` usando `pandas` (ou similar) para baixar dados, limpar e enviar para o banco. Adicionar libs necessárias no `requirements.txt`.

### Aula 2: CI/CD e Data Quality
- [ ] **Lab 2.1**: Configurar pipelines CI/CD usando GitHub Actions (linting, testes, build).
- [ ] **Lab 2.2**: Implementar validação de *Data Quality* (ex: com Soda Core) integrada ao pipeline.
- [ ] **Lab 2.3**: Empacotar o deploy para um cluster Kubernetes local via `Kind`.

### Aula 3: MLOps
- [ ] **Lab 3.1**: Subir ambiente MLflow via compose e versionar tracking de experimentos.
- [ ] **Lab 3.2**: Configurar DVC para versionar os arquivos grandes `.csv` / `.parquet` diretamente no repositório integrado ao Garage S3.
- [ ] **Lab 3.3**: Conteinerizar o serviço de Model Serving como uma API REST robusta pronta para predições em produção.

---

## 💻 Como Iniciar (Ambiente Atual)

### Pré-requisitos
- [Podman](https://podman.io/) instalado.
- [Podman Compose](https://github.com/containers/podman-compose).
- (Opcional) Make.

### Executando o esqueleto da API
```bash
# 1. Construir a imagem base
podman build -f ContainerFile -t fastapi-cnpj .

# 2. Subir via compose
podman-compose up -d --build
```
A API inicial estará disponível em `http://localhost:8000/docs`.

---
> ⚠️ **Dica**: Procure pelas tags `# TODO` nos arquivos do repositório para saber exatamente onde colocar a mão na massa!
