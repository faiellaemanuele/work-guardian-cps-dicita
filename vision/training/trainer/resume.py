import sys
from multiprocessing import Process, freeze_support, set_start_method
from pathlib import Path

import torch
from ultralytics import YOLO

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parents[2]
DATASETS_DIR = SCRIPT_DIR / 'datasets'
RUNS_DIR = SCRIPT_DIR / 'models'
DEFAULT_DATASET = 'dataset'

PATIENCE = 50
IMAGE_SIZE = 640
BATCH = 16


def breve(percorso):
    percorso = Path(percorso).resolve()
    try:
        return str(percorso.relative_to(BASE_DIR))
    except ValueError:
        return str(percorso)


def trova_data_yaml(nome):
    indicato = Path(nome).expanduser()
    for base in (indicato, DATASETS_DIR / indicato):
        candidato = base if base.suffix in ('.yaml', '.yml') else base / 'data.yaml'
        if candidato.is_file():
            return candidato.resolve()
    return None


def addestramenti_ripredibili():
    if not RUNS_DIR.is_dir():
        return []
    return sorted(d.name for d in RUNS_DIR.iterdir() if (d / 'weights' / 'last.pt').is_file())


def train(checkpoint, data_path):
    model = YOLO(checkpoint)

    model.train(
        resume=True,
        data=str(data_path),
        patience=PATIENCE,
        imgsz=IMAGE_SIZE,
        batch=BATCH,
        device=0 if torch.cuda.is_available() else 'cpu',
        plots=False,
        close_mosaic=0,
    )

    print("Addestramento completato.")


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
    nome = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DATASET
    data_path = trova_data_yaml(nome)
    if data_path is None:
        print(f"Dataset non trovato: {nome}")
        print("Uso: python resume.py [cartella del dataset] [nome dell'addestramento]")
        print(f"Senza argomenti cerca: {breve(DATASETS_DIR / DEFAULT_DATASET / 'data.yaml')}")
        print("Senza il secondo argomento si usa il nome della cartella del dataset.")
        sys.exit(1)

    run_name = sys.argv[2] if len(sys.argv) > 2 else data_path.parent.name
    checkpoint = RUNS_DIR / run_name / 'weights' / 'last.pt'
    if not checkpoint.is_file():
        print(f"Checkpoint da riprendere non trovato: {breve(checkpoint)}")
        disponibili = addestramenti_ripredibili()
        if disponibili:
            print(f"Addestramenti che si possono riprendere: {', '.join(disponibili)}")
        else:
            print(f"Non c'è nessun addestramento da riprendere sotto {breve(RUNS_DIR)}")
        sys.exit(1)

    print(f"Dataset: {breve(data_path)}", flush=True)
    print(f"Si riprende da: {breve(checkpoint)}", flush=True)

    freeze_support()
    set_start_method('spawn', force=True)
    p = Process(target=train, args=(checkpoint, data_path))
    p.start()
    p.join()
    sys.exit(p.exitcode)
