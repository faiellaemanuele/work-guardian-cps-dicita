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


BROKER = os.environ.get("WG_MQTT_BROKER", "127.0.0.1")
PORTA = int(os.environ.get("WG_MQTT_PORT", "1883"))

TOPIC_SENSORI = "cantiere/sensori/#"
TOPIC_DRONE = "cantiere/sensori/drone"
TOPIC_ALLARMI = "cantiere/allarmi"

# Un allarme uguale non si ripete prima di questo tempo: il drone pubblica ogni
# 0,5 s, e senza la pausa l'orologio vibrerebbe senza interruzione (ogni notifica
# dura 4 s sul firmware) fino a non essere piu' creduto.
PAUSA_ALLARME_SEC = 10.0
RIPROVA_BROKER_SEC = 5.0

# Soglie biometriche, identiche a quelle del firmware dell'orologio
# (BPM_MAX_IN, BPM_MIN_IN, SPO2_MIN_IN): se cambiano li', vanno cambiate qui.
BPM_MAX = 120
BPM_MIN = 50
SPO2_MIN = 92

_ultimo_allarme: dict[str, float] = {}


async def emetti_allarme(client, codice, msg, tipo, livello="warning", target="operaio_1"):
    adesso = time.monotonic()
    precedente = _ultimo_allarme.get(codice)
    if precedente is not None and (adesso - precedente) < PAUSA_ALLARME_SEC:
        return

    alert = {"msg": msg, "type": tipo, "level": livello, "source": "server_cps", "target": target}
    # La pausa si segna DOPO la pubblicazione riuscita: segnandola prima, un allarme
    # perso per un errore del broker restava zittito altri PAUSA_ALLARME_SEC, cioe'
    # proprio mentre il pericolo era in corso.
    await client.publish(TOPIC_ALLARMI, payload=json.dumps(alert), qos=1)
    _ultimo_allarme[codice] = adesso


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
            pericolo = None
            for d in rilevazioni:
                if isinstance(d, dict):
                    label = str(d.get("label", "")).casefold()
                    if label in ["person", "fall"]:
                        pericolo = label.upper()
                        break
            
            if pericolo:
                print(f"⚠️ Drone rileva {pericolo} nell'area di scavo!")
                await emetti_allarme(
                    client,
                    f"DRONE_{pericolo}",
                    f"PERICOLO: {pericolo}",
                    "VISUAL",
                    "critical",
                    target="operaio_1"
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
        spo2 = data.get("spo2")
        valida = data.get("lettura_valida", True)
        # Soglie uguali a BPM_MAX_IN e BPM_MIN_IN del firmware: l'orologio
        # suona da solo, qui l'allarme serve a chi sorveglia dal PC.
        if valida and isinstance(bpm, (int, float)) and not isinstance(bpm, bool):
            if bpm > BPM_MAX:
                print(f"🚨 ALLERTA MEDICA: Battito alto ({bpm} bpm)")
                await emetti_allarme(
                    client,
                    f"BATTITO_ALTO_{operaio}",
                    f"BATTITO ALTO ({int(bpm)} bpm)",
                    "MEDICAL",
                    "critical",
                    target=operaio
                )
            # Il battito basso ha una chiave sua: con una sola chiave la pausa
            # di 10 s di un allarme zittirebbe l'altro.
            elif 0 < bpm < BPM_MIN:
                print(f"🚨 ALLERTA MEDICA: Battito basso ({bpm} bpm)")
                await emetti_allarme(
                    client,
                    f"BATTITO_BASSO_{operaio}",
                    f"BATTITO BASSO ({int(bpm)} bpm)",
                    "MEDICAL",
                    "critical",
                    target=operaio
                )
        # Lo 0 e' "nessuna lettura", non una saturazione bassissima.
        if valida and isinstance(spo2, (int, float)) and not isinstance(spo2, bool):
            if 0 < spo2 < SPO2_MIN:
                print(f"🚨 ALLERTA MEDICA: Saturazione bassa ({spo2}%)")
                await emetti_allarme(
                    client,
                    f"SPO2_{operaio}",
                    f"SATURAZIONE BASSA ({int(spo2)}%)",
                    "MEDICAL",
                    "critical",
                    target=operaio
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
            print(f"[MSG] {topic}: {payload}")
            try:
                await process_logic(client, topic, payload)
            except aiomqtt.MqttError:
                # La connessione e' caduta mentre si pubblicava un allarme: non si
                # ingoia, si lascia salire all'anello di riconnessione di main().
                raise
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