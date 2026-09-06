import logging

import math

from pathlib import Path


LOGGER = logging.getLogger(__name__)


class ObjectDetector:
    def __init__(self, model_path: str, conf: float = 0.5, imgsz: int = 640, device="cpu"):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ImportError(
                "Per usare il detector devi installare ultralytics: pip install ultralytics"
            ) from exc

        model_path_obj = Path(model_path)
        if not model_path_obj.is_file():
            raise FileNotFoundError(f"Modello YOLO non trovato: {model_path}")

        self.model = YOLO(str(model_path_obj))

        self.conf = conf
        self.imgsz = imgsz
        self.device = device

        LOGGER.info("YOLO caricato da: %s", model_path_obj)

    @staticmethod
    def _tensor_to_python(value):
        if value is None:
            return None

        if hasattr(value, "detach"):
            value = value.detach()

        if hasattr(value, "cpu"):
            value = value.cpu()

        if hasattr(value, "tolist"):
            return value.tolist()

        return value

    def _get_label(self, cls: int) -> str:
        names = self.model.names

        if isinstance(names, dict):
            return str(names.get(cls, cls))

        if names is not None and 0 <= cls < len(names):
            return str(names[cls])

        return str(cls)

    def detect(self, frame):
        if frame is None:
            return None, []

        try:
            results = self.model(
                frame,
                conf=self.conf,
                imgsz=self.imgsz,
                verbose=False,
                device=self.device,
            )
        except Exception:
            LOGGER.exception("Errore durante il riconoscimento YOLO.")
            raise

        if not results:
            return frame, []

        result = results[0]
        detections = []

        frame_height, frame_width = frame.shape[:2]

        if result.boxes is not None:
            for box in result.boxes:
                xyxy = self._tensor_to_python(box.xyxy[0])
                conf = self._tensor_to_python(box.conf[0])
                cls = self._tensor_to_python(box.cls[0])

                if xyxy is None or conf is None or cls is None:
                    continue

                if not isinstance(xyxy, (list, tuple)) or len(xyxy) != 4:
                    LOGGER.warning("Riquadro YOLO in formato inatteso: %r", xyxy)
                    continue

                if not all(math.isfinite(v) for v in xyxy):
                    LOGGER.warning("Riquadro YOLO con coordinate non valide: %r", xyxy)
                    continue

                x1, y1, x2, y2 = map(int, xyxy)

                x1 = max(0, min(frame_width - 1, x1))
                y1 = max(0, min(frame_height - 1, y1))
                x2 = max(0, min(frame_width - 1, x2))
                y2 = max(0, min(frame_height - 1, y2))

                if x2 <= x1 or y2 <= y1:
                    LOGGER.warning(
                        "Riquadro YOLO senza area dopo la correzione ai bordi dell'immagine: (%s, %s, %s, %s)",
                        x1,
                        y1,
                        x2,
                        y2,
                    )
                    continue

                conf = float(conf)
                cls = int(cls)

                detections.append(
                    {
                        "label": self._get_label(cls),
                        "confidence": conf,
                        "bbox": (x1, y1, x2, y2),
                    }
                )

        return frame, detections
