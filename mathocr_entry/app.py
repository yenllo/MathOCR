"""Entrypoint `mathocr` — lanza la GUI de snip/bandeja (SimpleApp).

Independiente del batch: solo inserta SimpleApp/ en sys.path e importa la GUI.
Nunca toca Tractor/. Ver nota de install editable en mathocr_entry/__init__.py.
"""

import os
import sys

from . import _repo_root


def main():
    simpleapp_dir = os.path.join(_repo_root(), "SimpleApp")
    sys.path.insert(0, simpleapp_dir)
    import main as gui  # SimpleApp/main.py
    return gui.main()


if __name__ == "__main__":
    main()
