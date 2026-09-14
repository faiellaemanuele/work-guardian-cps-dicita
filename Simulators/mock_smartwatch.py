import sys
import asyncio
import aiomqtt
import json
import os


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

OPERAIO_ID = sys.argv[1] if len(sys.argv) > 1 else "operaio_1"


def mostra(payload):
    # Un allarme senza "target" e' per tutti, come nel firmware vero
    # (allarmePerMe in smartwatch.ino): altrimenti si mostra solo il proprio.
    target = payload.get("target")
    if target is not None and target != OPERAIO_ID:
        return

    bordo = "🔴" if payload.get("level") == "critical" else "🟠"
    print("\n" + bordo * 20)
    print("📳 [BZZZ BZZZ! Motore in vibrazione]")
    print(f"🚨 DISPLAY LCD: {payload.get('msg')}")
    print(bordo * 20 + "\n")


async def main():
    async with aiomqtt.Client(BROKER, port=PORTA) as client:
        print(f"⌚ Smartwatch Virtuale '{OPERAIO_ID}' acceso e in ascolto...")

        await client.subscribe("cantiere/allarmi", qos=1)

        async for message in client.messages:
            try:
                payload = json.loads(message.payload.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                print(f"[ERR] allarme non leggibile: {exc}")
                continue
            if not isinstance(payload, dict):
                print("[ERR] allarme non e' un oggetto JSON: ignorato")
                continue
            mostra(payload)


if __name__ == "__main__":
    ensure_utf8_console()
    try:
        avvia(main())
    except KeyboardInterrupt:
        print("\nChiusura dell'orologio virtuale.")
