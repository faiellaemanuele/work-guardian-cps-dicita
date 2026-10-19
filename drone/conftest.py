"""Configurazione condivisa usata da pytest per i test del package drone."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
