import sys
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parents[2]
RUNS_DIR = SCRIPT_DIR / "models"
MODELS_DIR = SCRIPT_DIR.parents[1] / "models"

REQUIRED_COLUMNS = (
    'epoch',
    'train/box_loss', 'train/cls_loss', 'train/dfl_loss',
    'val/box_loss', 'val/cls_loss', 'val/dfl_loss',
    'metrics/mAP50(B)', 'metrics/mAP50-95(B)',
)


def breve(percorso):
    percorso = Path(percorso).resolve()
    try:
        return str(percorso.relative_to(BASE_DIR))
    except ValueError:
        return str(percorso)


def leggi_results(csv_path):
    prime = csv_path.read_bytes().decode("utf-8", "replace").splitlines()[:1]
    if prime and ";" in prime[0]:
        return pd.read_csv(csv_path, sep=";", decimal=",")
    return pd.read_csv(csv_path)


def plot_training_results(csv_path):
    df = leggi_results(csv_path)
    df.columns = [c.strip() for c in df.columns]

    mancanti = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if mancanti:
        print(f"Colonne mancanti in {breve(csv_path)}: {', '.join(mancanti)}")
        print("Serve il results.csv scritto da un addestramento Ultralytics.")
        return 1

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 12))
    fig.suptitle(f"Addestramento: {csv_path.parent.name}", fontsize=15)

    train_loss = df['train/box_loss'] + df['train/cls_loss'] + df['train/dfl_loss']
    val_loss = df['val/box_loss'] + df['val/cls_loss'] + df['val/dfl_loss']
    ax1.plot(df['epoch'], train_loss, label='Loss addestramento', color='blue', lw=2)
    ax1.plot(df['epoch'], val_loss, label='Loss validazione', color='orange', linestyle='--', lw=2)
    ax1.set_title('Andamento delle loss (addestramento vs validazione)', fontsize=14)
    ax1.set_xlabel('Epoca')
    ax1.set_ylabel('Somma delle loss')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2.plot(df['epoch'], df['metrics/mAP50(B)'], label='mAP@50', color='green', lw=2)
    ax2.plot(df['epoch'], df['metrics/mAP50-95(B)'], label='mAP@50-95', color='red', lw=2)
    ax2.set_title('Evoluzione della precisione (mAP)', fontsize=14)
    ax2.set_xlabel('Epoca')
    ax2.set_ylabel('mAP')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()
    return 0


def ultimo_results_csv():
    trovati = [
        percorso
        for base in (RUNS_DIR, MODELS_DIR)
        if base.is_dir()
        for percorso in base.glob("*/results.csv")
    ]
    if not trovati:
        return None
    return max(trovati, key=lambda percorso: percorso.stat().st_mtime)


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
    if len(sys.argv) > 1:
        results_path = Path(sys.argv[1]).expanduser()
        if results_path.is_dir():
            results_path = results_path / "results.csv"
    else:
        results_path = ultimo_results_csv()

    if results_path is None or not results_path.is_file():
        if results_path is not None:
            print(f"File dei risultati non trovato: {breve(results_path)}")
        print("Uso: python plot_results.py [cartella dell'addestramento | results.csv]")
        print("Senza argomenti prende il results.csv più recente sotto:")
        print(f"  banco di prova: {breve(RUNS_DIR)}")
        print(f"  in servizio:    {breve(MODELS_DIR)}")
        sys.exit(1)

    sys.exit(plot_training_results(results_path))
