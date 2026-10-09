"""Rimappatura delle classi di un dataset YOLO.

Lo script crea una copia del dataset sorgente e ne modifica i file di
annotazione presenti nelle cartelle ``labels`` e il file ``data.yaml``.

La tabella ``OLD_TO_NEW_MAP`` stabilisce come trattare ciascuna classe:
- un intero assegna il nuovo identificativo della classe;
- ``None`` elimina le annotazioni appartenenti a quella classe.

Prima di eseguire la copia vengono controllati:
- la validità della nuova numerazione, che deve partire da 0 ed essere continua;
- l'eventuale presenza di classi non definite nella tabella di rimappatura;
- lo stato della cartella di destinazione, che deve essere vuota.

Nella copia, ``nc`` e ``names`` di ``data.yaml`` seguono la nuova numerazione.
Quando i nomi non si possono ricavare, perché ``data.yaml`` manca, non elenca
una classe mantenuta o più classi confluiscono nello stesso ID, il file resta
quello originale e lo script lo segnala; in questo caso va corretto a mano. La
riscrittura conserva tutte le chiavi del file, ma non i commenti.

Il dataset originale non viene modificato.
"""

import os
import shutil
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parents[3]
DATASET_PATH = SCRIPT_DIR / "dataset"
OUTPUT_PATH = SCRIPT_DIR / "dataset_rinumerato"

# Associazione tra ID originali e nuovi ID.
# Il valore None indica che la classe deve essere esclusa dal dataset risultante.
OLD_TO_NEW_MAP = {
    0: None,
    1: None,
    2: 2,
    3: None,
    4: 0,
    5: None,
    6: None,
    7: 3,
    8: 1,
    9: None,
    10: None,
    11: 6,
    12: None,
    13: 4,
    14: None,
    15: None,
    16: 7,
    17: 5,
}


def breve(percorso):
    """Restituisce un percorso relativo alla radice del progetto, se possibile."""
    percorso = Path(percorso).resolve()
    try:
        return str(percorso.relative_to(BASE_DIR))
    except ValueError:
        return str(percorso)


def destinazione_occupata(percorso):
    """Verifica se la destinazione esiste già come file o cartella non vuota."""
    if os.path.isfile(percorso):
        return True
    return os.path.isdir(percorso) and any(os.scandir(percorso))


def label_files(root_folder):
    """Itera sui file .txt contenuti nelle cartelle ``labels`` del dataset."""
    root = os.path.normpath(root_folder)

    for subdir, _dirs, files in os.walk(root):
        if "labels" not in os.path.relpath(subdir, root).split(os.sep):
            continue

        for filename in sorted(files):
            if filename.endswith(".txt"):
                yield os.path.join(subdir, filename)


def find_unknown_classes(root_folder, mapping):
    """Individua classi presenti nelle annotazioni ma assenti dalla mappatura."""
    unknown = {}
    total = 0

    for file_path in label_files(root_folder):
        total += 1

        with open(file_path, "r", encoding="utf-8-sig") as file:
            for number, line in enumerate(file, 1):
                parts = line.split()
                if not parts:
                    continue

                try:
                    label = int(parts[0])
                except ValueError:
                    label = parts[0]

                if label not in mapping:
                    unknown.setdefault(label, []).append((file_path, number))

    return total, unknown


def remap_labels(root_folder, mapping):
    """Rimappa gli ID delle classi nei file di annotazione del dataset copiato.

    Le annotazioni associate a una classe mappata su ``None`` vengono eliminate.
    Se un file perde tutte le annotazioni, viene mantenuto vuoto: l'immagine
    corrispondente può quindi essere utilizzata come esempio di sfondo.
    """
    rinumerate = 0
    scartate = 0
    svuotati = 0

    for file_path in label_files(root_folder):
        with open(file_path, "r", encoding="utf-8-sig") as file:
            lines = file.readlines()

        new_lines = []

        for line in lines:
            parts = line.split()
            if not parts:
                continue

            label = int(parts[0])

            if mapping[label] is None:
                scartate += 1
                continue

            parts[0] = str(mapping[label])
            new_lines.append(" ".join(parts))
            rinumerate += 1

        with open(file_path, "w", encoding="utf-8", newline="") as file:
            if new_lines:
                file.write("\n".join(new_lines))
                file.write("\n")
            elif lines:
                svuotati += 1

    return rinumerate, scartate, svuotati


def check_new_ids(mapping):
    """Controlla che i nuovi ID siano consecutivi e inizino da zero."""
    nuovi = sorted({value for value in mapping.values() if value is not None})
    attesi = list(range(len(nuovi)))
    return nuovi, attesi


def read_data_yaml(percorso):
    """Legge ``data.yaml``; restituisce il contenuto oppure il motivo per cui non è utilizzabile."""
    if not percorso.is_file():
        return None, f"manca {breve(percorso)}"
    try:
        contenuto = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return None, f"{breve(percorso)} non è leggibile ({exc})"
    if not isinstance(contenuto, dict):
        return None, f"{breve(percorso)} non contiene le chiavi di un dataset YOLO"
    return contenuto, None


def remapped_names(contenuto, mapping):
    """Restituisce i nomi delle classi ordinati secondo i nuovi ID, oppure il motivo per cui non si possono ricavare."""
    nomi = contenuto.get("names")
    if isinstance(nomi, list):
        vecchi = dict(enumerate(nomi))
    elif isinstance(nomi, dict):
        try:
            vecchi = {int(chiave): valore for chiave, valore in nomi.items()}
        except (TypeError, ValueError):
            return None, "le chiavi di 'names' non sono numeri di classe"
    else:
        return None, "manca l'elenco 'names'"

    per_nuovo_id = {}
    for vecchio, nuovo in mapping.items():
        if nuovo is None:
            continue
        if vecchio not in vecchi:
            return None, f"'names' non contiene la classe {vecchio}"
        per_nuovo_id.setdefault(nuovo, []).append(vecchi[vecchio])

    fusi = sorted(nuovo for nuovo, origini in per_nuovo_id.items() if len(origini) > 1)
    if fusi:
        return None, (
            f"più classi originali confluiscono negli ID {fusi}: il nome "
            "da dare a ciascuno va scelto a mano"
        )
    return [per_nuovo_id[nuovo][0] for nuovo in range(len(per_nuovo_id))], None


def _ensure_utf8_console() -> None:
    """Configura stdout e stderr in UTF-8 quando il runtime lo consente."""
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

    dataset_path = (
        Path(sys.argv[1]).expanduser()
        if len(sys.argv) > 1
        else DATASET_PATH
    )
    output_path = (
        Path(sys.argv[2]).expanduser()
        if len(sys.argv) > 2
        else OUTPUT_PATH
    )

    nuovi, attesi = check_new_ids(OLD_TO_NEW_MAP)

    if not nuovi:
        print(
            "OLD_TO_NEW_MAP scarta tutte le classi: "
            "non resterebbe nessuna annotazione."
        )
        sys.exit(1)

    if nuovi != attesi:
        mancanti = [i for i in attesi if i not in nuovi]
        print(
            f"OLD_TO_NEW_MAP assegna i numeri di classe {nuovi}: non formano "
            "una numerazione che parte da 0 e prosegue senza salti."
        )
        print(
            f"Mancano {mancanti}: YOLO richiede le classi numerate da 0 "
            f"a {len(nuovi) - 1}."
        )
        sys.exit(1)

    if not dataset_path.is_dir():
        print(f"Dataset non trovato: {breve(dataset_path)}")
        print(
            "Uso: python remap.py "
            "[cartella del dataset] [cartella di destinazione]"
        )
        print("Senza argomenti usa:")
        print(f"  dataset:      {breve(DATASET_PATH)}")
        print(f"  destinazione: {breve(OUTPUT_PATH)}")
        sys.exit(1)

    if destinazione_occupata(output_path):
        print(
            f"La cartella di destinazione non è vuota: "
            f"{breve(output_path)}"
        )
        print(
            "Rimuovila o indicane un'altra: rinumerare due volte lo stesso "
            "dataset cancella le annotazioni."
        )
        sys.exit(1)

    print(f"Dataset da rinumerare: {breve(dataset_path)}")

    total, unknown = find_unknown_classes(dataset_path, OLD_TO_NEW_MAP)

    if total == 0:
        print(
            f"Nessun file di etichette sotto {breve(dataset_path)}: "
            "serve una cartella 'labels'."
        )
        sys.exit(1)

    if unknown:
        print(f"Classi assenti da OLD_TO_NEW_MAP: {len(unknown)}")

        for label in sorted(unknown, key=str):
            posizioni = unknown[label]
            quante = (
                "1 occorrenza"
                if len(posizioni) == 1
                else f"{len(posizioni)} occorrenze"
            )
            percorso, riga = posizioni[0]

            print(
                f"  classe {label}: {quante}, la prima alla riga {riga} "
                f"di {breve(percorso)}"
            )

        print(
            "Aggiungile a OLD_TO_NEW_MAP, in cima a remap.py, con None se "
            "vanno scartate."
        )
        print("Niente è stato modificato.")
        sys.exit(1)

    print(f"File di etichette trovati: {total}")

    # I nomi delle classi si ricavano prima della copia. Se non è possibile, la
    # rinumerazione prosegue comunque e il problema viene segnalato alla fine.
    contenuto_yaml, problema_yaml = read_data_yaml(dataset_path / "data.yaml")
    nuovi_nomi = None
    if contenuto_yaml is not None:
        nuovi_nomi, problema_yaml = remapped_names(contenuto_yaml, OLD_TO_NEW_MAP)

    print(
        f"Copia dell'intero dataset in {breve(output_path)}: "
        "può richiedere tempo...",
        flush=True,
    )

    try:
        shutil.copytree(dataset_path, output_path, dirs_exist_ok=True)
        print("Rinumerazione delle classi in corso...", flush=True)

        rinumerate, scartate, svuotati = remap_labels(
            output_path,
            OLD_TO_NEW_MAP,
        )

        # Ultralytics rifiuta un data.yaml in cui nc non coincide con il numero
        # dei nomi. nc si aggiorna solo se il file lo dichiara, poiché in sua
        # assenza Ultralytics lo ricava dai nomi.
        if nuovi_nomi is not None:
            contenuto_yaml["names"] = nuovi_nomi
            if "nc" in contenuto_yaml:
                contenuto_yaml["nc"] = len(nuovi_nomi)
            (output_path / "data.yaml").write_text(
                yaml.safe_dump(contenuto_yaml, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

    except Exception as exc:
        shutil.rmtree(output_path, ignore_errors=True)

        print(f"Rinumerazione interrotta: {exc}")
        print(
            f"La copia incompleta è stata rimossa: {breve(output_path)}"
        )
        print("Il dataset originale non è stato toccato.")
        sys.exit(1)

    print(
        "Rinumerazione completata. "
        f"Annotazioni rinumerate: {rinumerate}, scartate: {scartate}."
    )

    if svuotati:
        quanti = (
            "1 file di etichette è rimasto"
            if svuotati == 1
            else f"{svuotati} file di etichette sono rimasti"
        )
        print(
            f"{quanti} senza annotazioni: le immagini corrispondenti "
            "diventano sfondo."
        )

    if nuovi_nomi is not None:
        print(f"data.yaml aggiornato con la nuova numerazione: names = {nuovi_nomi}")
    else:
        print(f"ATTENZIONE: data.yaml non aggiornato, {problema_yaml}.")
        print(
            "Va corretto a mano nella copia: 'nc' e 'names' devono seguire "
            "la nuova numerazione di OLD_TO_NEW_MAP."
        )

    print(
        "Il dataset originale non è stato toccato. "
        f"Il risultato è in {breve(output_path)}"
    )
    