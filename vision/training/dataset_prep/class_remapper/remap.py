import os
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parents[3]
DATASET_PATH = SCRIPT_DIR / "dataset"
OUTPUT_PATH = SCRIPT_DIR / "dataset_rinumerato"

OLD_TO_NEW_MAP = {0: None, 1: None, 2: 2, 3: None, 4: 0, 5: None, 6: None, 7: 3,
                  8: 1, 9: None, 10: None, 11: 6, 12: None, 13: 4, 14: None,
                  15: None, 16: 7, 17: 5}


def breve(percorso):
    percorso = Path(percorso).resolve()
    try:
        return str(percorso.relative_to(BASE_DIR))
    except ValueError:
        return str(percorso)


def destinazione_occupata(percorso):
    if os.path.isfile(percorso):
        return True
    return os.path.isdir(percorso) and any(os.scandir(percorso))


def label_files(root_folder):
    root = os.path.normpath(root_folder)
    for subdir, _dirs, files in os.walk(root):
        if 'labels' not in os.path.relpath(subdir, root).split(os.sep):
            continue
        for filename in sorted(files):
            if filename.endswith('.txt'):
                yield os.path.join(subdir, filename)


def find_unknown_classes(root_folder, mapping):
    unknown = {}
    total = 0
    for file_path in label_files(root_folder):
        total += 1
        with open(file_path, 'r', encoding='utf-8-sig') as file:
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
    rinumerate = 0
    scartate = 0
    svuotati = 0
    for file_path in label_files(root_folder):
        with open(file_path, 'r', encoding='utf-8-sig') as file:
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
            new_lines.append(' '.join(parts))
            rinumerate += 1

        with open(file_path, 'w', encoding='utf-8', newline='') as file:
            if new_lines:
                file.write('\n'.join(new_lines))
                file.write('\n')
            elif lines:
                svuotati += 1

    return rinumerate, scartate, svuotati


def check_new_ids(mapping):
    nuovi = sorted({v for v in mapping.values() if v is not None})
    attesi = list(range(len(nuovi)))
    return nuovi, attesi


def _ensure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


if __name__ == '__main__':
    _ensure_utf8_console()
    dataset_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DATASET_PATH
    output_path = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else OUTPUT_PATH

    nuovi, attesi = check_new_ids(OLD_TO_NEW_MAP)
    if not nuovi:
        print("OLD_TO_NEW_MAP scarta tutte le classi: non resterebbe nessuna annotazione.")
        sys.exit(1)
    if nuovi != attesi:
        mancanti = [i for i in attesi if i not in nuovi]
        print(f"OLD_TO_NEW_MAP assegna i numeri di classe {nuovi}: non formano "
              "una numerazione che parte da 0 e prosegue senza salti.")
        print(f"Mancano {mancanti}: YOLO richiede le classi numerate da 0 a {len(nuovi) - 1}.")
        sys.exit(1)

    if not dataset_path.is_dir():
        print(f"Dataset non trovato: {breve(dataset_path)}")
        print("Uso: python remap.py [cartella del dataset] [cartella di destinazione]")
        print("Senza argomenti usa:")
        print(f"  dataset:      {breve(DATASET_PATH)}")
        print(f"  destinazione: {breve(OUTPUT_PATH)}")
        sys.exit(1)

    if destinazione_occupata(output_path):
        print(f"La cartella di destinazione non è vuota: {breve(output_path)}")
        print("Rimuovila o indicane un'altra: rinumerare due volte lo stesso dataset cancella le annotazioni.")
        sys.exit(1)

    print(f"Dataset da rinumerare: {breve(dataset_path)}")

    total, unknown = find_unknown_classes(dataset_path, OLD_TO_NEW_MAP)

    if total == 0:
        print(f"Nessun file di etichette sotto {breve(dataset_path)}: "
              "serve una cartella 'labels'.")
        sys.exit(1)

    if unknown:
        print(f"Classi assenti da OLD_TO_NEW_MAP: {len(unknown)}")
        for label in sorted(unknown, key=str):
            posizioni = unknown[label]
            quante = ("1 occorrenza" if len(posizioni) == 1
                      else f"{len(posizioni)} occorrenze")
            percorso, riga = posizioni[0]
            print(f"  classe {label}: {quante}, la prima alla riga {riga} "
                  f"di {breve(percorso)}")
        print("Aggiungile a OLD_TO_NEW_MAP, in cima a remap.py, con None se "
              "vanno scartate.")
        print("Niente è stato modificato.")
        sys.exit(1)

    print(f"File di etichette trovati: {total}")
    print(f"Copia dell'intero dataset in {breve(output_path)}: "
          "può richiedere tempo...", flush=True)
    try:
        shutil.copytree(dataset_path, output_path, dirs_exist_ok=True)
        print("Rinumerazione delle classi in corso...", flush=True)
        rinumerate, scartate, svuotati = remap_labels(output_path, OLD_TO_NEW_MAP)
    except Exception as exc:
        shutil.rmtree(output_path, ignore_errors=True)
        print(f"Rinumerazione interrotta: {exc}")
        print(f"La copia incompleta è stata rimossa: {breve(output_path)}")
        print("Il dataset originale non è stato toccato.")
        sys.exit(1)

    print(f"Rinumerazione completata. Annotazioni rinumerate: {rinumerate}, scartate: {scartate}.")
    if svuotati:
        quanti = ("1 file di etichette è rimasto" if svuotati == 1
                  else f"{svuotati} file di etichette sono rimasti")
        print(f"{quanti} senza annotazioni: le immagini corrispondenti "
              "diventano sfondo.")
    print(f"Il dataset originale non è stato toccato. Il risultato è in {breve(output_path)}")
