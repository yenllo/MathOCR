"""Paquete-puente con los dos entrypoints de MathOCR.

ASUME INSTALACIÓN EDITABLE (`pip install -e .`): este paquete localiza
`SimpleApp/` y `Tractor/` por ruta relativa al repositorio, por lo que el
código debe permanecer en su sitio. Un install NO editable (wheel) movería
este paquete fuera del repo y rompería esas rutas.

- `mathocr_entry.app:main`   -> GUI de snip/bandeja (solo importa SimpleApp/, PyQt).
- `mathocr_entry.batch:main` -> CLI de lotes (solo importa Tractor/, sin PyQt).

Cada entrypoint inserta SOLO su carpeta en sys.path, de modo que lanzar uno
nunca arrastra las dependencias del otro.
"""

import os


def _repo_root():
    """Raíz del repo (carpeta padre de este paquete)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
