import sys
import asyncio
import aiomqtt
import json

# --- FIX PER WINDOWS ---
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
# -----------------------

async def process_logic(client, topic, data):
    # Logica Drone: Pericolo se vede una persona vicino
    if "drone" in topic:
        if any(d.get("label") == "person" for d in data.get("detections", [])):
            print("⚠️ Drone rileva persona nell'area di scavo!")
            alert = {"msg": "PERSONA IN AREA PERICOLOSA", "type": "VISUAL"}
            await client.publish("cantiere/allarmi", payload=json.dumps(alert))

    # Logica Orologio: Battito anomalo
    # L'orologio manda "bpm" (non "heart_rate"), e lo manda null quando il dito
    # non e' sul sensore: senza il controllo, il confronto con 120 solleverebbe
    # TypeError e fermerebbe il server.
    if "orologio" in topic:
        bpm = data.get("bpm")
        valida = data.get("lettura_valida", True)
        if valida and isinstance(bpm, (int, float)):
            if bpm > 120:
                print(f"🚨 ALLERTA MEDICA: Battito alto ({bpm} bpm)")

async def main():
    async with aiomqtt.Client("localhost") as client:
        print("✅ Server CPS in ascolto...")
        await client.subscribe("cantiere/sensori/#")
        async for message in client.messages:
            payload = json.loads(message.payload.decode())
            await process_logic(client, str(message.topic), payload)

if __name__ == "__main__":
    asyncio.run(main())