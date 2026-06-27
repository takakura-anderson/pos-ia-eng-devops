#!/bin/bash
set -e

echo "⏳ Aguardando o Garage iniciar..."
sleep 3

# 1. Configurar o layout
echo "🔧 Configurando layout do cluster..."
NODE_ID=$(podman compose exec storage /garage status | awk '/^[0-9a-f]+/ {print $1}' | tail -n 1)
if [ -z "$NODE_ID" ]; then
    echo "❌ Erro: Não foi possível obter o ID do nó do Garage."
    exit 1
fi
podman compose exec storage /garage layout assign -z us-east-1 -c 1G "$NODE_ID"
podman compose exec storage /garage layout apply --version 1 || echo "Layout versão 1 já aplicado."

# 2. Criar Bucket
echo "🪣 Criando bucket cnpj-data..."
podman compose exec storage /garage bucket create cnpj-data || echo "Bucket já existe."

# 3. Criar chave e configurar permissões
echo "🔑 Criando chaves de acesso (minioadmin)..."
podman compose exec storage /garage key import minioadmin minioadmin -n minioadmin --yes || true
podman compose exec storage /garage bucket allow cnpj-data --read --write --owner --key minioadmin

echo "✅ Garage configurado com sucesso!"
