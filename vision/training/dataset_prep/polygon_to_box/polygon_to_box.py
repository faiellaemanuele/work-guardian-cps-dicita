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
OUTPUT_DIR = SCRIPT_DIR / "converted"


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

dataset_dir = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DATASET_DIR
output_dir = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else OUTPUT_DIR

if not (dataset_dir / "data.yaml").is_file():
    print(f"Dataset non trovato: manca {breve(dataset_dir / 'data.yaml')}")
    print("Uso: python polygon_to_box.py [cartella del dataset] [cartella di destinazione]")
    print("Senza argomenti usa:")
    print(f"  dataset:      {breve(DATASET_DIR)}")
    print(f"  destinazione: {breve(OUTPUT_DIR)}")
    sys.exit(1)

if destinazione_occupata(output_dir):
    print(f"La cartella di destinazione non è vuota: {breve(output_dir)}")
    print("Rimuovila o indicane un'altra: rieseguendo, il nuovo dataset si sommerebbe a quello vecchio.")
    sys.exit(1)

convertite = 0

for folder in ["train", "valid", "test"]:
    ds = sv.DetectionDataset.from_yolo(
        images_directory_path=str(dataset_dir / folder / "images"),
        annotations_directory_path=str(dataset_dir / folder / "labels"),
        data_yaml_path=str(dataset_dir / "data.yaml"),
        force_masks=False
    )

    if len(ds) == 0:
        print(f"Cartella {folder} saltata: nessuna immagine in "
              f"{breve(dataset_dir / folder / 'images')}")
        continue

    immagini = "1 immagine" if len(ds) == 1 else f"{len(ds)} immagini"
    print(f"Conversione della cartella {folder} ({immagini})...", flush=True)

    for image_path, detections in ds.annotations.items():
        ds.annotations[image_path] = sv.Detections(
            xyxy=detections.xyxy,
            class_id=detections.class_id,
            confidence=detections.confidence
        )

    os.makedirs(output_dir / folder / "images", exist_ok=True)
    os.makedirs(output_dir / folder / "labels", exist_ok=True)

    ds.as_yolo(
        images_directory_path=str(output_dir / folder / "images"),
        annotations_directory_path=str(output_dir / folder / "labels"),
        data_yaml_path=str(output_dir / "data.yaml")
    )
    convertite += 1

if convertite == 0:
    print(f"Nessuna cartella è stata convertita: controlla il percorso {breve(dataset_dir)}")
    sys.exit(1)

print("Conversione completata: ogni annotazione è ora un rettangolo.")
print(f"Il risultato è in {breve(output_dir)}")
