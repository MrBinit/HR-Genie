#!/bin/bash

echo "🌍 Select Environment: [prod/internal]"
read -p "Enter environment: " ENV

if [[ "$ENV" == "internal" ]]; then
    docker compose down
    echo "🚀 Stopping and removing existing containers (Internal)..."
    docker compose build --no-cache
    echo "🔧 Rebuilding Docker images without cache (Internal)..."
    docker compose up
    echo "📦 Starting up the containers (Internal)..."


elif [[ "$ENV" == "prod" ]]; then
    docker compose down
    echo "🚀 Stopping and removing existing containers (Production)..."
    docker compose -f docker-compose.prod.yaml up --build
    echo "🔧 Rebuilding Docker images without cache (Production)..."
    docker compose -f docker-compose.prod.yaml up
    echo "📦 Starting containers without rebuilding (Production)..."
    echo "📦 Starting up the containers (Production)..."
else
    echo "❌ Invalid environment selected. Please enter 'prod' or 'internal'."
    exit 1
fi