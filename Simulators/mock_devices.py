import sys
import asyncio
import aiomqtt
import json
import random

# --- FIX PER WINDOWS ---
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
# -----------------------

async def simulate_drone(client):
    while True:
        data = {
            "battery": random.randint(20, 100),
            "is_flying": True,
            "position": {"x": 1.2, "y": 0.5, "z": 1.8, "yaw": 90.0},
            "detections": [{"label": "person", "conf": 0.89}]
        }
        await client.publish("cantiere/sensori/drone", payload=json.dumps(data))
        await asyncio.sleep(2)

async def simulate_watch(client):
    # Stessa forma che manda l'orologio vero (wearable/smartwatch.ino), altrimenti
    # il simulatore proverebbe un contratto che nella realta' non esiste.
    while True:
        estrazione = random.random()
        if estrazione < 0.15:
            # Battito alto: deve far scattare l'allerta medica sul server
            data = {"bpm": random.randint(121, 145), "spo2": random.randint(90, 96),
                    "stato": "ALLARME", "lettura_valida": True}
        elif estrazione < 0.20:
            # Dito non sul sensore: bpm null, il server non deve allarmare
            data = {"bpm": None, "spo2": None,
                    "stato": "GUASTO", "lettura_valida": False}
        else:
            data = {"bpm": random.randint(60, 100), "spo2": random.randint(95, 100),
                    "stato": "NORMALE", "lettura_valida": True}
        await client.publish("cantiere/sensori/orologio/operaio_1", payload=json.dumps(data))
        await asyncio.sleep(3)

async def main():
    async with aiomqtt.Client("localhost") as client:
        print("🚀 Simulatori avviati (CTRL+C per fermare)")
        await asyncio.gather(simulate_drone(client), simulate_watch(client))

if __name__ == "__main__":
    asyncio.run(main())