"""Ripresa di un addestramento YOLO interrotto.

Lo script individua il file ``data.yaml`` del dataset e riprende un
addestramento precedente a partire dal checkpoint ``weights/last.pt``.

Il dataset può essere indicato:
- tramite un percorso diretto a una cartella o a un file YAML;
- tramite il nome di una cartella presente in ``datasets``.

Il nome del run da riprendere può essere passato come secondo argomento.
Se viene omesso, viene utilizzato il nome della cartella che contiene
``data.yaml``.

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


def addestramenti_ripredibili():
    """Elenca i run che dispongono di un checkpoint ``weights/last.pt``."""
    if not RUNS_DIR.is_dir():
        return []

    return sorted(
        directory.name
        for directory in RUNS_DIR.iterdir()
        if (directory / "weights" / "last.pt").is_file()
    )


def train(checkpoint, data_path):
    """Riprende l'addestramento dal checkpoint indicato."""
    model = YOLO(checkpoint)

    model.train(
        resume=True,
        data=str(data_path),
        patience=PATIENCE,
        imgsz=IMAGE_SIZE,
        batch=BATCH,
        device=0 if torch.cuda.is_available() else "cpu",
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
            "Uso: python resume.py "
            "[cartella del dataset] [nome dell'addestramento]"
        )
        print(
            f"Senza argomenti cerca: "
            f"{breve(DATASETS_DIR / DEFAULT_DATASET / 'data.yaml')}"
        )
        print(
            "Senza il secondo argomento si usa il nome "
            "della cartella del dataset."
        )
        sys.exit(1)

    run_name = (
        sys.argv[2]
        if len(sys.argv) > 2
        else data_path.parent.name
    )
    checkpoint = RUNS_DIR / run_name / "weights" / "last.pt"

    if not checkpoint.is_file():
        print(
            f"Checkpoint da riprendere non trovato: "
            f"{breve(checkpoint)}"
        )

        disponibili = addestramenti_ripredibili()

        if disponibili:
            print(
                "Addestramenti che si possono riprendere: "
                f"{', '.join(disponibili)}"
            )
        else:
            print(
                "Non c'è nessun addestramento da riprendere sotto "
                f"{breve(RUNS_DIR)}"
            )

        sys.exit(1)

    print(f"Dataset: {breve(data_path)}", flush=True)
    print(f"Si riprende da: {breve(checkpoint)}", flush=True)

    freeze_support()
    set_start_method("spawn", force=True)

    process = Process(
        target=train,
        args=(checkpoint, data_path),
    )
    process.start()
    process.join()

    sys.exit(process.exitcode)
