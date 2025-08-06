#!/bin/bash

set -e

echo "Stopping and disabling system-installed Ollama..."
sudo systemctl stop ollama || true
sudo systemctl disable ollama || true

echo "Removing old Docker container named 'ollama' (if exists)..."
docker rm -f ollama || true

echo "Installing Docker (if not installed)..."
if ! command -v docker &> /dev/null; then
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg lsb-release

  sudo mkdir -p /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
  echo "Docker already installed."
fi

echo "Installing NVIDIA Container Toolkit..."
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

echo "Configuring Docker for NVIDIA GPU runtime..."
sudo nvidia-ctk runtime configure --runtime=docker

echo "Restarting Docker..."
sudo systemctl restart docker

echo "Pulling Ollama Docker image..."
docker pull ollama/ollama:latest

echo "Running Ollama in Docker with GPU..."
docker run -d --gpus=all \
  -v ollama:/root/.ollama \
  -p 11434:11434 \
  --name ollama \
  ollama/ollama

echo "Waiting for Ollama to start..."
sleep 5

echo "Pulling model 'mistral:7b-instruct' inside the Ollama container..."
docker exec ollama ollama pull mistral:7b-instruct

echo "Setting up PostgreSQL and Adminer..."
docker network create hr_network || true

docker run -d \
  --name hr_postgres \
  --network hr_network \
  -e POSTGRES_USER=hr_user \
  -e POSTGRES_PASSWORD=hr_password \
  -e POSTGRES_DB=hr_db \
  -p 5433:5432 \
  postgres:16

docker run -d \
  --name adminer_ui \
  --network hr_network \
  -p 8081:8080 \
  adminer

echo ""
echo "All setup complete."
echo ""
echo "Ollama running at:      http://localhost:11434"
echo "Model pulled:           mistral:7b-instruct"
echo "Postgres running at:    port 5433 (user: hr_user / pass: hr_password)"
echo "Adminer UI at:          http://localhost:8081"
