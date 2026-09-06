import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drone.flight.flight_loop import main

if __name__ == "__main__":
    main()
