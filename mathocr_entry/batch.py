"""Entrypoint `mathocr-batch` — CLI de lotes PDF -> Markdown/LaTeX (Tractor).

Independiente de la GUI: solo inserta Tractor/ en sys.path e importa el
pipeline de lotes. NO importa PyQt ni nada de SimpleApp/. Ver nota de install
editable en mathocr_entry/__init__.py.
"""

import os
import sys

from . import _repo_root


def main():
    tractor_dir = os.path.join(_repo_root(), "Tractor")
    sys.path.insert(0, tractor_dir)
    import batch_processor  # Tractor/batch_processor.py
    try:
        return batch_processor.main()
    except KeyboardInterrupt:
        print("\n🛑 Cancelado. Los .md ya completados se conservan; re-ejecuta el "
              "MISMO comando para continuar (omite lo hecho).")
        return 130


if __name__ == "__main__":
    main()
