# CLAUDE.md — MathOCR

App local de **OCR de matemáticas**: recortas una zona de la pantalla y la convierte a texto/LaTeX.
Es la versión vigente del motor OCR (sucede a `Tractor_old/`, que es la versión antigua de referencia).

## Estructura
- `SimpleApp/` — la app de usuario (PyQt, bandeja del sistema): `gui.py`, `main.py`, `snipper.py`
  (captura de región), `ocr_engine.py`. Se lanza con `run_mathocr.vbs` (en segundo plano).
- `Tractor/` — el pipeline de procesamiento (sin PyQt): `ocr_engine.py`, `batch_processor.py` (lotes),
  `native_extractor.py` (extracción híbrida para páginas digitales), `hallucination_filter.py`
  (descarta blobs basura de gráficos decorativos; ON por defecto), `format_cleaner.py` (limpieza
  determinista de SOLO formato), `llm_cleaner.py` (limpieza de formato opcional con LLM/Ollama).
- `mathocr_entry/` — paquete-puente con los dos entrypoints (`app.py` = GUI, `batch.py` = lotes).
  **Asume install editable** (`pip install -e .`): localiza `SimpleApp/`/`Tractor/` por ruta del repo.

## Cómo correr
- **Dos ejecutables independientes** (definidos en `pyproject.toml`, instalados con `pip install -e .`):
  - `MathOCRSimple` (gui-script → `venv\Scripts\MathOCRSimple.exe`, sin consola) — GUI de snip/bandeja
    (Ctrl+Alt+S). También vía `SimpleApp/run_mathocr.vbs` o `python SimpleApp/main.py`.
  - `MathOCRFull <carpeta_o_pdf> [--out <dir>] [--raw] [--clean] [--clean-llm]` (console-script) —
    lotes PDF → Markdown/LaTeX. Filtro anti-alucinación ON por defecto (`--raw` lo apaga = salida
    cruda). `--clean` = limpieza determinista solo-formato (off por defecto); `--clean-llm` = pasada
    extra con LLM, opt-in. Lanzar el batch NO carga PyQt.
- Lo instala: `venv\Scripts\python.exe -m pip install -e .` (reinstalar tras cambiar entrypoints).
- Python 3.12 en `venv/` (la GUI usa `pythonw.exe`; el código tolera `sys.stdout = None`).

## Notas
- **Pipeline híbrido (digital vs escaneado):** `batch_processor` clasifica cada página. Si tiene
  capa de texto (≈94% del material de Canvas) usa `native_extractor.py`: **prosa y tablas NATIVAS**
  del PDF (PyMuPDF `get_text`/`find_tables`, calidad perfecta sin OCR) + **fórmulas display por
  OCR→LaTeX**, todo reordenado con **detección de 2 columnas**. Si es escaneada, OCR completo. Hay
  fallback a OCR si la extracción nativa falla. Limitaciones v1: las fórmulas **inline** (no-display)
  quedan linealizadas en el texto nativo; el orden de fórmulas en slides mixtos puede ser imperfecto;
  las filas-pie de tablas se duplican por columna; si una página digital tiene el CUERPO dentro de
  una imagen (infografía, captura), esa imagen no se OCR-ea (solo sale el título nativo).
  Las fórmulas que el filtro anti-alucinación marca como basura (logos) se descartan ANTES de
  registrar su caja, para que no excluyan el texto nativo que hay debajo.
- **Fallas medidas en Canvas_MD y cómo se cubren (23/10/2026, respaldo previo en `_backup_2026-10-23/`):**
  - *CMEX sin ToUnicode* (PDFs LaTeX viejos: `∫` salía como línea `R`, paréntesis grandes `¡ ¢`):
    `native_extractor._regiones_cmex_rotas` detecta spans CMEX con letras, fusiona los bloques
    vecinos en regiones y las OCR-ea como texto+fórmula. Por bloque (≈1 línea) mezclaba
    vecinos: el ∫ invade la línea de al lado. Prioridad (24/10): una región DENTRO de una fórmula
    display se descarta (la display ya OCR-ea la ecuación entera; la región, solo los bloques con
    ∫, daba fragmentos duplicados); una display dentro de una región se descarta. Además, una
    display casi contenida (>60%) en otra más grande se descarta (MFD detecta el Σ suelto y la
    ecuación entera). Límite que queda: una display de muchas líneas apiladas (8 ecuaciones en
    una caja) sale con errores sueltos del MFR (`\int_0^t` por `\int_0^b`).
  - *Notas manuscritas de iPad* (pautas): trazo vectorial (≥500 `get_cdrawings`) + texto en
    fuentes de sistema de Apple (`.SFUI…`, su reconocimiento de escritura, casi ilegible) →
    `es_manuscrita`. No se re-OCR-ea (es letra a mano): se marca la página.
  - `format_cleaner` (`--clean`): combina acentos sueltos de TeX (`C´alculo`, ` ´area`, `n˜o`),
    expande ligaduras `ﬁ`, quita tablas fantasma de `find_tables` (grillas de gráficos con <1/5
    de celdas llenas: filas `|||||`, `Col1|Col2…`) y descarta NUL. Bugs corregidos: el inline
    `$…$` cruzaba líneas (entre dos precios protegía párrafos enteros) y un `$` suelto antes de
    un `$$…$$` anidaba placeholders y la fórmula se perdía (`\x000\x00`).
  - Frontmatter: `source_path` (relativo a la carpeta de entrada, nombre real en disco) y
    `alertas:` → `solo_imagen` (sin texto, casi siempre una foto; se escribe
    `_[Página sin texto: solo imagen]_`), `manuscrita` y `ocr_completo` (escaneada o fallback).
  - Las páginas "vacías" de Mitología NO eran falla del OCR: son fotos sin texto.
- **OCR de texto en español:** `Tractor/ocr_engine.py` llama a `Pix2Text.from_config` con
  `languages=('en','es')` → usa **EasyOCR** (alfabeto latino, respeta acentos) + corrector
  ortográfico español integrado. Mejora mucho la prosa sin tocar fórmulas. (La GUI de SimpleApp
  todavía usa el default chino de cnocr.)
- **GPU:** hay `onnxruntime-directml`, pero la inyección DirectML (`_inject_directml`) es no-op
  contra pix2text 1.1.6 → en la práctica corre en **CPU**. La iGPU (Radeon 860M) no es buen lever;
  la velocidad real está en `--workers` (todo es CPU-bound). EasyOCR añade costo de CPU.
- **Modelo de fórmulas (MFR):** se usa `mfr-1.5` (el mejor MFR local-gratis de pix2text; los
  `mfr-pro`/`mfr-plus` son de pago/gated). Evaluado y **descartado UniMERNet-base** (jun-2026):
  mejor en slides limpios (índice de raíz, LaTeX estándar) pero MÁS frágil en contenido real
  variado (alucina cajas anidadas, bucles de repetición) y exige venv aislada por choque de
  `transformers` → no compensa (2 procesos + 3-6× más lento). Beam search sobre mfr-1.5 tampoco
  ayuda. **DPI óptimo 150** (subirlo no mejora calidad; 300 la degrada y alucina).
- `ocr_init_error.log` registra fallos de inicialización del motor.

## graphify (índice de código)
Este proyecto tiene un grafo de conocimiento en `graphify-out/` (~94 nodos, 8 comunidades).
- Para preguntas sobre el código, usa primero: `graphify query "<pregunta>"` (BFS sobre el grafo),
  `graphify path "<A>" "<B>"` (relación entre dos nodos), `graphify explain "<X>"` (un nodo y sus vecinos).
  Devuelven un subgrafo acotado — más barato que leer todo o hacer grep.
- `graphify-out/GRAPH_REPORT.md` para una vista arquitectónica amplia.
- Tras cambiar código: `graphify update .` (AST, sin costo de API; parado en esta carpeta).
