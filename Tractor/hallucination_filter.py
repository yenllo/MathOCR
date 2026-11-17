"""Filtro DETERMINISTA anti-alucinación para la salida del OCR.

pix2text, al toparse con gráficos decorativos de las diapositivas (números
encerrados en círculo, logos, cajas sombreadas), alucina spans de "matemática"
que son pura basura: matrices anidadas vacías con `\\textcircled{...}` o
corridas de cientos de ceros. Esto no es formato: es ruido que infla el .md y
envenenaría un índice RAG.

Este filtro descarta ESOS spans `$...$`/`$$...$$` y SOLO esos, con señales
fuertes (nunca toca una ecuación legítima):
  - contiene `\\textcircled`            -> decoración, jamás matemática real aquí
  - corrida de 30+ ceros seguidos       -> blob alucinado
  - corrida de 40+ dígitos seguidos     -> blob numérico alucinado
  - 3+ `\\begin{matrix}` sin nada de matemática reconocible (=, \\frac, \\sqrt)
  - 10+ repeticiones del MISMO comando  -> `\\bullet\\bullet…`, `\\mathbf{\\mathbf{…`
    (bucle del MFR sobre un logo)
  - 8+ letras sueltas separadas por espacios -> `U n i v e r s i d a d`, texto de
    un logo leído como si fuera fórmula

Además elimina comandos `\\ref`/`\\eqref`/`\\label` (referencias a etiquetas
inexistentes que el OCR inventa), sin borrar el resto del span.

No usa LLM. No puede alucinar. No corrige ortografía ni contenido.
"""

import re

# $$...$$ antes que $...$ (alternancia con no-greedy + DOTALL).
_DOLLAR_SPAN = re.compile(r"\$\$.*?\$\$|\$.*?\$", re.DOTALL)
_REF_CMD = re.compile(r"\\(?:ref|eqref|label)\s*\{[^}]*\}")
_ZERO_RUN = re.compile(r"0(?:\s*0){29,}")        # 30+ ceros consecutivos
_DIGIT_RUN = re.compile(r"\d(?:\s*\d){39,}")      # 40+ dígitos consecutivos
_CMD_RUN = re.compile(r"(\\[a-zA-Z]+)(?:[\s{]*\1){9,}")   # \bullet\bullet…, \mathbf{\mathbf{…
_SPACED_WORD = re.compile(r"(?:[A-Za-z]\s+){7,}[A-Za-z]")  # "U n i v e r s i d a d"

# Señales que un logo no produce pero una fórmula real sí: comandos matemáticos
# de verdad y alineación multi-columna (`&`). Salvan a las ecuaciones y leyendas
# que llevan prosa dentro (`\mathrm{h a c i a ~ l a ~ d e r e c h a}`) de caer
# por la regla de letras espaciadas.
_REAL_MATH = ("\\frac", "\\sqrt", "\\int", "\\sum", "\\prod", "\\lim", "\\vec",
              "\\cdot", "\\times", "\\partial", "\\infty", "\\begin{cases}", "&")


def _is_garbage(inner):
    """True si el contenido de un span matemático es claramente basura."""
    if "\\textcircled" in inner:
        return True
    if _ZERO_RUN.search(inner):
        return True
    if _DIGIT_RUN.search(inner):
        return True
    if _CMD_RUN.search(inner):
        return True
    if _SPACED_WORD.search(inner) and not any(t in inner for t in _REAL_MATH):
        return True
    if inner.count("\\begin{matrix}") >= 3 and not any(
        tok in inner for tok in ("=", "\\frac", "\\sqrt")
    ):
        return True
    return False


def strip_hallucinations(text):
    """Quita spans matemáticos basura y referencias inventadas. Resto intacto."""
    if not text:
        return text

    def _repl(match):
        whole = match.group(0)
        display = whole.startswith("$$")
        inner = whole[2:-2] if display else whole[1:-1]

        inner = _REF_CMD.sub("", inner)        # fuera \ref/\eqref/\label
        if _is_garbage(inner):
            return ""                          # descartar el blob completo
        if not inner.strip():                  # quedó vacío tras limpiar refs
            return ""
        return f"$${inner}$$" if display else f"${inner}$"

    out = _DOLLAR_SPAN.sub(_repl, text)

    # Recoger el espaciado que deja un span eliminado (sin tocar saltos de línea).
    out = re.sub(r"(?<=\S) {2,}", " ", out)
    out = re.sub(r"[ \t]+(?=\n)", "", out)
    return out.strip()


if __name__ == "__main__":
    # Basura real (logos de la charla de seguridad) vs. matemática real: si una
    # heurística se vuelve demasiado agresiva, esto revienta.
    basura = [
        r"$$\begin{array}{l}{\mathcal{(}_{\mathcal{S}^{\bullet}" + r"\bullet" * 40 + "}}\\end{array}$$",
        "$$" + r"\mathbf{" * 12 + "A" + "}" * 12 + "$$",
        r"$$\widehat{\mathcal{P}}\overset{\mathrm{U n i v e r s i d a d d e}}{\mathrm{l o s A n d e s}}$$",
        r"$$\begin{array}{l}{\mathtt{F A C U L T A D}}\\{\mathtt{D E I N G E N I E R I A}}\\\end{array}$$",
        r"$$\mathrm{e m e r g e n c i a ?}$$",
        r"$$\begin{matrix}\textcircled{1}\end{matrix}$$",
    ]
    buena = [
        r"$$\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}$$",
        r"$$\vec{F} = m\vec{a}$$",
        r"Sea $x + y = z$ con $a b c$ reales.",
        r"$$\begin{array}{l}{v_x = v_0\cos\theta}\\{v_y = v_0\sin\theta - gt}\\\end{array}$$",
        r"$$\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$$",
        # Leyenda símbolo→texto, alineada con '&': no es un logo.
        r"$$\begin{array}{r r}{\widehat{\mathbf{x}}} & {\mathrm{h a c i a ~ l a ~ d e r e c h a ,}} \\ {\widehat{\mathbf{y}}} & {\mathrm{h a c i a ~ a d e l a n t e ,}}\end{array}$$",
        # Fórmula real con prosa dentro (así la emite el MFR): no es un logo.
        r"$$\vec{a} \cdot\vec{b} \begin{cases} {> 0 \quad\mathrm{v e c t o r ~ a p u n t a ~ h a c i a ~ a d e l a n t e}} \end{cases}$$",
    ]
    for s in basura:
        assert strip_hallucinations(s) == "", f"NO filtrado: {s[:60]}"
    for s in buena:
        assert "$" in strip_hallucinations(s), f"borró matemática real: {s[:60]}"
    print(f"ok: {len(basura)} blobs descartados, {len(buena)} fórmulas intactas")
