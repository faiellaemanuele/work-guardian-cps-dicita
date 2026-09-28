import os
import shutil
import subprocess
import sys
import time

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from drone.flight.flight_loop import main

SERVER_SCRIPT = os.path.join(RADICE, "Brain", "server_cps.py")
# Il server scrive su file e non sulla console: la dashboard del drone occupa
# il terminale, e le righe [MSG] ogni 0,5 s la coprirebbero. A volo finito il
# registro viene spostato nella cartella della sessione, insieme ai dati di
# volo: durante il volo la cartella non esiste ancora (la crea il postflight).
SESSIONI_DIR = os.path.join(RADICE, "drone", "flight_sessions")
SERVER_LOG = os.path.join(SESSIONI_DIR, "server_cps.log")
PREFISSO_SESSIONE = "sessione_volo_"
SERVER_AVVIO_SEC = 2.0


def avvia_server():
    # WG_AVVIA_SERVER=0 per chi avvia il server a mano in un altro terminale:
    # due server attivi pubblicherebbero ogni allarme due volte.
    if os.environ.get("WG_AVVIA_SERVER", "1") == "0":
        return None, None

    os.makedirs(os.path.dirname(SERVER_LOG), exist_ok=True)
    log = open(SERVER_LOG, "w", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    processo = subprocess.Popen(
        [sys.executable, "-u", SERVER_SCRIPT],
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
    )
    # Un errore all'avvio (per esempio aiomqtt non installato) chiude il server
    # subito: senza questo controllo il drone volerebbe senza allarmi medici.
    time.sleep(SERVER_AVVIO_SEC)
    if processo.poll() is not None:
        log.close()
        print(
            f"ATTENZIONE: il server CPS si e' chiuso all'avvio (codice {processo.returncode}). "
            f"Il volo prosegue senza allarmi del server. Dettagli in {SERVER_LOG}"
        )
        return None, None

    print(f"Server CPS avviato (registro in {SERVER_LOG})")
    return processo, log


def ferma_server(processo, log):
    if processo is None:
        return
    processo.terminate()
    try:
        processo.wait(timeout=5)
    except subprocess.TimeoutExpired:
        processo.kill()
    log.close()


def sessione_di_questo_volo(avviato_a):
    # La cartella la crea il postflight a fine volo, e solo se c'e' qualcosa da
    # salvare: la piu' recente creata dopo l'avvio e' quella di questo volo.
    try:
        cartelle = [
            os.path.join(SESSIONI_DIR, nome)
            for nome in os.listdir(SESSIONI_DIR)
            if nome.startswith(PREFISSO_SESSIONE)
        ]
    except OSError:
        return None
    di_questo_volo = [
        c for c in cartelle if os.path.isdir(c) and os.path.getmtime(c) >= avviato_a
    ]
    if not di_questo_volo:
        return None
    return max(di_questo_volo, key=os.path.getmtime)


def archivia_log_del_server(avviato_a):
    # Va chiamata a server gia' fermo: finche' il processo tiene il file aperto,
    # Windows non lo lascia spostare.
    if not os.path.isfile(SERVER_LOG) or os.path.getmtime(SERVER_LOG) < avviato_a:
        return  # nessun registro di questo volo (server non avviato o gia' archiviato)

    sessione = sessione_di_questo_volo(avviato_a)
    if sessione is None:
        print(
            "Il volo non ha prodotto una cartella di sessione: il registro del server "
            f"resta in {SERVER_LOG}"
        )
        return
    try:
        shutil.move(SERVER_LOG, os.path.join(sessione, "server_cps.log"))
    except OSError as errore:
        print(f"Il registro del server non e' stato spostato nella sessione: {errore}")
    else:
        print(f"Registro del server CPS salvato in {os.path.basename(sessione)}")


if __name__ == "__main__":
    avviato_a = time.time()
    server, server_log = avvia_server()
    try:
        main()
    finally:
        ferma_server(server, server_log)
        archivia_log_del_server(avviato_a)
