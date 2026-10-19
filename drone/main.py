"""Punto di ingresso dell'applicazione di volo. Prepara l'ambiente e avvia il ciclo principale."""

import os
import sys

# Radice del progetto: consente di eseguire direttamente ``python drone/main.py``.
RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)

# Evita il banner informativo mostrato da Pygame durante l'importazione.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from drone.flight.flight_loop import main


if __name__ == "__main__":
    main()
