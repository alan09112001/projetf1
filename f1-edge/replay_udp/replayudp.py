import time
import socket
import sys
from scapy.all import rdpcap

# --- CONFIGURATION ---
# Mets ici le nom exact de ton fichier enregistré
FILENAME = "autriche1tour.pcap" 
DEST_IP = "127.0.0.1"
DEST_PORT = 20777

def play_once():
    print(f"📂 Chargement du fichier {FILENAME} en mémoire... (Patientez)")
    try:
        packets = rdpcap(FILENAME)
    except FileNotFoundError:
        print(f"❌ ERREUR : Le fichier '{FILENAME}' n'existe pas.")
        print("   Assure-toi d'avoir enregistré des données d'abord.")
        return

    total_packets = len(packets)
    print(f"✅ {total_packets} paquets chargés. Démarrage du Replay...")
    print("🏎️  Envoi des données en TEMPS RÉEL...")

    # Configuration du socket UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Initialisation du temps
    start_time = time.time()
    
    # On prend le timestamp du premier paquet comme référence zéro
    if total_packets > 0:
        first_pkt_timestamp = float(packets[0].time)
    else:
        print("⚠️ Fichier vide.")
        return

    # --- BOUCLE DE LECTURE (UNE SEULE FOIS) ---
    for i, pkt in enumerate(packets):
        # 1. On vérifie que le paquet contient des données UDP (Raw payload)
        if hasattr(pkt, 'load'):
            payload = pkt.load
        else:
            continue # On saute les paquets vides

        # 2. Synchronisation Temporelle (Le secret du temps réel)
        # A quel moment ce paquet devait-il être joué ?
        target_time = float(pkt.time) - first_pkt_timestamp
        
        # Combien de temps s'est écoulé depuis qu'on a lancé le script ?
        current_elapsed = time.time() - start_time
        
        # Si on est en avance, on dort un peu
        wait = target_time - current_elapsed
        if wait > 0:
            time.sleep(wait)

        # 3. Envoi du paquet
        sock.sendto(payload, (DEST_IP, DEST_PORT))

        # 4. Affichage Progression (Tous les 100 paquets pour ne pas spammer)
        if i % 100 == 0:
            percent = (i / total_packets) * 100
            # Affichage dynamique sur la même ligne
            sys.stdout.write(f"\r⏳ Progression : [{percent:.1f}%] - Paquet {i}/{total_packets}")
            sys.stdout.flush()

    print("\n\n" + "="*40)
    print("🏁 REPLAY TERMINÉ ! TOUS LES TOURS ENVOYÉS.")
    print("="*40)

if __name__ == "__main__":
    play_once()