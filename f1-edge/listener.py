import os
import json
import time
import threading
import pyttsx3
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from f1_23_telemetry.listener import TelemetryListener

# --- CONFIGURATION ---
UDP_PORT = int(os.getenv("UDP_PORT", 20777))
BASE_DRIVER_NAME = os.getenv("DRIVER_NAME", "Unknown")
MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_TOPIC = "f1/telemetry"

# --- MOTEUR VOCAL ---
def speak_worker(text):
    try:
        engine = pyttsx3.init()
        engine.setProperty('rate', 175) 
        engine.setProperty('volume', 1.0)
        engine.say(text)
        engine.runAndWait()
    except: pass

def speak(text):
    print(f"🗣️ COACH: {text}")
    t = threading.Thread(target=speak_worker, args=(text,))
    t.start()

# --- MQTT ---
client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id=f"Edge_{UDP_PORT}")
try:
    client.connect(MQTT_BROKER, 1883, 60)
    client.loop_start()
    print(f"✅ COACH DIRECTIONNEL ACTIVÉ : {BASE_DRIVER_NAME}")
except Exception as e:
    print(f"❌ Erreur MQTT : {e}")

def main():
    listener = TelemetryListener(port=UDP_PORT, host="0.0.0.0")
    
    # Session
    session_counter = 1
    max_distance_reached = 0.0
    current_driver_tag = f"{BASE_DRIVER_NAME}_S{session_counter}"
    last_session_uid = None
    
    # Mémoire Télémétrie
    last_wears = [0.0]*4
    held_s1, held_s2 = 0.0, 0.0
    has_sent_s1, has_sent_s2 = False, False
    best_s1, best_s2 = None, None
    last_lap_time_recorded = 0
    current_speed_ms = 0.0
    
    # --- MÉMOIRE ESPIONNAGE ---
    grid_positions = {}         
    target_rival_idx = -1       # Index de la voiture ciblée
    target_rival_dir = ""       # "Devant" ou "Derrière"
    last_rival_ers_mode = -1    

    speak("Radar directionnel activé. Seuil de 5 secondes.")

    while True:
        try:
            packet = listener.get()
            pid = packet.header.packet_id
            player_index = packet.header.player_car_index

            # 1. SESSION
            if packet.header.session_uid != last_session_uid and last_session_uid is not None:
                session_counter += 1
                current_driver_tag = f"{BASE_DRIVER_NAME}_S{session_counter}"
                max_distance_reached = 0.0
                last_lap_time_recorded = 0
                held_s1, held_s2 = 0.0, 0.0
                has_sent_s1, has_sent_s2 = False, False
                best_s1, best_s2 = None, None
                target_rival_idx = -1
                target_rival_dir = ""
                speak("Nouvelle session.")
            last_session_uid = packet.header.session_uid

            # 2. LAP DATA (Positions & Cible)
            if pid == 2:
                all_laps = packet.lap_data
                
                # A. Grille
                grid_positions = {}
                for idx, car_data in enumerate(all_laps):
                    if car_data.car_position > 0:
                        grid_positions[car_data.car_position] = idx
                
                # B. Données Joueur
                lap_data = all_laps[player_index]
                current_lap = int(lap_data.current_lap_num)
                my_dist = float(lap_data.total_distance)
                my_pos = lap_data.car_position
                
                if max_distance_reached > 300 and my_dist < 100: 
                    max_distance_reached = 0.0; held_s1=0.0; held_s2=0.0; has_sent_s1=False; has_sent_s2=False
                elif my_dist > max_distance_reached:
                    max_distance_reached = my_dist

                # --- C. DÉSIGNATION DE LA CIBLE + DIRECTION ---
                if current_speed_ms > 10: 
                    closest_idx = -1
                    closest_dir = ""
                    min_gap_sec = 999.0
                    
                    # 1. Check DEVANT (P-1)
                    if my_pos > 1:
                        idx_front = grid_positions.get(my_pos - 1)
                        if idx_front is not None:
                            gap = abs(float(all_laps[idx_front].total_distance) - my_dist)
                            sec = gap / current_speed_ms
                            if sec < min_gap_sec:
                                min_gap_sec = sec
                                closest_idx = idx_front
                                closest_dir = "Devant"

                    # 2. Check DERRIÈRE (P+1)
                    if my_pos < 20:
                        idx_back = grid_positions.get(my_pos + 1)
                        if idx_back is not None:
                            gap = abs(float(all_laps[idx_back].total_distance) - my_dist)
                            sec = gap / current_speed_ms
                            # Si celui de derrière est encore plus près que celui de devant
                            if sec < min_gap_sec:
                                min_gap_sec = sec
                                closest_idx = idx_back
                                closest_dir = "Derrière"
                    
                    # 3. Validation (Seuil 5s)
                    if min_gap_sec < 5.0 and closest_idx != -1:
                        if closest_idx != target_rival_idx:
                            target_rival_idx = closest_idx
                            target_rival_dir = closest_dir # On mémorise la direction
                            last_rival_ers_mode = -1 
                        # Mise à jour continue de la direction (au cas où on double)
                        target_rival_dir = closest_dir 
                    else:
                        target_rival_idx = -1
                        target_rival_dir = ""
                
                # Chronos MQTT
                s1, s2 = lap_data.sector_1_time_in_ms, lap_data.sector_2_time_in_ms
                if s1 > 0 and not has_sent_s1:
                    held_s1 = s1/1000.0
                    client.publish(MQTT_TOPIC, json.dumps({"sector_1": held_s1, "lap_number": current_lap, "driver_name": current_driver_tag}))
                    has_sent_s1 = True
                if s2 > 0 and not has_sent_s2:
                    held_s2 = s2/1000.0
                    client.publish(MQTT_TOPIC, json.dumps({"sector_2": held_s2, "lap_number": current_lap, "driver_name": current_driver_tag}))
                    has_sent_s2 = True
                
                last_lap_ms = lap_data.last_lap_time_in_ms
                if last_lap_ms != last_lap_time_recorded and last_lap_ms > 0:
                    lap_sec = last_lap_ms/1000.0
                    finished = current_lap - 1
                    if finished >= 1:
                        s3 = lap_sec - held_s1 - held_s2
                        if s3 < 0: s3 = 0.0
                        speak(f"Tour {finished} bouclé.")
                        client.publish(MQTT_TOPIC, json.dumps({"lap_time": lap_sec, "sector_3": s3, "sector_1": held_s1, "sector_2": held_s2, "lap_number": finished, "driver_name": current_driver_tag}))
                    last_lap_time_recorded = last_lap_ms
                    has_sent_s1, has_sent_s2 = False, False; held_s1, held_s2 = 0.0, 0.0

            # 3. TÉLÉMÉTRIE (Vitesse)
            elif pid == 6:
                car = packet.car_telemetry_data[player_index]
                current_speed_ms = float(car.speed) / 3.6
                if max_distance_reached > 0:
                    client.publish(MQTT_TOPIC, json.dumps({
                        "speed": float(car.speed), 
                        "throttle": float(car.throttle), "brake": float(car.brake),
                        "gear": int(car.gear), "drs": int(car.drs),
                        "total_distance": max_distance_reached, "driver_name": current_driver_tag
                    }))

            # 4. STATUS & ESPIONNAGE CIBLÉ
            elif pid == 7:
                all_status = packet.car_status_data
                status = all_status[player_index]
                ers_pc = (float(status.ers_store_energy)/4000000)*100
                ers_mode = int(status.ers_deploy_mode) 

                # Surveillance CIBLE
                if target_rival_idx != -1:
                    rival_status = all_status[target_rival_idx]
                    rival_mode = int(rival_status.ers_deploy_mode)
                    
                    if rival_mode != last_rival_ers_mode:
                        if last_rival_ers_mode != -1:
                            mode_names = {0: "Recharge", 1: "Neutre", 2: "Chrono", 3: "Dépassement"}
                            mode_text = mode_names.get(rival_mode, str(rival_mode))
                            
                            # C'EST ICI QUE ÇA PARLE : "DEVANT : MODE..."
                            speak(f"{target_rival_dir} : Mode {mode_text}")
                        
                        last_rival_ers_mode = rival_mode

                client.publish(MQTT_TOPIC, json.dumps({
                    "ers_percent": ers_pc, "ers_mode": ers_mode,
                    "fuel": float(status.fuel_in_tank), 
                    "total_distance": max_distance_reached, "driver_name": current_driver_tag
                }))

            # 5. DAMAGE
            elif pid == 10:
                dmg = packet.car_damage_data[player_index]
                wears = dmg.tyres_wear
                current_wears = [float(w) for w in wears]
                if current_wears != last_wears:
                    client.publish(MQTT_TOPIC, json.dumps({
                        "wear_rl": current_wears[0], "wear_rr": current_wears[1],
                        "wear_fl": current_wears[2], "wear_fr": current_wears[3],
                        "total_distance": max_distance_reached, "driver_name": current_driver_tag
                    }))
                    last_wears = current_wears

        except Exception:
            pass

if __name__ == "__main__":
    main()