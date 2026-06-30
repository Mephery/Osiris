#!/usr/bin/env bash
# build.sh - Compile le frontend React avant de lancer Docker Compose.
# Usage : ./build.sh

set -e

cd "$(dirname "$0")/frontend"

if [ ! -f .env ]; then
    if [ -f ../.env ]; then
        # Extraire VITE_API_URL depuis le .env racine
        VITE_URL=$(grep '^VITE_API_URL=' ../.env | cut -d= -f2-)
        echo "VITE_API_URL=${VITE_URL}" > .env
        echo "Frontend .env genere depuis .env racine (VITE_API_URL=${VITE_URL})"
    else
        echo "ERREUR : .env manquant. Copier .env.example en .env et le remplir."
        exit 1
    fi
fi

echo "Installation des dependances npm..."
npm install --silent

echo "Build de production du frontend..."
npm run build

echo "Frontend compile avec succes -> frontend/dist/"
