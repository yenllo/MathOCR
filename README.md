# MathOCR

OCR de matemáticas para apuntes en español: convierte PDF a **Markdown con las fórmulas en
LaTeX** (`$$…$$`). Trae además una app de bandeja para recortar una zona de la pantalla y
copiarla como LaTeX.

Es el motor de OCR opcional de [canvas-sync-uandes](https://github.com/yenllo/canvas-sync-uandes),
que lo instala solo con `instalar_ocr.bat`. Si llegaste por ahí, no necesitas leer más.

## Qué hace con cada página

- **Página digital** (tiene capa de texto, como la gran mayoría de los PDF de clases): saca la
  prosa y las tablas **directo del PDF**, sin errores de OCR, pasa por OCR **solo las fórmulas
  en display** y reordena todo detectando si va en dos columnas.
- **Página escaneada:** la pasa entera por OCR, texto y fórmulas.
- **Filtro anti-alucinación** (activo por defecto): descarta las "fórmulas" que el modelo
  inventa a partir de logos y gráficos decorativos.
- Cada `.md` lleva un frontmatter con `source_path` y, por página, `alertas:` para avisar
  cuando el resultado es dudoso: `solo_imagen`, `manuscrita` u `ocr_completo`.

Usa [pix2text](https://github.com/breezedeus/Pix2Text) 1.1.6 con el modelo de fórmulas
`mfr-1.5` y EasyOCR para el texto en español. Corre en **CPU**.

## Instalación

Necesitas **Python 3.12** y git. Las versiones exactas están probadas en Windows y fijadas en
[`constraints.txt`](constraints.txt).

```bash
git clone https://github.com/yenllo/MathOCR
```

```bash
cd MathOCR && py -3.12 -m venv venv && venv\Scripts\python -m pip install -e . -c constraints.txt
```

Usa siempre el modo editable (`-e`): los ejecutables encuentran `Tractor/` y `SimpleApp/` por su
ruta dentro de la repo. La instalación ocupa unos 2,5 GB, la mayor parte de PyTorch. La primera
corrida además descarga los modelos.

## Uso

### Lotes: `MathOCRFull`

```bash
venv\Scripts\MathOCRFull "C:\ruta\a\carpeta_con_pdfs" --out "C:\ruta\salida"
```

Recorre la carpeta de forma recursiva y escribe un `.md` por PDF. Si lo vuelves a correr, salta
los que ya tienen su `.md`: puedes cortarlo con `Ctrl+C` y seguir después donde quedó.

| Opción | Qué hace | Por defecto |
|---|---|---|
| `--out`, `-o` | Carpeta de salida | `<entrada>_MD` |
| `--dpi` | Resolución a la que se renderiza cada página (150 es lo óptimo; 300 empeora) | 150 |
| `--cooldown`, `-c` | Pausa entre páginas, en segundos, para que el PC no se caliente | 2.5 |
| `--workers`, `-w` | PDF en paralelo. Cada worker carga su propio modelo: más RAM y un arranque de varios minutos | 1 |
| `--force` | Reprocesa aunque ya exista el `.md` | apagado |
| `--clean` | Limpieza de **solo formato** con reglas fijas, sin IA: acentos sueltos de TeX, ligaduras, tablas fantasma | apagado |
| `--raw` | Apaga el filtro anti-alucinación (deja la salida tal como la entrega el modelo) | apagado |
| `--clean-llm`, `--clean-model` | Pasada extra de formato con un LLM local ([Ollama](https://ollama.com)) | apagado / `phi3` |

### Recorte de pantalla: `MathOCRSimple`

```bash
venv\Scripts\MathOCRSimple
```

Queda en la bandeja del sistema. Con `Ctrl+Alt+S` recortas una zona de la pantalla y se abre
una ventana con el LaTeX, el texto y una vista previa, listos para copiar.

## Estructura

- `Tractor/`: el pipeline de lotes, sin interfaz gráfica.
  - `batch_processor.py`: la línea de comandos y la orquestación.
  - `native_extractor.py`: la extracción para páginas digitales.
  - `ocr_engine.py`: el motor (pix2text).
  - `hallucination_filter.py` y `format_cleaner.py`: el filtro y la limpieza de formato.
  - `llm_cleaner.py`: la pasada opcional con un LLM local.
- `SimpleApp/`: la app de recorte, hecha en PyQt6.
- `mathocr_entry/`: los dos ejecutables. El de lotes no carga PyQt.

## Limitaciones conocidas

- Las fórmulas **dentro de una línea de texto** (no en display) de una página digital quedan
  como texto plano, sin LaTeX.
- Una fórmula en display de muchas líneas apiladas puede salir con errores sueltos.
- Si el contenido de una página digital es una imagen (una infografía, una captura), esa
  imagen no se pasa por OCR.
- No transcribe letra manuscrita: esas páginas salen marcadas con `manuscrita`.
