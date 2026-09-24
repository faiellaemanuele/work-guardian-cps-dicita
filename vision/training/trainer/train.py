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

BASE_MODEL = 'yolo26s.pt'
EPOCHS = 300
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


def dataset_disponibili():
    if not DATASETS_DIR.is_dir():
        return []
    return sorted(d.name for d in DATASETS_DIR.iterdir() if (d / 'data.yaml').is_file())


def train(data_path, run_name):
    model = YOLO(BASE_MODEL)

    model.train(
        data=str(data_path),
        name=run_name,
        epochs=EPOCHS,
        patience=PATIENCE,
        imgsz=IMAGE_SIZE,
        batch=BATCH,
        device=0 if torch.cuda.is_available() else 'cpu',
        project=str(RUNS_DIR),
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
        print("Uso: python train.py [cartella del dataset | percorso di data.yaml]")
        print(f"Senza argomenti cerca: {breve(DATASETS_DIR / DEFAULT_DATASET / 'data.yaml')}")
        disponibili = dataset_disponibili()
        if disponibili:
            print(f"Dataset disponibili: {', '.join(disponibili)}")
        else:
            print(f"Non c'è nessun dataset sotto {breve(DATASETS_DIR)}")
        sys.exit(1)

    run_name = data_path.parent.name
    print(f"Dataset: {breve(data_path)}", flush=True)
    print(f"Risultati nel banco di prova: {breve(RUNS_DIR)}", flush=True)

    freeze_support()
    set_start_method('spawn', force=True)
    p = Process(target=train, args=(data_path, run_name))
    p.start()
    p.join()
    sys.exit(p.exitcode)
