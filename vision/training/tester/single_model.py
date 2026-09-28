import sys
from pathlib import Path

import cv2
from ultralytics import YOLO

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
BASE_DIR = Path(__file__).resolve().parents[3]

IMAGE_WIDTH = 640
IMAGE_HEIGHT = 480
CONFIDENCE = 0.5
BOX_COLOR = (0, 0, 255)
WINDOW_TITLE = "Prova di un modello"


def breve(percorso):
    percorso = Path(percorso).resolve()
    try:
        return str(percorso.relative_to(BASE_DIR))
    except ValueError:
        return str(percorso)


def modelli_disponibili():
    if not MODELS_DIR.is_dir():
        return []
    return sorted(d.name for d in MODELS_DIR.iterdir() if (d / "weights" / "best.pt").is_file())


def trova_pesi(nome):
    indicato = Path(nome).expanduser()
    if indicato.is_file():
        return indicato
    for base in (indicato, MODELS_DIR / indicato):
        candidato = base / "weights" / "best.pt"
        if candidato.is_file():
            return candidato
    return None


def _ensure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main(nome):
    _ensure_utf8_console()
    model_path = trova_pesi(nome)
    if model_path is None:
        print(f"Pesi non trovati per {nome}")
        print("Uso: python single_model.py [nome del modello | percorso dei pesi .pt]")
        print("Senza argomenti usa il primo modello disponibile.")
        disponibili = modelli_disponibili()
        if disponibili:
            print(f"Modelli disponibili: {', '.join(disponibili)}")
        else:
            print(f"Nessun modello con i pesi best.pt sotto {breve(MODELS_DIR)}")
        return 1

    model_name = model_path.parents[1].name
    model = YOLO(model_path)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Webcam non disponibile.")
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, IMAGE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, IMAGE_HEIGHT)

    print(f"Modello caricato: {model_name}")
    print("Per uscire premi 'q' o chiudi la finestra del video.")

    esito = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Il flusso della webcam si è interrotto.")
                esito = 1
                break

            results = model(frame, verbose=False, conf=CONFIDENCE)

            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])
                    label = f"{model.names[cls]} {conf:.2f}"

                    cv2.rectangle(frame, (x1, y1), (x2, y2), BOX_COLOR, 4)
                    cv2.putText(frame, label, (x1, max(y1 - 10, 20)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, BOX_COLOR, 3)

            cv2.imshow(WINDOW_TITLE, frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return esito


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main(sys.argv[1]))

    disponibili = modelli_disponibili()
    if not disponibili:
        print(f"Nessun modello con i pesi best.pt sotto {breve(MODELS_DIR)}")
        print("Uso: python single_model.py [nome del modello | percorso dei pesi .pt]")
        print("Senza argomenti usa il primo modello disponibile.")
        sys.exit(1)

    print(f"Nessun modello indicato: si usa {disponibili[0]}")
    sys.exit(main(disponibili[0]))
