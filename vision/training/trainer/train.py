"""Avvio di un nuovo addestramento YOLO.

Lo script individua il file ``data.yaml`` del dataset e avvia un nuovo
addestramento Ultralytics utilizzando ``yolo26s.pt`` come modello di base.

Il dataset può essere indicato:
- tramite un percorso diretto a una cartella o a un file YAML;
- tramite il nome di una cartella presente in ``datasets``.

Il nome del run viene ricavato automaticamente dal nome della cartella che
contiene ``data.yaml``. I risultati vengono salvati in
``vision/training/trainer/models``.

L'addestramento viene eseguito in un processo separato con metodo ``spawn``.
La GPU viene utilizzata automaticamente quando CUDA è disponibile; in caso
contrario viene selezionata la CPU.
"""

import sys
from multiprocessing import Process, freeze_support, set_start_method
from pathlib import Path

import torch
from ultralytics import YOLO


SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parents[2]
DATASETS_DIR = SCRIPT_DIR / "datasets"
RUNS_DIR = SCRIPT_DIR / "models"
DEFAULT_DATASET = "dataset"

# Configurazione principale dell'addestramento.
BASE_MODEL = "yolo26s.pt"
EPOCHS = 300
PATIENCE = 50
IMAGE_SIZE = 640
BATCH = 16


def breve(percorso):
    """Restituisce un percorso relativo alla radice del progetto, se possibile."""
    percorso = Path(percorso).resolve()

    try:
        return str(percorso.relative_to(BASE_DIR))
    except ValueError:
        return str(percorso)


def trova_data_yaml(nome):
    """Individua il file ``data.yaml`` associato al dataset indicato."""
    indicato = Path(nome).expanduser()

    for base in (indicato, DATASETS_DIR / indicato):
        candidato = (
            base
            if base.suffix in (".yaml", ".yml")
            else base / "data.yaml"
        )

        if candidato.is_file():
            return candidato.resolve()

    return None


def dataset_disponibili():
    """Elenca i dataset presenti nella cartella ``datasets``."""
    if not DATASETS_DIR.is_dir():
        return []

    return sorted(
        directory.name
        for directory in DATASETS_DIR.iterdir()
        if (directory / "data.yaml").is_file()
    )


def train(data_path, run_name):
    """Avvia un nuovo addestramento YOLO con i parametri configurati."""
    model = YOLO(BASE_MODEL)

    model.train(
        data=str(data_path),
        name=run_name,
        epochs=EPOCHS,
        patience=PATIENCE,
        imgsz=IMAGE_SIZE,
        batch=BATCH,
        device=0 if torch.cuda.is_available() else "cpu",
        project=str(RUNS_DIR),
        plots=False,
        close_mosaic=0,
    )

    print("Addestramento completato.")


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

    nome = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DATASET
    data_path = trova_data_yaml(nome)

    if data_path is None:
        print(f"Dataset non trovato: {nome}")
        print(
            "Uso: python train.py "
            "[cartella del dataset | percorso di data.yaml]"
        )
        print(
            f"Senza argomenti cerca: "
            f"{breve(DATASETS_DIR / DEFAULT_DATASET / 'data.yaml')}"
        )

        disponibili = dataset_disponibili()

        if disponibili:
            print(
                f"Dataset disponibili: {', '.join(disponibili)}"
            )
        else:
            print(
                f"Non c'è nessun dataset sotto "
                f"{breve(DATASETS_DIR)}"
            )

        sys.exit(1)

    run_name = data_path.parent.name

    print(f"Dataset: {breve(data_path)}", flush=True)
    print(
        f"Risultati nel banco di prova: "
        f"{breve(RUNS_DIR)}",
        flush=True,
    )

    freeze_support()
    set_start_method("spawn", force=True)

    process = Process(
        target=train,
        args=(data_path, run_name),
    )
    process.start()
    process.join()

    sys.exit(process.exitcode)
    