import os
import json
import time
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from f1_23_telemetry.listener import TelemetryListener

# --- CONFIGURATION ---
UDP_PORT = int(os.getenv("UDP_PORT", 20777))
BASE_DRIVER_NAME = os.getenv("DRIVER_NAME", "Unknown")
MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_TOPIC = "f1/telemetry"

client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id=f"Edge_{UDP_PORT}")

try:
    client.connect(MQTT_BROKER, 1883, 60)
    client.loop_start()
    print(f"✅ MODE LIVE TIMING ACTIVÉ : {BASE_DRIVER_NAME}")
except Exception as e:
    print(f"❌ Erreur MQTT : {e}")

def main():
    listener = TelemetryListener(port=UDP_PORT, host="0.0.0.0")
    
    # Variables de Session
    session_counter = 1
    max_distance_reached = 0.0
    current_driver_tag = f"{BASE_DRIVER_NAME}_S{session_counter}"
    last_session_uid = None
    
    # Mémoire
    last_wears = [0, 0, 0, 0]
    last_lap_time_recorded = 0
    
    # --- MEMOIRE DES SECTEURS (Solution anti-zéros) ---
    held_s1 = 0.0
    held_s2 = 0.0
    
    # Flags pour éviter les doublons
    has_sent_s1 = False
    has_sent_s2 = False

    print(f"📡 En attente des données sur le port {UDP_PORT}...")

    while True:
        try:
            packet = listener.get()
            pid = packet.header.packet_id
            player_index = packet.header.player_car_index

            # --- 1. GESTION SESSION ---
            if packet.header.session_uid != last_session_uid and last_session_uid is not None:
                session_counter += 1
                current_driver_tag = f"{BASE_DRIVER_NAME}_S{session_counter}"
                max_distance_reached = 0.0
                last_lap_time_recorded = 0
                has_sent_s1 = False
                has_sent_s2 = False
                held_s1, held_s2 = 0.0, 0.0
                print(f"🔄 Nouvelle Session -> {current_driver_tag}")
            last_session_uid = packet.header.session_uid

            # --- 2. GPS (Packet 0) ---
            if pid == 0:
                motion = packet.car_motion_data[player_index]
                payload = {
                    "pos_x": float(motion.world_position_x),
                    "pos_y": float(motion.world_position_z),
                    "driver_name": current_driver_tag
                }
                client.publish(MQTT_TOPIC, json.dumps(payload))

            # --- 3. LIVE TIMING & LAP DATA (Packet 2) ---
            elif pid == 2:
                lap_data = packet.lap_data[player_index]
                dist = float(lap_data.total_distance)
                
                # Gestion Flashback/Restart
                if max_distance_reached > 300 and dist < 100:
                    session_counter += 1
                    current_driver_tag = f"{BASE_DRIVER_NAME}_S{session_counter}"
                    max_distance_reached = 0.0
                    last_lap_time_recorded = 0
                    has_sent_s1 = False
                    has_sent_s2 = False
                    held_s1, held_s2 = 0.0, 0.0
                elif dist > max_distance_reached:
                    max_distance_reached = dist

                # Données actuelles
                current_lap = int(lap_data.current_lap_num)
                s1_ms = lap_data.sector_1_time_in_ms
                s2_ms = lap_data.sector_2_time_in_ms

                # --- A. ENVOI INSTANTANÉ SECTEUR 1 ---
                if s1_ms > 0 and not has_sent_s1:
                    held_s1 = float(s1_ms / 1000.0) # On mémorise
                    print(f"⏱️ Secteur 1 Bouclé : {held_s1}s")
                    payload = {
                        "sector_1": held_s1,
                        "lap_number": current_lap,
                        "driver_name": current_driver_tag
                    }
                    client.publish(MQTT_TOPIC, json.dumps(payload))
                    has_sent_s1 = True

                # --- B. ENVOI INSTANTANÉ SECTEUR 2 ---
                if s2_ms > 0 and not has_sent_s2:
                    held_s2 = float(s2_ms / 1000.0) # On mémorise
                    print(f"⏱️ Secteur 2 Bouclé : {held_s2}s")
                    payload = {
                        "sector_2": held_s2,
                        "lap_number": current_lap,
                        "driver_name": current_driver_tag
                    }
                    client.publish(MQTT_TOPIC, json.dumps(payload))
                    has_sent_s2 = True

                # --- C. FIN DE TOUR ---
                current_last_lap_ms = lap_data.last_lap_time_in_ms
                
                # On détecte que le temps du dernier tour a changé
                if current_last_lap_ms != last_lap_time_recorded and current_last_lap_ms > 0:
                    lap_time_sec = current_last_lap_ms / 1000.0
                    finished_lap = current_lap - 1 
                    
                    # --- FILTRE ANTI TOUR 0 ---
                    # On n'envoie les données que si c'est un vrai tour (>= 1)
                    if finished_lap >= 1:
                        # On calcule S3 avec les valeurs mémorisées
                        s3_sec = lap_time_sec - held_s1 - held_s2
                        if s3_sec < 0: s3_sec = 0.0 # Sécurité si le calcul foire

                        print(f"🏁 Tour {finished_lap} FINI : {lap_time_sec}s")
                        
                        payload = {
                            "lap_time": lap_time_sec,
                            "sector_1": held_s1, # On renvoie les valeurs mémorisées
                            "sector_2": held_s2,
                            "sector_3": s3_sec,
                            "lap_number": finished_lap,
                            "driver_name": current_driver_tag
                        }
                        client.publish(MQTT_TOPIC, json.dumps(payload))
                    
                    # Mise à jour mémoire système
                    last_lap_time_recorded = current_last_lap_ms
                    
                    # RESET pour le prochain tour
                    has_sent_s1 = False
                    has_sent_s2 = False
                    held_s1 = 0.0
                    held_s2 = 0.0

            # --- 4. TÉLÉMÉTRIE (Packet 6) ---
            elif pid == 6:
                car = packet.car_telemetry_data[player_index]
                if car.speed > 5 and max_distance_reached > 0:
                    payload = {
                        "speed": float(car.speed),
                        "rpm": float(car.engine_rpm),
                        "throttle": float(car.throttle),
                        "brake": float(car.brake),
                        "gear": int(car.gear),
                        "drs": int(car.drs),
                        "total_distance": max_distance_reached,
                        "driver_name": current_driver_tag
                    }
                    client.publish(MQTT_TOPIC, json.dumps(payload))

            # --- 5. ERS (Packet 7) ---
            elif pid == 7:
                status = packet.car_status_data[player_index]
                if max_distance_reached > 0:
                    try: ers = (float(status.ers_store_energy)/4000000)*100
                    except: ers = 0.0
                    
                    payload = {
                        "ers_percent": ers,
                        "fuel": float(status.fuel_in_tank),
                        "total_distance": max_distance_reached,
                        "driver_name": current_driver_tag
                    }
                    client.publish(MQTT_TOPIC, json.dumps(payload))

            # --- 6. USURE (Packet 10) ---
            elif pid == 10:
                dmg = packet.car_damage_data[player_index]
                if max_distance_reached > 0:
                    try:
                        w_rl = float(dmg.tyres_wear[0])
                        w_rr = float(dmg.tyres_wear[1])
                        w_fl = float(dmg.tyres_wear[2])
                        w_fr = float(dmg.tyres_wear[3])
                        current_wears = [w_rl, w_rr, w_fl, w_fr]
                    except:
                        current_wears = [0.0, 0.0, 0.0, 0.0]
                    
                    if current_wears != last_wears:
                        payload = {
                            "wear_rl": w_rl, "wear_rr": w_rr,
                            "wear_fl": w_fl, "wear_fr": w_fr,
                            "total_distance": max_distance_reached,
                            "driver_name": current_driver_tag
                        }
                        client.publish(MQTT_TOPIC, json.dumps(payload))
                        last_wears = current_wears

        except Exception:
            pass

if __name__ == "__main__":
    main()