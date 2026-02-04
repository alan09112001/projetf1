#!/bin/bash

# 1. Se placer dans le dossier du script
cd "$(dirname "$0")"

echo "🏎️  --- MASTER 2 INFRA CLOUD : PROJET F1 TELEMETRY ---"

# --- ÉTAPE 1 : Démarrage Infrastructure Cloud ---
if [ -d "../f1-cloud" ]; then
    echo "☁️  Démarrage des conteneurs Docker (Mosquitto, InfluxDB, Grafana)..."
    
    # On va dans le dossier cloud pour lancer le compose
    pushd ../f1-cloud > /dev/null
    docker-compose up -d
    
    if [ $? -eq 0 ]; then
        echo "✅ Cloud opérationnel."
        echo "   📊 Grafana : http://localhost:3000 (Login: admin / admin)"
    else
        echo "❌ Erreur Docker. Vérifie que Docker Desktop tourne."
        exit 1
    fi
    popd > /dev/null
else
    echo "❌ Erreur : Dossier '../f1-cloud' introuvable."
    exit 1
fi

# --- ÉTAPE 2 : Préparation Environnement Python (Edge) ---
if [ ! -d "venv" ]; then
    echo "🐍 Création de l'environnement virtuel..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "📦 Installation des dépendances..."
pip install -r requirements.txt > /dev/null 2>&1

# --- ÉTAPE 3 : Détection IP ---
MON_IP=$(python3 -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8', 80)); print(s.getsockname()[0]); s.close()")

echo "📡 CONFIGURATION JEU :"
echo "   - IP : $MON_IP"
echo "   - Port : 20777"
echo "   - Format : F1 23"

# --- ÉTAPE 4 : Lancement ---
echo "🚀 Démarrage de l'agent de télémétrie..."
python3 listener.py