#!/bin/bash
cd "$(dirname "$0")"

# --- NETTOYAGE PRÉVENTIF ---
# On tue brutalement toute ancienne instance de listener.py avant de commencer
echo "🧹 Nettoyage des anciens processus..."
pkill -f listener.py
sleep 1 # On laisse une seconde au système pour libérer les ports

# Fonction pour tout tuer proprement quand on fait Ctrl+C
cleanup() {
    echo ""
    echo "🛑 Arrêt des services..."
    pkill -P $$ 
    pkill -f listener.py # Double sécurité à la fermeture
    exit
}
trap cleanup SIGINT

echo "🏎️  --- INFRASTRUCTURE F1 : DUAL STREAM ---"

# 1. Démarrage Cloud (Docker)
if [ -d "../f1-cloud" ]; then
    echo "☁️  Lancement Docker..."
    pushd "../f1-cloud" > /dev/null
    docker-compose up -d
    popd > /dev/null
else
    echo "❌ Dossier Cloud introuvable."
    exit 1
fi

# 2. Setup Python
if [ ! -d "venv" ]; then python3 -m venv venv; fi
source venv/bin/activate
pip install -r requirements.txt > /dev/null 2>&1

echo "🚀 Démarrage des Listeners en parallèle..."

# --- INSTANCE 1 : Le Jeu LIVE (Port 20777) ---
export UDP_PORT=20777
export DRIVER_NAME="Live_Player"
echo "   [1] Listener démarré sur port 20777 (Tag: Live_Player)"
python3 listener.py &

# --- INSTANCE 2 : Le Replay (Port 20778) ---
export UDP_PORT=20778
export DRIVER_NAME="Replay_Data"
echo "   [2] Listener démarré sur port 20778 (Tag: Replay_Data)"
python3 listener.py &

echo "✅ Système actif."
echo "📊 Grafana : http://localhost:3000"
echo "   (Ctrl+C pour arrêter)"

wait