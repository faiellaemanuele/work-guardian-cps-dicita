import json
import platform
import re
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parents[2]
RUNS_DIR = SCRIPT_DIR / "models"
MODELS_DIR = SCRIPT_DIR.parents[1] / "models"
CATALOGO = MODELS_DIR / "catalog.json"
DATASETS_RELATIVI = "vision/training/trainer/datasets"
MODELLI_RELATIVI = "vision/models"
DA_COPIARE = (Path("weights") / "best.pt", Path("weights") / "last.pt",
              Path("results.csv"), Path("args.yaml"))
CHIAVI_COMANDO = ("data", "name", "project", "epochs", "patience",
                  "imgsz", "batch", "device", "plots", "close_mosaic")
ESTENSIONI_IMMAGINI = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")
METRICHE = ("metrics/precision(B)", "metrics/recall(B)",
            "metrics/mAP50(B)", "metrics/mAP50-95(B)")
AVVISO_OBSOLETA = ("ATTENZIONE: da qui in su questa scheda descrive l'addestramento "
                   "precedente, non i pesi ora in servizio. Rigenerala con --scheda.")


def breve(percorso):
    percorso = Path(percorso).resolve()
    try:
        return str(percorso.relative_to(BASE_DIR))
    except ValueError:
        return str(percorso)


def run_disponibili():
    if not RUNS_DIR.is_dir():
        return []
    return sorted(d.name for d in RUNS_DIR.iterdir() if (d / "weights" / "best.pt").is_file())


def modelli_disponibili():
    if not MODELS_DIR.is_dir():
        return []
    return sorted(d.name for d in MODELS_DIR.iterdir() if d.is_dir())


def terminatore(testo):
    return "\r\n" if "\r\n" in testo else "\n"


def nome_dataset(valore):
    parti = valore.strip().strip("'\"").replace("\\", "/").rstrip("/").split("/")
    if parti and parti[-1].endswith((".yaml", ".yml")):
        parti = parti[:-1]
    return parti[-1] if parti else ""


def valori_di(percorso):
    if not percorso.is_file():
        return {}
    testo = percorso.read_bytes().decode("utf-8")
    valori = {}
    for riga in testo.split(terminatore(testo)):
        chiave, separatore, valore = riga.partition(":")
        if separatore and chiave and not chiave.startswith(" "):
            valori[chiave] = valore.strip()
    return valori


def sistema_args(percorso, modello):
    testo = percorso.read_bytes().decode("utf-8")
    fine = terminatore(testo)
    righe = testo.split(fine)

    dataset = ""
    for riga in righe:
        if riga.startswith("data:"):
            dataset = nome_dataset(riga.split(":", 1)[1])

    pesi = f"{MODELLI_RELATIVI}/{modello}/weights/last.pt"
    nuove = []
    for riga in righe:
        chiave, _, valore = riga.partition(":")
        valore = valore.strip()
        if chiave == "data" and dataset:
            riga = f"data: {DATASETS_RELATIVI}/{dataset}/data.yaml"
        elif chiave == "project":
            riga = f"project: {MODELLI_RELATIVI}"
        elif chiave == "name":
            riga = f"name: {modello}"
        elif chiave == "save_dir":
            riga = f"save_dir: {MODELLI_RELATIVI}/{modello}"
        elif chiave in ("model", "resume") and valore.endswith(".pt") and ("/" in valore or "\\" in valore):
            riga = f"{chiave}: {pesi}"
        nuove.append(riga)

    percorso.write_bytes(fine.join(nuove).encode("utf-8"))


def decimali_necessari(valori):
    numeri = [float(v) for v in valori]
    for decimali in range(18):
        if all(float(f"{n:.{decimali}f}") == n for n in numeri):
            return decimali
    return None


def formatta_results(percorso):
    testo = percorso.read_bytes().decode("utf-8")
    fine = terminatore(testo)
    separatore = ";" if ";" in testo.split(fine)[0] else ","
    righe = [[c.strip() for c in r.split(separatore)] for r in testo.split(fine) if r.strip()]
    if len(righe) < 2:
        return False
    intestazione, dati = righe[0], righe[1:]
    if any(len(r) != len(intestazione) for r in dati):
        return False

    colonne = []
    for i in range(len(intestazione)):
        valori = [r[i].replace(",", ".") for r in dati]
        if all("." not in v and "e" not in v.lower() for v in valori):
            colonne.append(valori)
            continue
        try:
            decimali = decimali_necessari(valori)
        except ValueError:
            decimali = None
        colonne.append(valori if decimali is None
                       else [f"{float(v):.{decimali}f}".replace(".", ",") for v in valori])

    tabella = [intestazione]
    tabella += [[colonne[i][r] for i in range(len(intestazione))] for r in range(len(dati))]
    if any(";" in c for r in tabella for c in r):
        return False
    nuovo = fine.join(";".join(r) for r in tabella)
    percorso.write_bytes((nuovo + fine).encode("utf-8"))
    return True


def righe_results(percorso):
    if not percorso.is_file():
        return []
    testo = percorso.read_bytes().decode("utf-8")
    fine = terminatore(testo)
    separatore = ";" if ";" in testo.split(fine)[0] else ","
    righe = [[c.strip() for c in r.split(separatore)] for r in testo.split(fine) if r.strip()]
    if len(righe) < 2:
        return []
    intestazione = righe[0]
    dati = righe[1:]
    if separatore == ";":
        dati = [[c.replace(",", ".") for c in r] for r in dati]
    return [dict(zip(intestazione, r)) for r in dati if len(r) == len(intestazione)]


def epoca_migliore(righe, metriche_migliori):
    if not righe or not metriche_migliori:
        return None
    trovate = []
    for riga in righe:
        if all(chiave in riga and chiave in metriche_migliori
               and abs(float(riga[chiave]) - float(metriche_migliori[chiave])) < 1e-9
               for chiave in METRICHE):
            trovate.append(riga.get("epoch"))
    return trovate[0] if len(trovate) == 1 else None


def metadati_checkpoint(pesi):
    try:
        import torch
        checkpoint = torch.load(str(pesi), map_location="cpu", weights_only=False)
    except Exception:
        return {}
    return {"versione": checkpoint.get("version"),
            "data": checkpoint.get("date"),
            "metriche": checkpoint.get("train_metrics") or {}}


def numero_italiano(valore, decimali=0):
    testo = f"{valore:,.{decimali}f}"
    return testo.replace(",", "@").replace(".", ",").replace("@", ".")


def conta_immagini_val(dati):
    try:
        from ultralytics.data.utils import check_det_dataset
        risolto = check_det_dataset(str(dati))
    except Exception:
        return None
    voci = risolto.get("val")
    if voci is None:
        return None
    if not isinstance(voci, (list, tuple)):
        voci = [voci]
    totale = 0
    for voce in voci:
        percorso = Path(voce)
        if percorso.is_dir():
            totale += sum(1 for f in percorso.rglob("*")
                          if f.suffix.lower() in ESTENSIONI_IMMAGINI)
        elif percorso.is_file() and percorso.suffix.lower() == ".txt":
            testo = percorso.read_bytes().decode("utf-8")
            totale += len([r for r in testo.splitlines() if r.strip()])
    return totale or None


def esegui_validazione(pesi, dati, impostazioni):
    from ultralytics import YOLO
    opzioni = {"data": str(dati), "plots": False, "verbose": False, "workers": 0}
    for chiave in ("imgsz", "batch", "split"):
        if impostazioni.get(chiave):
            opzioni[chiave] = impostazioni[chiave]
    for chiave in ("imgsz", "batch"):
        if chiave in opzioni:
            opzioni[chiave] = int(opzioni[chiave])
    with tempfile.TemporaryDirectory() as cartella:
        return YOLO(str(pesi)).val(project=cartella, name="val", **opzioni)


def tabella_validazione(risultato, immagini_totali):
    intestazioni = ("classe", "immagini", "istanze", "precisione", "richiamo", "mAP50", "mAP50-95")
    nomi = getattr(risultato, "names", {}) or {}
    indici = list(getattr(risultato, "ap_class_index", []))
    per_classe = getattr(risultato, "nt_per_class", None)
    per_immagine = getattr(risultato, "nt_per_image", None)

    istanze_totali = int(sum(per_classe)) if per_classe is not None else None
    righe = [("tutte",
              numero_italiano(immagini_totali) if immagini_totali else "-",
              numero_italiano(istanze_totali) if istanze_totali is not None else "-",
              numero_italiano(risultato.box.mp, 3),
              numero_italiano(risultato.box.mr, 3),
              numero_italiano(risultato.box.map50, 3),
              numero_italiano(risultato.box.map, 3))]

    for posizione, indice in enumerate(indici):
        precisione, richiamo, ap50, ap = risultato.box.class_result(posizione)
        righe.append((str(nomi.get(int(indice), indice)),
                      numero_italiano(int(per_immagine[int(indice)])) if per_immagine is not None else "-",
                      numero_italiano(int(per_classe[int(indice)])) if per_classe is not None else "-",
                      numero_italiano(precisione, 3),
                      numero_italiano(richiamo, 3),
                      numero_italiano(ap50, 3),
                      numero_italiano(ap, 3)))

    tabella = [intestazioni] + righe
    larghezze = [max(len(r[i]) for r in tabella) for i in range(len(intestazioni))]
    fuori = [r[0].ljust(larghezze[0]) + "".join("   " + r[i].rjust(larghezze[i])
                                                for i in range(1, len(r)))
             for r in tabella]
    return ["    " + r.rstrip() for r in fuori]


def registrato_nel_catalogo(modello):
    if not CATALOGO.is_file():
        return False
    try:
        catalogo = json.loads(CATALOGO.read_bytes().decode("utf-8"))
    except ValueError:
        return False
    return any(str(m.get("weights", "")).replace("\\", "/").split("/")[0] == modello
               for m in catalogo.get("models", []))


def paragrafo_esistente(percorso):
    if not percorso.is_file():
        return []
    testo = percorso.read_bytes().decode("utf-8")
    righe = testo.split(terminatore(testo))
    if len(righe) < 3 or righe[1].strip():
        return []
    paragrafo = []
    for riga in righe[2:]:
        if not riga.strip():
            break
        paragrafo.append(riga)
    return paragrafo


def segnala_scheda_obsoleta(percorso):
    if not percorso.is_file():
        return False
    testo = percorso.read_bytes().decode("utf-8")
    if a_capo(AVVISO_OBSOLETA)[0] in testo:
        return False
    fine = terminatore(testo)
    corpo = testo.rstrip()
    righe = [corpo, ""] + a_capo(AVVISO_OBSOLETA)
    percorso.write_bytes((fine.join(righe) + fine).encode("utf-8"))
    return True


def frase_conservata(percorso, inizio):
    if not percorso.is_file():
        return ""
    testo = percorso.read_bytes().decode("utf-8")
    unito = " ".join(r.strip() for r in testo.split(terminatore(testo)))
    posizione = unito.find(inizio)
    if posizione < 0:
        return ""
    fine = re.search(r"\.(?!\d)", unito[posizione:])
    return unito[posizione:posizione + fine.end()] if fine else ""


def a_capo(testo, larghezza=79):
    righe, corrente = [], ""
    for parola in testo.split():
        if corrente and len(corrente) + 1 + len(parola) > larghezza:
            righe.append(corrente)
            corrente = parola
        else:
            corrente = f"{corrente} {parola}".strip()
    if corrente:
        righe.append(corrente)
    return righe


def blocco_comando(valori):
    righe = [f"    model = YOLO('{valori.get('model', 'yolo26s.pt')}')", "    model.train("]
    for chiave in CHIAVI_COMANDO:
        if chiave not in valori:
            continue
        valore = valori[chiave]
        if chiave in ("data", "name", "project"):
            valore = f"'{valore}'"
        elif chiave == "plots":
            valore = "True" if valore.lower() == "true" else "False"
        righe.append(f"        {chiave}={valore},")
    righe.append("    )")
    return righe


def scrivi_scheda(destinazione, modello, valori, risultato, metadati, eseguite, dati_risolti):
    fine = "\r\n"
    info = destinazione / "info.txt"
    dataset = nome_dataset(valori.get("data", ""))
    previste = valori.get("epochs")

    apertura = paragrafo_esistente(info)
    if not apertura:
        apertura = ["Da completare: che cosa riconosce il modello e con quali classi."]

    pezzi = [f"Python {platform.python_version()}"]
    macchina = ""
    try:
        import torch
        pezzi.append(f"torch {torch.__version__}")
        if torch.cuda.is_available():
            macchina = f" su {torch.cuda.get_device_name(0)}"
    except Exception:
        pass
    versione = metadati.get("versione") or "sconosciuta"
    partenza = valori.get("model", "yolo26s.pt").replace("\\", "/")
    if "/" in partenza:
        partenza = "/".join(partenza.split("/")[-2:])
    frasi = [f"Addestrato con Ultralytics {versione} ({', '.join(pezzi)}){macchina}, "
             f"partendo da {partenza} e dal dataset {dataset}."]

    migliore = epoca_migliore(righe_results(destinazione / "results.csv"),
                              metadati.get("metriche"))
    pazienza = valori.get("patience")
    anticipato = f" (patience={pazienza})" if pazienza else ""
    epoca = f"best.pt conserva i pesi dell'epoca {migliore}" if migliore else ""
    if eseguite and previste and str(eseguite) != str(previste):
        if pazienza:
            frase = (f"Delle {previste} epoche previste ne ha eseguite {eseguite}: nelle "
                     f"ultime {pazienza} i risultati di validazione non sono migliorati, "
                     f"così è scattato l'arresto anticipato{anticipato}")
        else:
            frase = f"Delle {previste} epoche previste ne ha eseguite {eseguite}"
        frasi.append(f"{frase} e {epoca}." if epoca else f"{frase}.")
    elif eseguite:
        frase = (f"Ha eseguito tutte le {eseguite} epoche previste, senza che "
                 f"l'arresto anticipato{anticipato} scattasse")
        frasi.append(f"{frase}, e {epoca}." if epoca else f"{frase}.")

    if valori.get("resume", "false").endswith(".pt"):
        frasi.append("La sessione è stata interrotta e ripresa da weights/last.pt: "
                     "l'ultimo avvio è ripartito da lì, non dai pesi di base.")

    risultante = frase_conservata(info, "Modello risultante:")
    if risultante:
        frasi.append(risultante)

    velocita = getattr(risultato, "speed", {}) or {}
    tempi = ("Per immagine: "
             + f"{numero_italiano(velocita.get('preprocess', 0), 1)} ms di preparazione, "
             + f"{numero_italiano(velocita.get('inference', 0), 1)} ms di inferenza, "
             + f"{numero_italiano(velocita.get('postprocess', 0), 1)} ms di post-elaborazione.")

    corpo = [modello, ""] + apertura + [""] + a_capo(" ".join(frasi))
    corpo += [""] + blocco_comando(valori)
    corpo += ["", "Validazione di best.pt:", ""]
    corpo += tabella_validazione(risultato, conta_immagini_val(dati_risolti))
    corpo += ["", *a_capo(tempi), ""]

    info.write_bytes(fine.join(corpo).encode("utf-8"))


def _ensure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


if __name__ == "__main__":
    _ensure_utf8_console()
    argomenti = [a for a in sys.argv[1:] if not a.startswith("--")]
    sostituisci = "--sostituisci" in sys.argv
    scheda = "--scheda" in sys.argv

    if len(argomenti) != 2:
        print("Uso: python deploy.py <addestramento> <modello> [--sostituisci] [--scheda]")
        print("Copia un addestramento finito nella cartella da cui il sistema di volo carica.")
        print(f"  da (banco di prova): {breve(RUNS_DIR)}")
        print(f"  a  (in servizio):    {breve(MODELS_DIR)}")
        print("--sostituisci rimpiazza un modello che è già in servizio.")
        print("--scheda rigenera info.txt rifacendo la validazione, quindi richiede il dataset.")
        pronti = run_disponibili()
        print(f"Addestramenti pronti: {', '.join(pronti) if pronti else 'nessuno'}")
        in_servizio = modelli_disponibili()
        print(f"Modelli in servizio: {', '.join(in_servizio) if in_servizio else 'nessuno'}")
        sys.exit(1)

    nome_run, modello = argomenti
    origine = RUNS_DIR / nome_run
    destinazione = MODELS_DIR / modello
    pesi_origine = origine / "weights" / "best.pt"
    pesi_destinazione = destinazione / "weights" / "best.pt"

    if not pesi_origine.is_file():
        print(f"Addestramento non utilizzabile: manca {breve(pesi_origine)}")
        pronti = run_disponibili()
        if pronti:
            print(f"Addestramenti pronti: {', '.join(pronti)}")
        sys.exit(1)

    sostituzione = pesi_destinazione.is_file()
    if sostituzione and not sostituisci:
        print(f"In {modello} c'è già un modello in servizio: {breve(pesi_destinazione)}")
        print("Rilancia con --sostituisci per rimpiazzarlo.")
        sys.exit(1)

    (destinazione / "weights").mkdir(parents=True, exist_ok=True)
    copiati = []
    rimossi = []
    for relativo in DA_COPIARE:
        sorgente = origine / relativo
        arrivo = destinazione / relativo
        if not sorgente.is_file():
            if arrivo.is_file():
                arrivo.unlink()
                rimossi.append(relativo.as_posix())
            else:
                print(f"Saltato, non c'è nell'addestramento: {relativo.as_posix()}")
            continue
        shutil.copy2(sorgente, arrivo)
        copiati.append(relativo.as_posix())
    print(f"Copiati in {breve(destinazione)}: {', '.join(copiati)}")
    if rimossi:
        print(f"Rimossi perché l'addestramento non li ha, restavano dal modello "
              f"precedente: {', '.join(rimossi)}")

    args = destinazione / "args.yaml"
    if args.is_file():
        sistema_args(args, modello)
        print(f"args.yaml riscritto con i percorsi di {modello}")

    results = destinazione / "results.csv"
    if results.is_file() and formatta_results(results):
        print("results.csv convertito nel formato italiano: punto e virgola e decimali con la virgola.")

    if sostituzione and segnala_scheda_obsoleta(destinazione / "info.txt"):
        print("In fondo a info.txt è stato aggiunto un avviso: la scheda descrive "
              "ancora l'addestramento precedente.")

    if not registrato_nel_catalogo(modello):
        print(f"Attenzione: {modello} non compare in {CATALOGO.name}, "
              "quindi il sistema di volo non lo caricherebbe.")

    valori = valori_di(args)
    eseguite = len(righe_results(results)) or None

    if scheda:
        dati = valori.get("data", "")
        percorso_dati = Path(dati)
        if not percorso_dati.is_absolute():
            percorso_dati = MODELS_DIR.parents[1] / dati
        if not percorso_dati.is_file():
            print(f"Dataset non trovato: {breve(percorso_dati)}")
            print("info.txt non rigenerato: la validazione ha bisogno del dataset.")
            sys.exit(1)
        print(f"Validazione di best.pt su {percorso_dati.parent.name}: "
              "può richiedere tempo...", flush=True)
        risultato = esegui_validazione(pesi_destinazione, percorso_dati, valori)
        scrivi_scheda(destinazione, modello, valori, risultato,
                      metadati_checkpoint(pesi_destinazione), eseguite, percorso_dati)
        print("info.txt rigenerato.")
        print("  conservati: il paragrafo di apertura e la frase sul modello risultante")
        print("  rimisurato: tutto il resto")
        print("  la versione di Ultralytics viene dal checkpoint dell'addestramento")
        print("  Python, torch e GPU descrivono invece la macchina che gira adesso")
    else:
        print()
        print(f"Da aggiornare a mano in {breve(destinazione / 'info.txt')}:")
        if eseguite and valori.get("epochs"):
            print(f"  le epoche eseguite sono {eseguite} sulle {valori['epochs']} previste")
        print("  la tabella di validazione, dall'output dell'addestramento")
        print("  la riga con Ultralytics, Python, torch e GPU, dallo stesso output")
        print("Non prenderle da results.csv: si ferma sull'ultima epoca, non su best.pt.")
        print("In alternativa rilancia con --scheda per rigenerarlo dalla validazione.")
