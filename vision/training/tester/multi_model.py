"""Test simultaneo di più modelli YOLO tramite webcam.

Lo script carica i modelli descritti in ``catalog.json`` e li esegue in
parallelo sullo stesso flusso video.

Per ogni voce del catalogo vengono letti:
- percorso dei pesi;
- etichetta del modello;
- colore usato per le annotazioni.

Ogni modello viene gestito da un thread dedicato. Il frame corrente viene
inviato a tutti i worker, quindi i risultati vengono raccolti e disegnati sulla
stessa immagine.

Se un modello non risponde entro il timeout configurato o genera un'eccezione,
l'esecuzione viene interrotta e l'errore viene segnalato.
"""

import json
import queue
import sys
from pathlib import Path
from threading import Thread

import cv2
from ultralytics import YOLO


DEFAULT_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
BASE_DIR = Path(__file__).resolve().parents[3]
CATALOG_NAME = "catalog.json"

IMAGE_WIDTH = 640
IMAGE_HEIGHT = 480
CONFIDENCE = 0.5
INFERENCE_TIMEOUT_SEC = 10.0
JOIN_TIMEOUT_SEC = 1.0
WINDOW_TITLE = "Prova di modelli multipli"
DEFAULT_COLOR = (0, 255, 0)


def breve(percorso):
    """Restituisce un percorso relativo alla radice del progetto, se possibile."""
    percorso = Path(percorso).resolve()

    try:
        return str(percorso.relative_to(BASE_DIR))
    except ValueError:
        return str(percorso)


def read_color(raw):
    """Restituisce un colore BGR valido oppure il colore predefinito."""
    if (
        isinstance(raw, list)
        and len(raw) == 3
        and all(
            isinstance(c, int)
            and not isinstance(c, bool)
            and 0 <= c <= 255
            for c in raw
        )
    ):
        return tuple(raw)

    return DEFAULT_COLOR


def load_catalog(models_dir):
    """Carica dal catalogo i modelli che dispongono di pesi utilizzabili."""
    catalog_path = models_dir / CATALOG_NAME

    try:
        catalog = json.loads(
            catalog_path.read_text(encoding="utf-8")
        )
    except OSError:
        print(
            f"Catalogo dei modelli non leggibile: "
            f"{breve(catalog_path)}"
        )
        return [], True
    except ValueError as exc:
        print(
            f"Il catalogo dei modelli non è JSON valido: "
            f"{breve(catalog_path)}"
        )
        print(f"  {exc}")
        return [], True

    voci = catalog.get("models") if isinstance(catalog, dict) else None

    if not isinstance(voci, list):
        print(
            f"Nel catalogo dei modelli manca la lista 'models': "
            f"{breve(catalog_path)}"
        )
        return [], True

    models = []

    for entry in voci:
        if not isinstance(entry, dict):
            continue

        weights = entry.get("weights")

        if not isinstance(weights, str) or not weights:
            continue

        path = models_dir / weights

        if not path.is_file():
            print(
                f"Modello saltato, pesi non trovati: "
                f"{breve(path)}"
            )
            continue

        label = entry.get("label")

        models.append(
            {
                "label": (
                    label
                    if isinstance(label, str) and label
                    else Path(weights).parent.parent.name
                ),
                "path": path,
                "color": read_color(entry.get("color")),
            }
        )

    return models, False


class ModelWorker(Thread):
    """Esegue un singolo modello YOLO in un thread dedicato."""

    def __init__(self, model_path, color, label):
        """Carica il modello e inizializza le code di frame e risultati."""
        super().__init__(daemon=True)

        self.model = YOLO(model_path)
        self.color = color
        self.label = label
        self.running = True

        # Le code contengono un solo elemento: ogni worker elabora quindi
        # un frame alla volta e restituisce il relativo risultato.
        self._frames = queue.Queue(maxsize=1)
        self._results = queue.Queue(maxsize=1)

    def run(self):
        """Elabora i frame ricevuti finché il worker resta attivo."""
        while self.running:
            try:
                frame = self._frames.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                self._results.put(
                    self.model(
                        frame,
                        verbose=False,
                        conf=CONFIDENCE,
                    )
                )
            except Exception as exc:
                self._results.put(exc)

    def submit(self, frame):
        """Invia un frame al modello."""
        self._frames.put(frame)

    def collect(self):
        """Restituisce il risultato del modello entro il timeout previsto."""
        try:
            return self._results.get(
                timeout=INFERENCE_TIMEOUT_SEC
            )
        except queue.Empty:
            return None


def draw(frame, results, color, names):
    """Disegna bounding box, classe e confidenza sul frame."""
    for result in results:
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            label = f"{names[int(box.cls[0])]} {conf:.2f}"

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                color,
                3,
            )
            cv2.putText(
                frame,
                label,
                (x1, max(y1 - 10, 15)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )


def annotate(frame, workers):
    """Raccoglie i risultati dei worker e annota il frame corrente."""
    for worker in workers:
        results = worker.collect()

        if results is None:
            return (
                f"Nessuna risposta dal modello {worker.label} "
                f"entro {INFERENCE_TIMEOUT_SEC:.0f} s."
            )

        if isinstance(results, Exception):
            return (
                f"Errore nel modello {worker.label}: "
                f"{results}"
            )

        draw(
            frame,
            results,
            worker.color,
            worker.model.names,
        )

    return None


def _ensure_utf8_console() -> None:
    """Configura stdout e stderr in UTF-8 quando il runtime lo consente."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)

        if reconfigure is None:
            continue

        try:
            reconfigure(
                encoding="utf-8",
                errors="replace",
            )
        except (ValueError, OSError):
            pass


def main(models_dir):
    """Carica i modelli e avvia il test multi-modello tramite webcam."""
    _ensure_utf8_console()

    models, segnalato = load_catalog(models_dir)

    if not models:
        if not segnalato:
            print(
                "Nel catalogo non c'è nessun modello utilizzabile: "
                f"{breve(models_dir / CATALOG_NAME)}"
            )

        print(
            "Uso: python multi_model.py "
            "[cartella dei modelli]"
        )
        print(
            f"Senza argomenti usa: "
            f"{breve(DEFAULT_MODELS_DIR)}"
        )
        return 1

    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Webcam non disponibile.")
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, IMAGE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, IMAGE_HEIGHT)

    workers = [
        ModelWorker(
            model["path"],
            model["color"],
            model["label"],
        )
        for model in models
    ]

    for worker in workers:
        worker.start()

    print(
        f"Modelli caricati: "
        f"{', '.join(worker.label for worker in workers)}"
    )
    print(
        "Per uscire premi 'q' o chiudi la finestra del video."
    )

    esito = 0

    try:
        while True:
            ret, frame = cap.read()

            if not ret:
                print(
                    "Il flusso della webcam si è interrotto."
                )
                esito = 1
                break

            # Ogni modello riceve una copia dello stesso frame.
            for worker in workers:
                worker.submit(frame.copy())

            errore = annotate(frame, workers)

            if errore:
                print(errore)
                esito = 1
                break

            cv2.imshow(WINDOW_TITLE, frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            if (
                cv2.getWindowProperty(
                    WINDOW_TITLE,
                    cv2.WND_PROP_VISIBLE,
                )
                < 1
            ):
                break

    finally:
        for worker in workers:
            worker.running = False

        for worker in workers:
            worker.join(timeout=JOIN_TIMEOUT_SEC)

        cap.release()
        cv2.destroyAllWindows()

    return esito


if __name__ == "__main__":
    cartella = (
        Path(sys.argv[1]).expanduser()
        if len(sys.argv) > 1
        else DEFAULT_MODELS_DIR
    )

    sys.exit(main(cartella))
    