import sys
import asyncio
import aiomqtt
import json
import os
import time


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
    # Senza questa riconfigurazione un'emoji nei print sotto termina il processo
    # quando la console non e' UTF-8 (per esempio con l'output rediretto su file).
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

TOPIC_SENSORI = "cantiere/sensori/#"
TOPIC_DRONE = "cantiere/sensori/drone"
TOPIC_ALLARMI = "cantiere/allarmi"

# Un allarme uguale non si ripete prima di questo tempo: il drone pubblica ogni
# 0,5 s, e senza la pausa l'orologio vibrerebbe senza interruzione (ogni notifica
# dura 4 s sul firmware) fino a non essere piu' creduto.
PAUSA_ALLARME_SEC = 10.0
RIPROVA_BROKER_SEC = 5.0

_ultimo_allarme: dict[str, float] = {}


async def emetti_allarme(client, codice, msg, tipo, livello="warning"):
    adesso = time.monotonic()
    precedente = _ultimo_allarme.get(codice)
    if precedente is not None and (adesso - precedente) < PAUSA_ALLARME_SEC:
        return
    _ultimo_allarme[codice] = adesso

    alert = {"msg": msg, "type": tipo, "level": livello, "source": "server_cps"}
    await client.publish(TOPIC_ALLARMI, payload=json.dumps(alert), qos=1)


async def process_logic(client, topic, data):
    # Logica Drone: Pericolo se vede una persona vicino
    # Il confronto e' insensibile alle maiuscole: il modello Caduta_delle_Persone
    # emette "Person", mentre i simulatori scrivevano "person" - con l'uguaglianza
    # esatta la regola scattava solo in simulazione e mai in volo.
    # Il topic si confronta per intero: "drone" come sottostringa avrebbe preso
    # anche un ipotetico operaio che si chiama "drone".
    if topic == TOPIC_DRONE:
        rilevazioni = data.get("detections")
        if isinstance(rilevazioni, list):
            persona = any(
                isinstance(d, dict) and str(d.get("label", "")).casefold() == "person"
                for d in rilevazioni
            )
            if persona:
                print("⚠️ Drone rileva persona nell'area di scavo!")
                await emetti_allarme(
                    client,
                    "PERSONA_AREA",
                    "PERSONA IN AREA PERICOLOSA",
                    "VISUAL",
                    "critical",
                )

    # Logica Orologio: Battito anomalo
    # L'orologio manda "bpm" (non "heart_rate"), e lo manda null quando il dito
    # non e' sul sensore: senza il controllo, il confronto con 120 solleverebbe
    # TypeError e fermerebbe il server.
    # Il segmento del topic si isola, invece di cercare "orologio" dentro tutta
    # la stringa, cosi' l'id dell'operaio non puo' cambiare il ramo scelto.
    segmenti = topic.split("/")
    if len(segmenti) >= 4 and segmenti[2] == "orologio":
        operaio = segmenti[3]
        bpm = data.get("bpm")
        valida = data.get("lettura_valida", True)
        if valida and isinstance(bpm, (int, float)) and not isinstance(bpm, bool):
            if bpm > 120:
                print(f"🚨 ALLERTA MEDICA: Battito alto ({bpm} bpm)")
                await emetti_allarme(
                    client,
                    f"BATTITO_{operaio}",
                    f"BATTITO ALTO ({int(bpm)} bpm)",
                    "MEDICAL",
                    "critical",
                )


async def ascolta():
    async with aiomqtt.Client(BROKER, port=PORTA) as client:
        print(f"✅ Server CPS in ascolto su {BROKER}:{PORTA}...")
        await client.subscribe(TOPIC_SENSORI)
        async for message in client.messages:
            # Un messaggio malformato non deve fermare il server: prima di questo
            # try un JSON non valido (o un payload che non e' un oggetto) usciva da
            # async for e chiudeva il processo, cioe' spegneva la sicurezza in
            # silenzio mentre il drone continuava a volare.
            topic = str(message.topic)
            try:
                payload = json.loads(message.payload.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                print(f"[ERR] payload non leggibile su {topic}: {exc}")
                continue
            if not isinstance(payload, dict):
                print(f"[ERR] payload non e' un oggetto JSON su {topic}: ignorato")
                continue
            try:
                await process_logic(client, topic, payload)
            except Exception as exc:
                print(f"[ERR] errore nell'elaborare {topic}: {type(exc).__name__}: {exc}")


async def main():
    # Anello di riconnessione: aiomqtt solleva MqttError a ogni caduta della
    # connessione. Senza questo anello un riavvio di Mosquitto o un calo del
    # Wi-Fi spegneva il server per sempre.
    while True:
        try:
            await ascolta()
        except aiomqtt.MqttError as exc:
            print(f"⚠️ Connessione al broker persa ({exc}): riprovo fra {RIPROVA_BROKER_SEC:.0f} s.")
            await asyncio.sleep(RIPROVA_BROKER_SEC)


if __name__ == "__main__":
    ensure_utf8_console()
    try:
        avvia(main())
    except KeyboardInterrupt:
        print("\nChiusura del server CPS.")
