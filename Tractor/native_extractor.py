"""Extracción híbrida para páginas DIGITALES (con capa de texto).

La prosa y las tablas se toman NATIVAS del PDF (calidad perfecta, sin OCR);
solo las fórmulas DISPLAY se OCR-ean a LaTeX (en el text-layer salen
linealizadas e inservibles). Todo se reordena con detección de columnas.

Las páginas escaneadas (sin capa de texto) las maneja el caller con OCR
completo. Si algo falla aquí, el caller también cae a OCR.

Coordenadas: pix2text trabaja en píxeles de la imagen renderizada a `dpi`;
PyMuPDF (get_text/find_tables) en puntos PDF (72 dpi). Convertimos todo a
puntos para comparar regiones.
"""

import re

# CMEX (símbolos grandes de TeX) no tiene letras: si un span CMEX trae letras o
# latin-1, el PDF no tiene ToUnicode y el glifo salió con su código crudo
# (∫ -> 'R', paréntesis grandes -> '¡ ¢'). Pasa en PDFs LaTeX viejos.
_CMEX_ROTO = re.compile(r"[A-Za-z¡-ÿ]")


def _bloques_cmex_rotos(page):
    """Rects (pt) de los bloques de texto con glifos CMEX sin ToUnicode."""
    rects = []
    for b in page.get_text("dict")["blocks"]:
        if any("CMEX" in s["font"].upper() and _CMEX_ROTO.search(s["text"])
               for l in b.get("lines", []) for s in l["spans"]):
            rects.append(tuple(b["bbox"]))
    return rects


def _regiones_cmex_rotas(page, margen=6):
    """Fusiona los bloques rotos vecinos (a <margen pt) en regiones. Cada bloque
    es ~1 línea, y en listas apretadas el ∫ invade la línea de al lado: OCR-ear
    línea por línea mezcla vecinos; la lista entera de una vez sale limpia.
    ponytail: una sola pasada ordenada por y; si alguna región quedara partida,
    repetir la fusión hasta que no cambie."""
    regiones = []
    for r in sorted(_bloques_cmex_rotos(page), key=lambda r: r[1]):
        for i, g in enumerate(regiones):
            if (r[1] - margen <= g[3] and r[3] + margen >= g[1]
                    and r[0] - margen <= g[2] and r[2] + margen >= g[0]):
                regiones[i] = (min(g[0], r[0]), min(g[1], r[1]), max(g[2], r[2]), max(g[3], r[3]))
                break
        else:
            regiones.append(r)
    return regiones


def is_digital(page, min_chars=20):
    """True si la página tiene capa de texto usable (y sin rotación)."""
    try:
        return page.rotation == 0 and len(page.get_text().strip()) >= min_chars
    except Exception:
        return False


def es_manuscrita(page, min_trazos=500):
    """Nota manuscrita de iPad (pautas de ayudantía): el trazo es vectorial y la
    capa de texto es el reconocimiento de escritura de Apple (fuentes de sistema
    '.SFUI…'), que sale casi ilegible. No se re-OCR-ea (es letra a mano): se marca."""
    try:
        if len(page.get_cdrawings()) < min_trazos:
            return False
        return any(s["font"].startswith(".") for b in page.get_text("dict")["blocks"]
                   for l in b.get("lines", []) for s in l["spans"])
    except Exception:
        return False


def _box_px_to_pt(box_px, dpi):
    """box pix2text [4,2] (px) -> (x0,y0,x1,y1) en puntos."""
    f = 72.0 / dpi
    xs = [p[0] for p in box_px]
    ys = [p[1] for p in box_px]
    return (min(xs) * f, min(ys) * f, max(xs) * f, max(ys) * f)


def _overlap_frac(a, b):
    """Fracción del área de 'a' cubierta por su intersección con 'b'."""
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    return inter / area


def extract_page_hybrid(page, pil_image, engine, dpi, strip_junk=True):
    """Devuelve el Markdown de una página digital (prosa nativa + tablas
    nativas + fórmulas OCR), ordenado por columnas. '' si no hay contenido."""
    tfo = engine.p2t.text_formula_ocr
    W = page.rect.width
    w_px, h_px = pil_image.size

    # ── 1) Fórmulas DISPLAY (isolated): MFD + OCR -> LaTeX ──────────────
    formula_elems, formula_boxes = [], []
    mfd_outs = tfo.mfd(pil_image.copy(), resized_shape=(int(h_px * 768 / w_px), 768))
    for info in mfd_outs:
        if info.get("type") != "isolated":
            continue
        b = info["box"]
        crop = pil_image.crop((int(b[0][0]), int(b[0][1]), int(b[2][0]), int(b[2][1])))
        if crop.width < 16 or crop.height < 12:
            continue
        res = tfo.latex_ocr.recognize(crop)
        latex = (res["text"] if isinstance(res, dict) else res).strip()
        if not latex:
            continue
        md = f"$$\n{latex}\n$$"
        if strip_junk:
            from hallucination_filter import strip_hallucinations
            md = strip_hallucinations(md)
        if not md:
            # Logo/gráfico decorativo: se descarta ANTES de registrar su caja, si
            # no se "roba" el texto nativo que hay debajo (títulos, viñetas).
            continue
        rect = _box_px_to_pt(b, dpi)
        formula_boxes.append(rect)
        formula_elems.append({"rect": rect, "md": md})
    # MFD a veces detecta un trozo de la ecuación (el Σ con su índice) Y la
    # ecuación entera: el trozo sale como fórmula suelta duplicada. Se queda la grande.
    def _area(r):
        return (r[2] - r[0]) * (r[3] - r[1])
    formula_elems = [e for e in formula_elems
                     if not any(o is not e and _area(o["rect"]) > _area(e["rect"])
                                and _overlap_frac(e["rect"], o["rect"]) > 0.6
                                for o in formula_elems)]

    # ── 2) Tablas nativas (find_tables) ────────────────────────────────
    table_elems, table_boxes = [], []
    try:
        for t in page.find_tables().tables:
            if t.row_count < 2 or t.col_count < 2:
                continue  # filtra falsos positivos (no es una rejilla real)
            md = t.to_markdown().strip()
            if md:
                table_elems.append({"rect": tuple(t.bbox), "md": md})
                table_boxes.append(tuple(t.bbox))
    except Exception:
        pass

    # ── 2b) Regiones con CMEX roto (fórmulas inline de LaTeX viejo: ∫ -> 'R'):
    #    se OCR-ean como texto+fórmula y reemplazan al texto nativo y a las
    #    fórmulas display que caigan dentro (si no, salen duplicadas). Una
    #    región que cae DENTRO de una display se descarta: la display ya OCR-ea
    #    la ecuación entera, y la región (solo los bloques con ∫) da fragmentos.
    f = dpi / 72.0
    region_elems = []
    for g in _regiones_cmex_rotas(page):
        if any(_overlap_frac(g, fb) > 0.5 for fb in formula_boxes):
            continue
        crop = pil_image.crop((int(g[0] * f) - 4, int(g[1] * f) - 4,
                               int(g[2] * f) + 4, int(g[3] * f) + 4))
        md = (tfo.recognize(crop, return_text=True) or "").strip()
        if md:
            region_elems.append({"rect": g, "md": md})
    region_boxes = [e["rect"] for e in region_elems]
    formula_elems = [e for e in formula_elems
                     if not any(_overlap_frac(e["rect"], g) > 0.5 for g in region_boxes)]

    # ── 3) Texto nativo por bloques, excluyendo fórmulas/tablas/regiones ──
    exclude = formula_boxes + table_boxes + region_boxes
    text_elems = []
    for blk in page.get_text("blocks"):
        if len(blk) >= 7 and blk[6] != 0:
            continue  # bloque de imagen, no de texto
        rect = (blk[0], blk[1], blk[2], blk[3])
        txt = (blk[4] or "").strip()
        if not txt:
            continue
        if any(_overlap_frac(rect, ex) > 0.5 for ex in exclude):
            continue
        text_elems.append({"rect": rect, "md": txt})

    elems = text_elems + formula_elems + table_elems + region_elems
    if not elems:
        return ""
    return "\n\n".join(e["md"] for e in _order_columns(elems, W))


def _order_columns(elems, W):
    """Ordena los elementos en orden de lectura, detectando 2 columnas.
    Los elementos full-width (títulos, tablas anchas) actúan como cortes."""
    for e in elems:
        x0, _, x1, _ = e["rect"]
        e["_full"] = (x1 - x0) > 0.55 * W
        e["_col"] = 0 if (x0 + x1) / 2 < W / 2 else 1

    left = [e for e in elems if not e["_full"] and e["_col"] == 0]
    right = [e for e in elems if not e["_full"] and e["_col"] == 1]
    two_col = any(
        l["rect"][1] < r["rect"][3] and r["rect"][1] < l["rect"][3]
        for l in left for r in right
    )
    if not two_col:
        return sorted(elems, key=lambda e: (e["rect"][1], e["rect"][0]))

    out, bl, br = [], [], []

    def flush():
        out.extend(sorted(bl, key=lambda e: e["rect"][1]))
        out.extend(sorted(br, key=lambda e: e["rect"][1]))
        bl.clear()
        br.clear()

    for e in sorted(elems, key=lambda e: e["rect"][1]):
        if e["_full"]:
            flush()
            out.append(e)
        elif e["_col"] == 0:
            bl.append(e)
        else:
            br.append(e)
    flush()
    return out
