"""Suddivisione di un dataset YOLO in train, validation e test.

Lo script carica il contenuto della cartella ``train`` di un dataset YOLO e lo
suddivide in tre sottoinsiemi:

- 80% per l'addestramento;
- 10% per la validazione;
- 10% per il test.

La suddivisione viene eseguita tramite ``supervision.DetectionDataset`` e usa
un seme fisso, così da ottenere gli stessi gruppi a ogni esecuzione.

Prima del salvataggio vengono verificati:
- la presenza del file ``data.yaml``;
- lo stato della cartella di destinazione, che deve essere vuota;
- la presenza di immagini nel dataset;
- l'assenza di gruppi vuoti;
- la presenza di almeno un'annotazione in ciascun gruppo.

Il dataset sorgente non viene modificato.
"""

import os
import sys
from pathlib import Path

import supervision as sv


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


_ensure_utf8_console()

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parents[3]
DATASET_DIR = SCRIPT_DIR / "dataset"
OUTPUT_DIR = SCRIPT_DIR / "split"

# Seme usato per rendere riproducibile la suddivisione del dataset.
SEED = 42


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


def elenco(nomi):
    """Converte una sequenza di nomi in un elenco leggibile in italiano."""
    if len(nomi) == 1:
        return nomi[0]

    return ", ".join(nomi[:-1]) + " e " + nomi[-1]


dataset_dir = (
    Path(sys.argv[1]).expanduser()
    if len(sys.argv) > 1
    else DATASET_DIR
)
output_dir = (
    Path(sys.argv[2]).expanduser()
    if len(sys.argv) > 2
    else OUTPUT_DIR
)

# Il file data.yaml identifica la radice del dataset YOLO da suddividere.
if not (dataset_dir / "data.yaml").is_file():
    print(
        f"Dataset non trovato: manca "
        f"{breve(dataset_dir / 'data.yaml')}"
    )
    print(
        "Uso: python split.py "
        "[cartella del dataset] [cartella di destinazione]"
    )
    print("Senza argomenti usa:")
    print(f"  dataset:      {breve(DATASET_DIR)}")
    print(f"  destinazione: {breve(OUTPUT_DIR)}")
    sys.exit(1)

if destinazione_occupata(output_dir):
    print(
        f"La cartella di destinazione non è vuota: "
        f"{breve(output_dir)}"
    )
    print(
        "Rimuovila o indicane un'altra: rieseguendo, il nuovo dataset "
        "si sommerebbe a quello vecchio."
    )
    sys.exit(1)

# Il dataset sorgente viene letto dalle sole cartelle train/images e
# train/labels. I tre nuovi sottoinsiemi vengono creati successivamente.
ds = sv.DetectionDataset.from_yolo(
    images_directory_path=str(dataset_dir / "train" / "images"),
    annotations_directory_path=str(dataset_dir / "train" / "labels"),
    data_yaml_path=str(dataset_dir / "data.yaml"),
)

if len(ds) == 0:
    print(
        f"Nessuna immagine trovata in "
        f"{breve(dataset_dir / 'train' / 'images')}: "
        "niente da suddividere."
    )
    sys.exit(1)

# Prima separazione: 80% train e 20% restante.
ds_train, ds_resto = ds.split(
    split_ratio=0.8,
    shuffle=True,
    random_state=SEED,
)

# Seconda separazione: il 20% restante viene diviso in parti uguali,
# ottenendo complessivamente 10% validation e 10% test.
ds_valid, ds_test = ds_resto.split(
    split_ratio=0.5,
    shuffle=True,
    random_state=SEED,
)

gruppi = (
    ("addestramento", ds_train),
    ("validazione", ds_valid),
    ("prova", ds_test),
)

# Con dataset molto piccoli uno o più gruppi potrebbero risultare vuoti.
vuoti = [
    nome
    for nome, gruppo in gruppi
    if len(gruppo) == 0
]

if vuoti:
    immagini = "1 immagine" if len(ds) == 1 else f"{len(ds)} immagini"
    quali = "vuoto il gruppo" if len(vuoti) == 1 else "vuoti i gruppi"

    print(
        f"Con {immagini} la suddivisione lascia {quali} "
        f"di {elenco(vuoti)}."
    )
    print(
        "Servono più immagini o proporzioni diverse. "
        "Non è stato scritto niente."
    )
    sys.exit(1)

# Ogni sottoinsieme deve contenere almeno un oggetto annotato. Un gruppo
# composto soltanto da immagini di sfondo non consentirebbe una valutazione
# significativa delle prestazioni del modello.
senza_annotazioni = [
    nome
    for nome, gruppo in gruppi
    if not any(len(det) > 0 for det in gruppo.annotations.values())
]

if senza_annotazioni:
    quali = (
        "Il gruppo"
        if len(senza_annotazioni) == 1
        else "I gruppi"
    )
    verbo = (
        "contiene"
        if len(senza_annotazioni) == 1
        else "contengono"
    )

    print(
        f"{quali} di {elenco(senza_annotazioni)} {verbo} solo immagini "
        "di sfondo, senza annotazioni."
    )
    print(
        "Con questa suddivisione le misure di qualità non avrebbero senso. "
        "Non è stato scritto niente."
    )
    sys.exit(1)

print()
print(
    f"Suddivisione con seme {SEED}: rilanciando lo script "
    "si ottengono gli stessi gruppi."
)
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

print(
    f"Suddivisione completata. "
    f"Il risultato è in {breve(output_dir)}"
)
print()
