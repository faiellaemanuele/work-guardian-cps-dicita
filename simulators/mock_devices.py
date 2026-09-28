import sys
import asyncio
import aiomqtt
import json
import os
import random


def avvia(coro):
    # aiomqtt (paho) usa add_reader/add_writer, che il loop Proactor di Windows
    # non ha: serve un SelectorEventLoop. Dalla 3.12 lo si passa ad asyncio.run,
    # perche' la policy e' deprecata dalla 3.14 e sparisce nella 3.16.
    if sys.version_info >= (3, 12):
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(coro)


def ensure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        riconfigura = getattr(stream, "reconfigure", None)
        if riconfigura is None:
            continue
        try:
            riconfigura(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


BROKER = os.environ.get("WG_MQTT_BROKER", "localhost")
PORTA = int(os.environ.get("WG_MQTT_PORT", "1883"))

async def simulate_drone(client):
    while True:
        data = {
            "battery": random.randint(20, 100),
            "is_flying": True,
            "position": {"x": 1.2, "y": 0.5, "z": 1.8, "yaw": 90.0},
            "detections": [{"label": "Person", "conf": 0.89}]
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
    async with aiomqtt.Client(BROKER, port=PORTA) as client:
        print(f"🚀 Simulatori avviati su {BROKER}:{PORTA} (CTRL+C per fermare)")
        await asyncio.gather(simulate_drone(client), simulate_watch(client))

if __name__ == "__main__":
    ensure_utf8_console()
    try:
        avvia(main())
    except KeyboardInterrupt:
        print("\nChiusura dei simulatori.")