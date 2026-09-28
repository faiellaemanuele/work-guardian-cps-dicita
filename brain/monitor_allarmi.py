"""Mostra in chiaro gli allarmi che passano su cantiere/allarmi.

Uso (dalla radice del progetto, mentre il drone vola):
    python Brain/monitor_allarmi.py
Con --tutto mostra anche lo stato online/offline e i messaggi dell'orologio.
"""
import json
import os
import sys
import time

import paho.mqtt.client as mqtt

BROKER = os.environ.get("WG_MQTT_BROKER", "127.0.0.1")
PORTA = int(os.environ.get("WG_MQTT_PORT", "1883"))
TOPIC_ALLARMI = "cantiere/allarmi"
TUTTO = "--tutto" in sys.argv

MITTENTI = {"drone": "DRONE", "server_cps": "SERVER"}
LIVELLI = {"critical": "CRITICO", "warning": "AVVISO", "info": "INFO"}
# Cosa fa l'orologio vero con il campo "tipo" (onMqttMessage nel firmware).
AZIONE_OROLOGIO = {
    "DPI_MANCANTE": "orologio: vibra e mostra l'allarme",
    "DPC_MANCANTE": "orologio: vibra e mostra l'allarme",
    "DPI_OK": "orologio: spegne l'allarme DPI (silenzioso)",
    "DPC_OK": "orologio: spegne l'allarme DPC (silenzioso)",
    "RISOLTO": "orologio: spegne gli allarmi DPI/DPC (silenzioso)",
}


def ora():
    return time.strftime("%H:%M:%S")


def mostra_allarme(testo):
    try:
        allarme = json.loads(testo)
    except ValueError:
        print(f"{ora()}  [ERR] allarme non leggibile: {testo}")
        return
    if not isinstance(allarme, dict):
        print(f"{ora()}  [ERR] allarme non e' un oggetto JSON: {testo}")
        return

    mittente = MITTENTI.get(allarme.get("source"), str(allarme.get("source")))
    livello = LIVELLI.get(allarme.get("level"), str(allarme.get("level")))
    riga = f"{ora()}  {mittente:<6}  {livello:<7}  {allarme.get('msg')}"
    if allarme.get("target"):
        riga += f"  -> {allarme['target']}"
    print(riga)
    azione = AZIONE_OROLOGIO.get(allarme.get("tipo"))
    if azione:
        print(f"{'':>10}{azione}")


def on_connect(client, _userdata, _flags, reason_code, _properties=None):
    if reason_code != 0:
        print(f"Connessione al broker rifiutata: {reason_code}")
        return
    client.subscribe("cantiere/#" if TUTTO else TOPIC_ALLARMI, qos=1)
    print(f"In ascolto degli allarmi su {BROKER}:{PORTA} (Ctrl+C per uscire)\n")


def on_message(_client, _userdata, message):
    testo = message.payload.decode("utf-8", errors="replace")
    if message.topic == TOPIC_ALLARMI:
        mostra_allarme(testo)
    elif message.topic.startswith("cantiere/sistema/"):
        print(f"{ora()}  STATO   {message.topic.split('/')[2]}: {testo}")
    elif message.topic.startswith("cantiere/sensori/orologio/"):
        print(f"{ora()}  OROLOGIO  {testo}")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    except (AttributeError, TypeError):
        client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(BROKER, PORTA, 30)
    except OSError as exc:
        print(f"Broker {BROKER}:{PORTA} non raggiungibile: {exc}. Mosquitto e' avviato?")
        return
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nChiusura del monitor.")


if __name__ == "__main__":
    main()
