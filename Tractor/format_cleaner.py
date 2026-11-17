"""Limpieza DETERMINISTA de solo-formato para la salida del OCR.

Filosofía: nunca puede alucinar. No usa LLM. Solo normaliza espaciado y unos
pocos glitches de espacios "raros", y JAMÁS toca:
  - el contenido dentro de matemáticas LaTeX ($...$ y $$...$$),
  - el contenido dentro de código inline (`...`),
  - palabras, números o signos del texto.

Cualquier span matemático/código se aísla con un placeholder antes de tocar el
texto y se restaura intacto al final, byte por byte.
"""

import re
import unicodedata

# Acentos de TeX viejo en la capa de texto: el acento va SUELTO antes de la vocal
# ("C´alculo", "Gu´ıa", " ´area", "Espa˜na"). Se combinan con su letra.
_RE_ACENTO = re.compile(r"(´)[ \n]?([aeiouAEIOUı])|(˜)[ \n]?([nN])|(¨)[ \n]?([uU])|([nN])(˜)")
_COMBINA = {"´": "́", "˜": "̃", "¨": "̈"}
_LIGADURAS = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"})


def _acento(m):
    if m.group(7):                                   # "An˜o": la tilde quedó DESPUÉS de la n
        return unicodedata.normalize("NFC", m.group(7) + _COMBINA["˜"])
    signo, base = next((m.group(i), m.group(i + 1)) for i in (1, 3, 5) if m.group(i))
    return unicodedata.normalize("NFC", ("i" if base == "ı" else base) + _COMBINA[signo])


_CELDA_VACIA = re.compile(r"\s*(:?-{3,}:?|Col\d+)?\s*")


def _tabla_util(m):
    """Deja la tabla solo si al menos 1/5 de sus celdas tiene contenido. find_tables
    lee las grillas de los gráficos como tablas: filas '|||||' y 'Col1|Col2…'."""
    celdas = [c for l in m.group(0).splitlines() for c in l.strip()[1:-1].split("|")]
    llenas = sum(1 for c in celdas if not _CELDA_VACIA.fullmatch(c))
    return m.group(0) if llenas >= 0.2 * len(celdas) else ""


# Orden importante: $$...$$ antes que $...$. El código inline `...` se protege aparte.
_PROTECT_PATTERNS = [
    re.compile(r"\$\$.*?\$\$", re.DOTALL),   # math display
    re.compile(r"\$[^$\n]*?\$"),             # math inline: una línea (si no, entre dos
                                             # precios "$200 … $500" protege todo el texto)
    re.compile(r"`[^`]*`"),                  # código inline
]


def _protect(text):
    """Sustituye spans intocables por placeholders. Devuelve (texto, lista_de_spans)."""
    spans = []

    def _stash(match):
        spans.append(match.group(0))
        # El placeholder no contiene espacios ni puntuación para que las pasadas
        # de formato no lo alteren.
        return f"\x00{len(spans) - 1}\x00"

    for pattern in _PROTECT_PATTERNS:
        text = pattern.sub(_stash, text)
    return text, spans


def _restore(text, spans):
    """Reinyecta los spans originales en su sitio, sin modificarlos. Itera porque
    un span puede contener el placeholder de otro: un '$' suelto (un precio)
    antes de un '$$…$$' hace que el '$…$' se trague el placeholder del display."""
    def _pop(match):
        return spans[int(match.group(1))]

    for _ in range(len(spans) + 1):
        text, n = re.subn(r"\x00(\d+)\x00", _pop, text)
        if not n:
            break
    return text


def clean_format(text):
    """Normaliza SOLO formato del texto plano (la matemática queda intacta)."""
    if not text:
        return text

    # NUL de la capa de texto del PDF: basura, y chocaría con los placeholders.
    protected, spans = _protect(text.replace("\x00", ""))

    # 1. Espacios no separables / exóticos -> espacio normal (puro formato).
    protected = protected.replace(" ", " ").replace("​", "")
    protected = protected.replace("\t", " ")

    # 1b. Acentos sueltos de TeX y ligaduras -> letra normal. Tablas fantasma fuera.
    protected = _RE_ACENTO.sub(_acento, protected).translate(_LIGADURAS)
    protected = re.sub(r"(?m)(?:^\|.*\|[ \t]*(?:\n|$))+", _tabla_util, protected)

    # 2. Colapsar runs de 2+ espacios INTERNOS (no al inicio de línea, para no
    #    romper indentación de listas/bloques markdown).
    protected = re.sub(r"(?<=\S) {2,}", " ", protected)

    # 3. Quitar espacios al final de cada línea.
    protected = re.sub(r"[ \t]+(?=\n)", "", protected)
    protected = re.sub(r"[ \t]+$", "", protected)

    # 4. Colapsar 3+ líneas en blanco consecutivas a un máximo de 2.
    protected = re.sub(r"\n{3,}", "\n\n", protected)

    return _restore(protected, spans)


if __name__ == "__main__":
    assert clean_format("Gu´ıa de C´alculo, el ´area y Espa˜na: deﬁnici´on") == \
        "Guía de Cálculo, el área y España: definición"
    assert clean_format("Ping¨uino $x´a$") == "Pingüino $x´a$"          # LaTeX intacto
    fantasma = "|Col1|Col2|Col3|\n|---|---|---|\n||||\n||||\n"
    assert clean_format("antes\n" + fantasma + "despues") == "antes\ndespues"
    real = "|a|b|\n|---|---|\n|1||\n"
    assert real.strip() in clean_format(real)
    anidado = "cuesta $5 y\n$$\nx^2\n$$\nluego $ fin"                     # '$' suelto + display
    assert clean_format(anidado) == anidado and "\x00" not in clean_format("a\x00 1")
    assert clean_format("cuesta $200\nla informaci´on del An˜o $500") == \
        "cuesta $200\nla información del Año $500"                       # precios en líneas distintas
    print("format_cleaner OK")
