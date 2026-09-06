import os
import sys
from pathlib import Path

import supervision as sv


def _ensure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


_ensure_utf8_console()

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parents[3]
DATASET_DIR = SCRIPT_DIR / "dataset"
OUTPUT_DIR = SCRIPT_DIR / "split"
SEED = 42


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


def elenco(nomi):
    if len(nomi) == 1:
        return nomi[0]
    return ", ".join(nomi[:-1]) + " e " + nomi[-1]

dataset_dir = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DATASET_DIR
output_dir = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else OUTPUT_DIR

if not (dataset_dir / "data.yaml").is_file():
    print(f"Dataset non trovato: manca {breve(dataset_dir / 'data.yaml')}")
    print("Uso: python split.py [cartella del dataset] [cartella di destinazione]")
    print("Senza argomenti usa:")
    print(f"  dataset:      {breve(DATASET_DIR)}")
    print(f"  destinazione: {breve(OUTPUT_DIR)}")
    sys.exit(1)

if destinazione_occupata(output_dir):
    print(f"La cartella di destinazione non è vuota: {breve(output_dir)}")
    print("Rimuovila o indicane un'altra: rieseguendo, il nuovo dataset si sommerebbe a quello vecchio.")
    sys.exit(1)

ds = sv.DetectionDataset.from_yolo(
    images_directory_path=str(dataset_dir / "train" / "images"),
    annotations_directory_path=str(dataset_dir / "train" / "labels"),
    data_yaml_path=str(dataset_dir / "data.yaml")
)

if len(ds) == 0:
    print(f"Nessuna immagine trovata in {breve(dataset_dir / 'train' / 'images')}: "
          "niente da suddividere.")
    sys.exit(1)

ds_train, ds_resto = ds.split(split_ratio=0.8, shuffle=True, random_state=SEED)
ds_valid, ds_test = ds_resto.split(split_ratio=0.5, shuffle=True, random_state=SEED)

gruppi = (("addestramento", ds_train), ("validazione", ds_valid), ("prova", ds_test))
vuoti = [nome for nome, gruppo in gruppi if len(gruppo) == 0]
if vuoti:
    immagini = "1 immagine" if len(ds) == 1 else f"{len(ds)} immagini"
    quali = "vuoto il gruppo" if len(vuoti) == 1 else "vuoti i gruppi"
    print(f"Con {immagini} la suddivisione lascia {quali} di {elenco(vuoti)}.")
    print("Servono più immagini o proporzioni diverse. Non è stato scritto niente.")
    sys.exit(1)

senza_annotazioni = [nome for nome, gruppo in gruppi
                     if not any(len(det) > 0 for det in gruppo.annotations.values())]
if senza_annotazioni:
    quali = "Il gruppo" if len(senza_annotazioni) == 1 else "I gruppi"
    verbo = "contiene" if len(senza_annotazioni) == 1 else "contengono"
    print(f"{quali} di {elenco(senza_annotazioni)} {verbo} solo immagini di sfondo, senza annotazioni.")
    print("Con questa suddivisione le misure di qualità non avrebbero senso. Non è stato scritto niente.")
    sys.exit(1)

print()
print(f"Suddivisione con seme {SEED}: rilanciando lo script si ottengono gli stessi gruppi.")
print("Immagini per gruppo:")
print(f"  addestramento: {len(ds_train)}")
print(f"  validazione:   {len(ds_valid)}")
print(f"  prova:         {len(ds_test)}")
print()

print("Salvataggio del gruppo di addestramento...", flush=True)
ds_train.as_yolo(
    images_directory_path=str(output_dir / "train" / "images"),
    annotations_directory_path=str(output_dir / "train" / "labels"),
    data_yaml_path=str(output_dir / "data.yaml"),
)
print("Salvataggio del gruppo di validazione...", flush=True)
ds_valid.as_yolo(
    images_directory_path=str(output_dir / "valid" / "images"),
    annotations_directory_path=str(output_dir / "valid" / "labels"),
    data_yaml_path=str(output_dir / "data.yaml"),
)
print("Salvataggio del gruppo di prova...", flush=True)
ds_test.as_yolo(
    images_directory_path=str(output_dir / "test" / "images"),
    annotations_directory_path=str(output_dir / "test" / "labels"),
    data_yaml_path=str(output_dir / "data.yaml"),
)
print(f"Suddivisione completata. Il risultato è in {breve(output_dir)}")
print()
