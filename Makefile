.PHONY: build up down test clean

# TODO: Implementar a construção da imagem
build:
	@echo "Construindo a imagem com Podman..."
	# podman build -f ContainerFile -t fastapi-cnpj .

# TODO: Implementar subida do ambiente usando compose
up:
	@echo "Subindo o ambiente..."
	# podman-compose up -d --build

# TODO: Implementar a descida do ambiente
down:
	@echo "Derrubando o ambiente..."
	# podman-compose down

# TODO: Implementar a execução dos testes
test:
	@echo "Executando testes locais..."
	# pytest tests/

# TODO: Implementar limpeza de imagens e volumes (opcional/cuidado!)
clean:
	@echo "Limpando artefatos locais..."
	# podman system prune -f
