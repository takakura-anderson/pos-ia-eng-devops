# ADR 0006: Validação de Qualidade de Dados com Great Expectations

## Status
Aceito

## Contexto
O processo de ingestão insere os dados via COPY diretamente no banco PostgreSQL. Para atender aos critérios do Encontro 02 ("Data quality checks"), precisávamos de uma ferramenta que validasse os dados no pós-carga. Inicialmente o *Soda Core* havia sido considerado, porém a equipe prefere ferramentas 100% integráveis em ecossistemas Python nativos para padronização.

## Decisão
Adotamos o **Great Expectations (GX)** para rodar verificações de Data Quality (DQ) direto nas tabelas do PostgreSQL. As regras estão estruturadas via código nativo no script `src/jobs/data_quality.py`, configurando *Datasources*, *Expectation Suites* e *Checkpoints* programaticamente (em memória).

## Consequências
- **Positivas**: Como o Great Expectations é 100% Python, não precisamos de arquivos YAML desconexos (como no Soda). Isso facilita testes unitários e a manipulação dinâmica de expectativas.
- **Negativas**: A curva de aprendizado inicial da API do GX pode ser mais alta, e a execução em banco exige que a carga no Postgres já tenha sido concluída (verificação reativa).
