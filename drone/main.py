import os
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RADICE)
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from drone.flight.flight_loop import main


if __name__ == "__main__":
    main()
