# ADR 0005: Processamento Chunked com PyArrow para Arquivos Massivos

## Status
Aceito

## Contexto
Os dados públicos da Receita Federal contêm arquivos CSV (como o "Simples.zip" ou "Estabelecimentos") que, descompactados, chegam a vários Gigabytes. Carregar esses dataframes inteiros no Pandas resultava em *Out Of Memory* (OOM) no container da API.

## Decisão
Implementamos uma leitura assíncrona baseada em chunks de 50.000 linhas usando o iterador nativo do Pandas. Cada chunk passa pelas regras de negócio e é incrementado em um arquivo físico Parquet local via `pyarrow.parquet.ParquetWriter`.

## Consequências
- **Positivas**: Uso estável e baixo de RAM. Arquivos infinitamente grandes podem ser convertidos localmente sem estourar a máquina.
- **Negativas**: O progresso é assíncrono, então a leitura dos metadados (como *row_count*) pela API de status só funciona *após* a finalização total da escrita (com fechamento do writer). Isso causou bugs temporários visuais na interface.
