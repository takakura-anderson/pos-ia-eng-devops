# 8. Estratégia de Model Serving

Data: 2026-07-11

## Status

Aceito

## Contexto

Com o desenvolvimento do modelo de predição de "Optante pelo Simples" (usando RandomForest) treinado sobre os dados da Receita Federal e versionado via MLflow e DVC, precisávamos de uma forma de expor o modelo para ser consumido por outras aplicações, sem quebrar ou interferir nas APIs existentes (consulta de empresas, dashboard).

A aplicação atual usa FastAPI, que é altamente performática e projetada para requisições assíncronas, o que a torna ideal também para machine learning serving leve.

## Decisão

Adotamos a estratégia de **Model Serving Embutido na API FastAPI**, onde o modelo preditivo atua como mais um "Router" dentro da aplicação principal (na rota `/predict`), em vez de instanciar um serviço isolado. 

Como o modelo é carregado:
1. No evento de `startup` do FastAPI (`@router.on_event("startup")`), o modelo "SimplesClassifier" é baixado da URI correspondente do MLflow (apontando para o Garage/S3 local).
2. O modelo (usando a classe `mlflow.pyfunc.load_model`) fica armazenado em memória (variável global do módulo router).
3. A rota `POST /predict/` aceita payloads no formato Pydantic contendo os atributos (natureza jurídica, capital social, porte empresa) e retorna a probabilidade/classe.
4. Para evitar que a API caia, envolvemos a carga do modelo num `try-except` de modo que, se o modelo não existir no repositório ainda, o serviço devolve "503 Service Unavailable" na rota `/predict`, mas os outros endpoints de consulta do CNPJ continuam operantes.

## Consequências

**Positivas:**
- Redução da complexidade arquitetural: sem necessidade de orquestrar um container extra rodando o servidor próprio do MLflow (`mlflow models serve`) ou Seldon Core.
- Permite reaproveitar a infraestrutura, monitoramento e métricas de tráfego (middlewares) que já temos na API.
- Maior velocidade e menos "cold-starts" no tempo de resposta para inferência, pois o modelo fica carregado diretamente na memória da API base.

**Negativas:**
- Se o modelo for muito pesado, ele competirá por memória (RAM) e CPU com a API regular de consulta aos bancos de dados, podendo impactar a escalabilidade do sistema transacional de dados. (Para este laboratório, o modelo RandomForest é leve o suficiente para não representar perigo).
