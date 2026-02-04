import os
import json
import paho.mqtt.client as mqtt
from f1_23_telemetry.listener import TelemetryListener

# --- CONFIGURATION ---
UDP_PORT = int(os.getenv("UDP_PORT", 20777))
BASE_DRIVER_NAME = os.getenv("DRIVER_NAME", "Unknown")
MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_TOPIC = "f1/telemetry"

client = mqtt.Client(client_id=f"Edge_{UDP_PORT}")
try:
    client.connect(MQTT_BROKER, 1883, 60)
    client.loop_start()
    print(f"✅ Listener Hybride actif : {BASE_DRIVER_NAME}")
except Exception as e:
    print(f"❌ Erreur MQTT : {e}")

def main():
    listener = TelemetryListener(port=UDP_PORT, host="0.0.0.0")
    
    # --- MÉMOIRE ---
    session_counter = 1
    max_distance_reached = 0.0
    current_driver_tag = f"{BASE_DRIVER_NAME}_S{session_counter}"
    
    # Mémoire pour l'UID (Identifiant unique de la session par le jeu)
    last_session_uid = None

    print(f"📡 Prêt. Enregistrement sous : {current_driver_tag}")

    while True:
        try:
            packet = listener.get()
            pid = packet.header.packet_id
            player_index = packet.header.player_car_index
            
            # --- 1. DÉTECTION "HARD" (Via l'UID du jeu) ---
            # Si cet ID change, c'est que le jeu a rechargé (Restart, Menu, Nouveau circuit)
            current_uid = packet.header.session_uid
            
            if last_session_uid is None:
                last_session_uid = current_uid
            
            if current_uid != last_session_uid:
                # C'est un vrai Restart officiel
                session_counter += 1
                current_driver_tag = f"{BASE_DRIVER_NAME}_S{session_counter}"
                max_distance_reached = 0.0 # On remet le compteur distance à zéro
                last_session_uid = current_uid
                print(f"🔄 NOUVELLE SESSION (UID) -> Reset Graphique : {current_driver_tag}")

            # --- 2. DÉTECTION "SOFT" (Via la distance) ---
            # Utile pour les modes "Time Trial" où l'UID ne change pas toujours au restart
            if pid == 2:
                current_dist = float(packet.lap_data[player_index].total_distance)
                
                # Si on passe de >300m à <100m sans changement d'UID
                if max_distance_reached > 300 and current_dist < 100:
                    session_counter += 1
                    current_driver_tag = f"{BASE_DRIVER_NAME}_S{session_counter}"
                    max_distance_reached = 0.0
                    print(f"✂️  RESET MANUEL (Dist) -> Nouvelle courbe : {current_driver_tag}")

                # LOGIQUE D'AVANCE STRICTE (Anti-Flashback)
                elif current_dist > max_distance_reached:
                    max_distance_reached = current_dist

            # --- 3. ENVOI DES DONNÉES (Packet 6) ---
            elif pid == 6:
                car = packet.car_telemetry_data[player_index]
                
                # On envoie seulement si :
                # - On roule (> 5 km/h) pour éviter le bruit à l'arrêt
                # - On a une distance valide (> 0)
                if car.speed > 5 and max_distance_reached > 0:
                    
                    payload = {
                        "speed": float(car.speed),
                        "rpm": float(car.engine_rpm),
                        "throttle": float(car.throttle),
                        "brake": float(car.brake),
                        "gear": int(car.gear),
                        
                        # On utilise TOUJOURS le max atteint pour figer le graph en cas de flashback
                        "total_distance": max_distance_reached,
                        
                        "driver_name": current_driver_tag,
                        "source_port": UDP_PORT
                    }
                    client.publish(MQTT_TOPIC, json.dumps(payload))

        except Exception:
            pass

if __name__ == "__main__":
    main()