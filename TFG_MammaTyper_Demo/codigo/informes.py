"""
informes.py

Generación de informe PDF (1 página) integrando:
  - Datos IHQ (Patwin/Excel)
  - Datos MammaTyper® (PDF qRT-PCR)
  - Derivados de cutoffs (Δabs, equivalencias)
  - Visualizaciones (barras tipo MammaTyper + proximidad a cutoffs)
  - Pie legal + firmantes

Requisitos:
    pip install reportlab

Notas de diseño:
  - Este PDF está pensado para ser “visual” y compacto en una sola página A4.
  - Se respeta la configuración desde ajustes.py (load_settings) para:
        * títulos de secciones
        * logo
        * activación/desactivación de bloques
        * rangos/thresholds por gen (mmt_ranges)
        * avisos en PDF
"""

from typing import Mapping, Any, Optional
from io import BytesIO
from datetime import datetime
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from ajustes import load_settings


# =============================================================================
# CONSTANTES DE ESTILO
# =============================================================================

IHC_POSITIVE_BLUE = colors.Color(0.05, 0.25, 0.55)

# Pie de página (altura reservada + tipografía)
FOOTER_HEIGHT = 45
FOOTER_FONT = 7.2
FOOTER_LINE_H = 9.0

# Bordes por “origen” (solo borde, sin relleno)
BORDER_EXCEL = colors.Color(0.15, 0.55, 0.20)   # verde (procedente de Excel)
BORDER_PDF   = colors.Color(0.70, 0.15, 0.15)   # rojo (procedente de PDF)
BORDER_GEN   = colors.black                    # negro (generado / general)

BORDER_W_THIN = 1.1
BORDER_W_THICK = 1.6


# =============================================================================
# HELPERS GENERALES (NA / formato / wrapping)
# =============================================================================

def _es_na(valor) -> bool:
    """
    Devuelve True si 'valor' se considera vacío/no disponible:
      - None
      - NaN (float)
      - string vacío o con espacios
    """
    if valor is None:
        return True
    if isinstance(valor, float):
        return valor != valor  # NaN
    if isinstance(valor, str) and valor.strip() == "":
        return True
    return False


def _fmt(valor, fallback: str = "No consta") -> str:
    """Formatea valores para imprimir en PDF (con fallback si está vacío)."""
    return fallback if _es_na(valor) else str(valor)


def _draw_wrapped_lines(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    max_width: float,
    font_name: str,
    font_size: float,
    line_h: float,
    max_lines: int = 2,
) -> float:
    """
    Dibuja texto multi-línea con “word wrap” manual y truncado a max_lines.

    Parámetros clave:
      - max_width: ancho máximo disponible (en puntos) para cada línea.
      - max_lines: si el contenido excede, se recorta y se añade "…".

    Retorna:
      - nueva coordenada y (la y final tras imprimir las líneas).
    """
    if not text:
        return y

    c.setFont(font_name, font_size)

    paragraphs = str(text).splitlines()
    all_lines = []

    # Partimos por párrafos y hacemos wrap por palabras
    for para in paragraphs:
        para = str(para).strip()
        if para == "":
            all_lines.append("")
            continue

        words = para.split()
        current = ""

        for w in words:
            trial = (current + " " + w).strip()
            if c.stringWidth(trial, font_name, font_size) <= max_width:
                current = trial
            else:
                if current:
                    all_lines.append(current)
                current = w

        if current:
            all_lines.append(current)

    # Truncado (si hay más líneas que max_lines)
    if len(all_lines) > max_lines:
        visible = all_lines[:max_lines]

        # buscamos la última línea “útil” para añadir elipsis
        i = len(visible) - 1
        while i > 0 and visible[i].strip() == "":
            i -= 1

        last = visible[i]
        if last.strip() == "":
            visible[i] = "…"
        else:
            # recortamos caracteres hasta que quepa con "…"
            while c.stringWidth(last + "…", font_name, font_size) > max_width and len(last) > 0:
                last = last[:-1]
            visible[i] = (last + "…") if last else "…"

        # vaciamos el resto
        for j in range(i + 1, len(visible)):
            visible[j] = ""
        all_lines = visible

    # Pintado final
    for ln in all_lines:
        if ln.strip() == "":
            y -= (line_h * 0.5)
            continue
        c.drawString(x, y, ln)
        y -= line_h

    return y


def _to_float(x) -> Optional[float]:
    """Convierte a float de forma segura; devuelve None si no es posible."""
    try:
        if _es_na(x):
            return None
        return float(x)
    except Exception:
        return None


# =============================================================================
# HELPERS PARA GRADIENTE Y GEOMETRÍA DE BARRAS
# =============================================================================

def _clamp01(x: float) -> float:
    """Satura un valor a [0, 1]."""
    return max(0.0, min(1.0, x))


def _lerp(a: float, b: float, t: float) -> float:
    """Interpolación lineal entre a y b con t en [0,1]."""
    return a + (b - a) * t


def _colormap_mammatyper(t: float):
    """
    Colormap “tipo heatmap” para las barras:
      - azul -> verde -> amarillo -> naranja -> rojo

    t debe estar en [0,1].
    """
    t = _clamp01(t)
    stops = [
        (0.00, (0.05, 0.35, 0.80)),
        (0.30, (0.45, 0.75, 0.45)),
        (0.55, (0.95, 0.80, 0.20)),
        (0.72, (0.95, 0.55, 0.15)),
        (1.00, (0.75, 0.10, 0.10)),
    ]

    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t0 <= t <= t1:
            tt = (t - t0) / (t1 - t0) if t1 != t0 else 0.0
            r = _lerp(c0[0], c1[0], tt)

            # IMPORTANTE:
            # En tu versión original había un detalle:
            #   g = _lerp(c0[1], c1[0], tt)
            # Eso mezcla el canal G con el canal R del siguiente stop.
            # Aquí lo dejo corregido para que interpolen canales homólogos.
            g = _lerp(c0[1], c1[1], tt)

            b = _lerp(c0[2], c1[2], tt)
            return colors.Color(r, g, b)

    return colors.Color(*stops[-1][1])


def _x_from_value(x0: float, w: float, v: float, vmin: float, vmax: float) -> float:
    """
    Convierte un valor v dentro de [vmin, vmax] a coordenada X dentro del rango [x0, x0+w].
    """
    if vmax == vmin:
        return x0
    t = (v - vmin) / (vmax - vmin)
    return x0 + _clamp01(t) * w


def _draw_gradient_bar(c: canvas.Canvas, x0: float, y0: float, w: float, h: float, vmin: float, vmax: float):
    """
    Dibuja una barra horizontal con gradiente (por rectángulos finos).
    """
    steps = 220
    for i in range(steps):
        t = i / (steps - 1)
        c.setFillColor(_colormap_mammatyper(t))
        c.rect(x0 + w * t, y0, w / steps + 0.5, h, stroke=0, fill=1)

    # borde exterior
    c.setStrokeColor(colors.black)
    c.rect(x0, y0, w, h, stroke=1, fill=0)


def _draw_ticks(
    c: canvas.Canvas,
    x0: float,
    y_top: float,
    w: float,
    vmin: float,
    vmax: float,
    major_step: float,
    minor_step: float,
    font_size: float = 6.5,
):
    """
    Dibuja ticks y etiquetas numéricas encima de una barra.

    - minor_step: marcas cortas
    - major_step: marcas largas + etiqueta
    """
    # marcas menores
    c.setStrokeColor(colors.grey)
    c.setLineWidth(0.6)

    v = vmin
    while v <= vmax + 1e-9:
        x = _x_from_value(x0, w, v, vmin, vmax)
        c.line(x, y_top, x, y_top - 6)
        v += minor_step

    # marcas mayores + etiquetas
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.setFont("Helvetica", font_size)

    v = vmin
    while v <= vmax + 1e-9:
        x = _x_from_value(x0, w, v, vmin, vmax)
        c.line(x, y_top, x, y_top - 10)
        lab = f"{v:.1f}"
        c.setFillColor(colors.grey)
        c.drawCentredString(x, y_top + 2, lab)
        v += major_step


def _draw_tag(c: canvas.Canvas, x: float, y: float, text: str, font_size: float = 7.0):
    """
    Dibuja una “etiqueta” negra con texto blanco (útil para marcar thresholds).
    """
    padding_x = 4
    padding_y = 2

    c.saveState()
    c.setFont("Helvetica-Bold", font_size)

    text_w = c.stringWidth(text, "Helvetica-Bold", font_size)
    box_w = text_w + 2 * padding_x
    box_h = font_size + 2 * padding_y

    c.setFillColor(colors.black)
    c.setStrokeColor(colors.black)
    c.roundRect(x, y, box_w, box_h, 3, stroke=0, fill=1)

    c.setFillColor(colors.white)
    c.drawString(x + padding_x, y + padding_y, text)
    c.restoreState()


def _draw_thresholds(
    c: canvas.Canvas,
    x0: float,
    y0: float,
    w: float,
    h: float,
    vmin: float,
    vmax: float,
    thresholds: list[float],
):
    """
    Dibuja líneas verticales (negras) en la barra para thresholds.
    También coloca una etiqueta con el valor numérico del threshold.
    """
    c.saveState()
    c.setStrokeColor(colors.black)
    c.setLineWidth(1.4)

    for th in thresholds:
        x = _x_from_value(x0, w, th, vmin, vmax)
        c.line(x, y0, x, y0 + h)

        label = f"{th:.1f}"
        tag_y = y0 - 16
        if tag_y < 6:
            tag_y = y0 + h + 4

        est_w = c.stringWidth(label, "Helvetica-Bold", 7.0) + 8
        tag_x = x - est_w / 2

        # evitar que la etiqueta se salga de la barra
        if tag_x < x0:
            tag_x = x0
        if tag_x + est_w > x0 + w:
            tag_x = x0 + w - est_w

        _draw_tag(c, tag_x, tag_y, label, font_size=7.0)

    c.restoreState()


def _draw_value_marker(
    c: canvas.Canvas,
    x0: float,
    y0: float,
    w: float,
    h: float,
    vmin: float,
    vmax: float,
    value: float,
):
    """
    Dibuja el marcador rojo (valor medido) como una línea vertical.
    """
    x = _x_from_value(x0, w, value, vmin, vmax)
    c.saveState()
    c.setStrokeColor(colors.red)
    c.setLineWidth(2.8)
    c.line(x, y0 - 2, x, y0 + h + 2)
    c.restoreState()


def _draw_mmt_bar(
    c: canvas.Canvas,
    x0: float,
    y_top: float,
    w: float,
    title: str,
    value_raw,
    status: str,
    vmin: float,
    vmax: float,
    thresholds: list[float],
    labels: list[tuple[str, float]],
):
    """
    Dibuja una barra completa para un gen:
      - título
      - ticks numéricos
      - gradiente
      - labels internos (texto centrado)
      - líneas de thresholds (negro)
      - marcador del valor (rojo)
      - texto Valor/Estado debajo
    """
    c.saveState()

    bar_h = 14
    gap_after = 16

    # Conversión segura del valor
    try:
        value = float(value_raw)
    except Exception:
        value = None

    # Título
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(colors.black)
    c.drawString(x0, y_top + 2, title)

    # Coordenadas internas: se separa el título de ticks/barra para evitar solapes
    ticks_y = y_top - 18
    bar_y0 = ticks_y - 22

    _draw_ticks(c, x0, ticks_y, w, vmin, vmax, major_step=0.5, minor_step=0.2, font_size=6.3)
    _draw_gradient_bar(c, x0, bar_y0, w, bar_h, vmin, vmax)

    # Labels sobre la barra (texto blanco dentro del gradiente)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(colors.white)
    for txt, pos_value in labels:
        cx = _x_from_value(x0, w, pos_value, vmin, vmax)
        c.drawCentredString(cx, bar_y0 + 4, txt)

    # Thresholds (negro)
    if thresholds:
        _draw_thresholds(c, x0, bar_y0, w, bar_h, vmin, vmax, thresholds)

    # Valor (rojo) + texto inferior
    if value is not None:
        _draw_value_marker(c, x0, bar_y0, w, bar_h, vmin, vmax, value)

        y_txt = bar_y0 - 6
        right_x = x0 + w

        status_txt = _fmt(status, "NC")
        is_positive = "pos" in status_txt.lower()

        left_text = f"Valor: {value:.2f}   Estado:"
        font_name = "Helvetica-Bold"
        font_size = 7.2

        c.setFont(font_name, font_size)
        status_w = c.stringWidth(status_txt, font_name, font_size)

        # “Valor: xx.xx  Estado:” alineado a la derecha dejando hueco para el estado
        c.setFillColor(colors.black)
        c.drawRightString(right_x - status_w - 2, y_txt, left_text)

        # Estado coloreado si es positivo
        c.setFillColor(colors.red if is_positive else colors.black)
        c.drawRightString(right_x, y_txt, status_txt)

    c.restoreState()
    return bar_y0 - gap_after


# =============================================================================
# CAJAS / CONTENEDORES (solo borde)
# =============================================================================

def _box_stroked(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    radius: float = 8,
    stroke_color=colors.black,
    stroke_width: float = 1.1,
) -> None:
    """
    Dibuja un rectángulo redondeado SOLO con borde (sin relleno).
    y se interpreta como coordenada superior: la caja se dibuja hacia abajo.
    """
    c.saveState()
    c.setFillColor(colors.white)
    c.setStrokeColor(stroke_color)
    c.setLineWidth(stroke_width)
    c.roundRect(x, y - h, w, h, radius, stroke=1, fill=0)
    c.restoreState()


# =============================================================================
# CLASIFICACIONES COMPACTAS (para resumen IHQ)
# =============================================================================

def _clasificar_hr(m: Mapping[str, Any]) -> str:
    """
    Resume HR (ER/PR) priorizando IHQ si existe (% y/o estado).
    Si no hay IHQ disponible, cae a estados MMT (ESR1_status/PGR_status).
    """
    er_status = _fmt(m.get("ESR1_IHQ"), "")
    pr_status = _fmt(m.get("PGR_IHQ"), "")

    er_pct = _to_float(m.get("ESR1_IHQ_pct"))
    pr_pct = _to_float(m.get("PGR_IHQ_pct"))

    tiene_er_ihq = (not _es_na(m.get("ESR1_IHQ"))) or (er_pct is not None)
    tiene_pr_ihq = (not _es_na(m.get("PGR_IHQ"))) or (pr_pct is not None)

    if tiene_er_ihq or tiene_pr_ihq:
        # ER
        if er_pct is not None:
            er_txt = f"ER+ ({int(round(er_pct))}%)" if "pos" in str(er_status).lower() else f"ER ({int(round(er_pct))}%)"
        else:
            er_txt = f"ER: {_fmt(m.get('ESR1_IHQ'),'NC')}"

        # PR
        if pr_pct is not None:
            pr_low = pr_pct < 10
            if "pos" in str(pr_status).lower():
                pr_txt = f"PR bajo ({int(round(pr_pct))}%)" if pr_low else f"PR+ ({int(round(pr_pct))}%)"
            else:
                pr_txt = f"PR ({int(round(pr_pct))}%)"
        else:
            pr_txt = f"PR: {_fmt(m.get('PGR_IHQ'),'NC')}"

        return f"{er_txt}, {pr_txt}"

    # Fallback: MMT status
    er_m = _fmt(m.get("ESR1_status"), "NC")
    pr_m = _fmt(m.get("PGR_status"), "NC")
    if (not _es_na(m.get("ESR1_status"))) or (not _es_na(m.get("PGR_status"))):
        return f"ER ({er_m}), PR ({pr_m})"

    return "No consta"


def _clasificar_her2(m: Mapping[str, Any]) -> str:
    """
    Resume HER2 combinando:
      - HER2_final (si existe)
      - ERBB2_IHQ_SISH (texto)
      - ERBB2_status (MMT)

    Devuelve: "HER2+", "HER2−", "HER2-low", "HER2-low (comentario)" o "No consta".
    """
    base_parts = []
    for x in [m.get("HER2_final"), m.get("ERBB2_IHQ_SISH"), m.get("ERBB2_status")]:
        if not _es_na(x):
            base_parts.append(str(x).lower())
    base = " ".join(base_parts)

    score = None
    if not _es_na(m.get("HER2_IHQ_score")):
        score = str(m.get("HER2_IHQ_score")).strip()

    if "low" in base:
        if score in ("0", "1", "2", "3", "0+", "1+", "2+", "3+"):
            return "HER2-low"
        return "HER2-low (comentario)"

    if "ampl" in base or "positivo" in base or "pos" in base or score in ("3", "3+"):
        return "HER2+"

    if "neg" in base or score in ("0", "0+", "1", "1+"):
        return "HER2−"

    return "No consta"


def _clasificar_ki67(m: Mapping[str, Any]) -> str:
    """
    Resume Ki-67 a partir de IHQ (KI67_IHQ).
    Categorías orientativas:
      - <10: bajo
      - 10-20: intermedio
      - >20: alto
    """
    v = _to_float(m.get("KI67_IHQ"))
    if v is None:
        return "Ki-67: No consta"
    if v < 10:
        cat = "bajo"
    elif v <= 20:
        cat = "intermedio"
    else:
        cat = "alto"
    return f"Ki-67: {int(round(v))}% ({cat})"


# =============================================================================
# PANEL INTEGRADO (IHQ + MMT + CUT-OFFS)
# =============================================================================

def _draw_panel_resumen_integrado(
    c: canvas.Canvas,
    x: float,
    y_top: float,
    w: float,
    muestra: Mapping[str, Any],
    settings_mmt: dict,
) -> float:
    """
    Panel único: resume IHQ (HR/HER2/Ki67) a la izquierda y una tabla de genes a la derecha.

    Tabla genes (derecha):
      - Gen
      - Valor (Ct)
      - Estado (Positive/Negative/NC)
      - Cutoff más cercano (a partir de thresholds en settings)
      - Δabs (|valor - cutoff|)
      - Equiv (m.get("{GEN}_equiv") si existe)

    Retorna:
      - y_top actualizado para continuar dibujando debajo del panel.
    """
    genes = ["ERBB2", "ESR1", "PGR", "MKI67"]

    title_h = 14
    header_h = 12
    row_h = 12
    box_h = title_h + header_h + len(genes) * row_h + 16

    # Borde rojo grueso porque el panel se apoya fuertemente en MMT/cutoffs
    _box_stroked(c, x, y_top, w, box_h, radius=8, stroke_color=BORDER_PDF, stroke_width=BORDER_W_THICK)

    # Título panel
    c.setFont("Helvetica-Bold", 8.4)
    c.setFillColor(colors.black)
    c.drawString(x + 10, y_top - 14, "Resumen integrado (IHQ + MMT qRT-PCR + cutoffs)")

    # Resumen IHQ (izquierda)
    hr = _clasificar_hr(muestra)
    her2 = _clasificar_her2(muestra)
    ki67 = _clasificar_ki67(muestra)

    c.setFont("Helvetica", 7.6)
    c.setFillColor(colors.black)
    ihq_x = x + 10
    ihq_y = y_top - 30
    c.drawString(ihq_x, ihq_y,      f"HR: {hr}")
    c.drawString(ihq_x, ihq_y - 10, f"HER2: {her2}")
    c.drawString(ihq_x, ihq_y - 20, f"{ki67}")

    # Tabla genes (derecha)
    table_x = x + 200
    col_gen   = table_x
    col_val   = table_x + 55
    col_stat  = table_x + 105
    col_cut   = table_x + 175
    col_delta = table_x + 230
    col_eq    = table_x + 280

    y = y_top - title_h - 6
    c.setFont("Helvetica-Bold", 7.2)
    c.drawString(col_gen, y, "Gen")
    c.drawString(col_val, y, "Valor")
    c.drawString(col_stat, y, "Estado")
    c.drawString(col_cut, y, "Cutoff")
    c.drawString(col_delta, y, "Δabs")
    c.drawString(col_eq, y, "Equiv")

    y -= 10
    c.setFont("Helvetica", 7.2)

    for g in genes:
        v = _to_float(muestra.get(f"{g}_value"))
        stt = _fmt(muestra.get(f"{g}_status"), "NC")

        # thresholds desde settings (si existen)
        cfg = (settings_mmt or {}).get(g, {}) or {}
        thresholds = cfg.get("thresholds") or []
        thresholds = [float(t) for t in thresholds if t is not None]

        # cutoff más cercano (si hay datos)
        cutoff = None
        if thresholds and v is not None:
            cutoff = min(thresholds, key=lambda t: abs(v - t))

        delta = abs(v - cutoff) if (v is not None and cutoff is not None) else None
        eq = _fmt(muestra.get(f"{g}_equiv"), "—")

        c.drawString(col_gen, y, g)
        c.drawRightString(col_val + 35, y, f"{v:.2f}" if v is not None else "—")
        c.drawString(col_stat, y, stt)
        c.drawRightString(col_cut + 45, y, f"{cutoff:.2f}" if cutoff is not None else "—")
        c.drawRightString(col_delta + 32, y, f"{delta:.2f}" if delta is not None else "—")
        c.drawString(col_eq, y, eq)

        y -= row_h

    return y_top - (box_h + 14)


# =============================================================================
# VISUAL: PROXIMIDAD A CUTOFFS (Δabs)
# =============================================================================

def _draw_mmt_proximity_visual(
    c: canvas.Canvas,
    x: float,
    y_top: float,
    w: float,
    muestra: Mapping[str, Any],
    max_delta: float = 1.0,
) -> float:
    """
    Representación compacta del Δabs por gen.

    Idea:
      - Se pinta una barra “0 → max_delta” y se marca Δabs.
      - Se colorea el tramo (relleno) según severidad:
          * <0.2: rojo (crítico)
          * <0.5: naranja (cercano)
          * resto: gris

    Retorna:
      - y_top actualizado.
    """
    genes = ["ERBB2", "ESR1", "PGR", "MKI67"]

    title_h = 14
    row_h = 14

    expl_lines = [
        "Cómo leerlo: el marcador negro indica el Δabs (distancia al cutoff) para cada gen.",
        "Cuanto menor es Δabs (más a la izquierda), más cerca está del punto de corte: rojo <0.2, naranja <0.5.",
    ]
    expl_h = 2 * 8.0 + 2

    box_h = title_h + len(genes) * row_h + 14 + expl_h + 6
    _box_stroked(c, x, y_top, w, box_h, radius=8, stroke_color=BORDER_PDF, stroke_width=BORDER_W_THIN)

    c.setFont("Helvetica-Bold", 8.0)
    c.setFillColor(colors.black)
    c.drawString(x + 10, y_top - 14, "Proximidad a cutoffs (Δabs, Ct)")

    c.setFont("Helvetica", 6.8)
    c.setFillColor(colors.black)
    c.drawRightString(x + w - 10, y_top - 14, f"Escala: 0 → {max_delta:.1f} Ct  |  <0.2 crítico, <0.5 cercano")

    # geometría barras
    bar_x0 = x + 90
    right_text_pad = 62
    bar_w = (x + w - 10) - right_text_pad - bar_x0
    if bar_w < 60:
        bar_w = 60

    x_text = x + w - 10
    y = y_top - 30

    for g in genes:
        delta = _to_float(muestra.get(f"{g}_delta_cutoff"))

        c.setFont("Helvetica-Bold", 7.6)
        c.setFillColor(colors.black)
        c.drawString(x + 10, y + 2, g)

        # marco base
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.6)
        c.rect(bar_x0, y - 2, bar_w, 8, fill=0)

        if delta is None:
            c.setFont("Helvetica", 7.0)
            c.setFillColor(colors.black)
            c.drawString(bar_x0 + 4, y + 2, "—")
            c.drawRightString(x_text, y + 2, "Δ=—")
        else:
            d_raw = float(delta)
            d = max(0.0, min(d_raw, max_delta))
            frac = d / max_delta if max_delta > 0 else 0.0

            # semáforo
            if d < 0.2:
                fill = colors.red
            elif d < 0.5:
                fill = colors.orange
            else:
                fill = colors.lightgrey

            fill_w = bar_w * frac
            c.setFillColor(fill)
            c.rect(bar_x0, y - 2, fill_w, 8, stroke=0, fill=1)

            # marcador negro al final del relleno (posición Δ)
            c.setStrokeColor(colors.black)
            c.setLineWidth(1.0)
            c.line(bar_x0 + fill_w, y - 3, bar_x0 + fill_w, y + 7)

            c.setFont("Helvetica", 7.0)
            c.setFillColor(colors.black)
            c.drawRightString(x_text, y + 2, f"Δ={d:.2f}")

        y -= row_h

    # texto explicativo
    y_text = y + 2
    c.setFont("Helvetica", 7.2)
    c.setFillColor(colors.black)
    c.drawString(x + 10, y_text, expl_lines[0])
    c.setFillColor(colors.grey)
    c.drawString(x + 10, y_text - 9, expl_lines[1])

    return y_top - (box_h + 14)


# =============================================================================
# AVISOS (bloque opcional)
# =============================================================================

def _normalizar_aviso_texto(aviso: str) -> str:
    """
    Normaliza el texto de avisos para imprimirse como lista:
      - reemplaza separador " | " por salto + viñeta
      - asegura que empiece por "•"
    """
    if not aviso:
        return ""
    t = str(aviso).strip()
    t = t.replace(" | ", "\n• ")
    if not t.startswith("•"):
        t = "• " + t
    return t


def _draw_aviso_box(
    c: canvas.Canvas,
    x: float,
    y_top: float,
    w: float,
    aviso_text: str,
    title: str,
    font_small: float,
    max_lines: int,
    margin_inside: float = 10,
) -> float:
    """
    Dibuja una caja con avisos (si hay espacio en la página).

    - max_lines limita el tamaño final del bloque.
    - retorna y_top actualizado.
    """
    if not aviso_text:
        return y_top

    line_h = 9.0
    title_h = 14
    body_h = max_lines * line_h + 6
    box_h = title_h + body_h + 10

    _box_stroked(c, x, y_top, w, box_h, radius=8, stroke_color=BORDER_GEN, stroke_width=BORDER_W_THIN)

    c.setFont("Helvetica-Bold", font_small)
    c.setFillColor(colors.black)
    c.drawString(x + margin_inside, y_top - 14, title)

    body = _normalizar_aviso_texto(aviso_text)
    _draw_wrapped_lines(
        c,
        x=x + margin_inside,
        y=y_top - 28,
        text=body,
        max_width=(w - 2 * margin_inside),
        font_name="Helvetica",
        font_size=8.0,
        line_h=line_h,
        max_lines=max_lines,
    )

    return y_top - (box_h + 12)


# =============================================================================
# PDF PRINCIPAL
# =============================================================================

def generar_informe_pdf_bytes(
    muestra: Mapping[str, Any],
    logo_path: str = "hubu_escudo.png",
) -> bytes:
    """
    Genera el PDF (1 página A4) y devuelve el contenido como bytes.

    Parámetros
    ----------
    muestra : Mapping[str, Any]
        Diccionario con los campos integrados (Excel+PDF) y derivados (cutoffs/avisos).
    logo_path : str
        Ruta por defecto del logo si no viene en settings.

    Retorna
    -------
    bytes
        PDF final en memoria.
    """
    # -------------------------------------------------------------------------
    # 1) Carga de settings y configuración por secciones
    # -------------------------------------------------------------------------
    settings = load_settings()
    cfg_pdf = settings.get("pdf", {})
    cfg_cli = settings.get("clinico", {})
    cfg_avisos = cfg_cli.get("avisos", {})
    cfg_mmt = cfg_cli.get("mmt_ranges", {})

    section_titles = cfg_pdf.get("section_titles", {})
    if not isinstance(section_titles, dict):
        section_titles = {}

    def T(key: str, fallback: str) -> str:
        """
        Traduce/renombra el título de una sección si existe en settings["pdf"]["section_titles"].
        """
        v = section_titles.get(key)
        return str(v) if v not in (None, "") else fallback

    # -------------------------------------------------------------------------
    # 2) Logo: puede venir desde settings. Si es ruta relativa, la anclamos al
    #    directorio del módulo para que funcione en ejecución local / .exe
    # -------------------------------------------------------------------------
    logo_path = cfg_pdf.get("logo_path", logo_path)
    base_dir = os.path.dirname(__file__)
    if logo_path and not os.path.isabs(logo_path):
        logo_path = os.path.join(base_dir, logo_path)

    # -------------------------------------------------------------------------
    # 3) Layout base página
    # -------------------------------------------------------------------------
    width, height = A4
    margin = 36

    # Evitar que el contenido invada el pie de página
    min_y_allowed = margin + FOOTER_HEIGHT
    y = height - margin

    # Para mapas: reducimos margen lateral y ganamos ancho (evita cortar nombres)
    MARGIN_WIDE_MAPS = 18

    # Tipografías base
    font_h1 = 12
    font_h2 = 10
    font_body = 9
    font_small = 8

    # -------------------------------------------------------------------------
    # 4) Datos comunes para cabecera / identificación
    # -------------------------------------------------------------------------
    nhc = _fmt(muestra.get("nhc"), "No disponible")
    sample_id = _fmt(muestra.get("sample_id"), "No consta")
    ronda = _fmt(muestra.get("ronda"), "No consta")
    celularidad = _fmt(muestra.get("celularidad"), "No consta")
    fecha_excel = _fmt(muestra.get("fecha_excel"), "No informada")

    fecha_mmt = _fmt(muestra.get("fecha_informe_mmt"), "No informada")
    fecha_gen = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Tabla simple genes (solo para fallback si se apaga el panel integrado)
    genes = [
        ("ERBB2", _fmt(muestra.get("ERBB2_value"), "—"), _fmt(muestra.get("ERBB2_status"), "No consta")),
        ("ESR1",  _fmt(muestra.get("ESR1_value"), "—"),  _fmt(muestra.get("ESR1_status"), "No consta")),
        ("PGR",   _fmt(muestra.get("PGR_value"), "—"),   _fmt(muestra.get("PGR_status"), "No consta")),
        ("MKI67", _fmt(muestra.get("MKI67_value"), "—"), _fmt(muestra.get("MKI67_status"), "No consta")),
    ]

    # -------------------------------------------------------------------------
    # 5) Canvas + buffer en memoria
    # -------------------------------------------------------------------------
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    # -------------------------------------------------------------------------
    # CABECERA
    # -------------------------------------------------------------------------
    c.setFont("Helvetica-Bold", font_h1)
    c.drawString(margin, y, _fmt(cfg_pdf.get("titulo_servicio"), "SERVICIO DE ANATOMÍA PATOLÓGICA – HUBU"))
    y -= 16

    c.setFont("Helvetica-Bold", font_h2)
    c.drawString(margin, y, _fmt(cfg_pdf.get("titulo_informe"), "INFORME INTEGRADO IHQ + MammaTyper®"))
    y -= 10

    # Logo arriba derecha (si existe)
    if logo_path and os.path.exists(logo_path):
        try:
            img = ImageReader(logo_path)
            iw, ih = img.getSize()
            if ih:
                scale = 28 / ih
                lw = iw * scale
                lh = ih * scale
                c.drawImage(
                    img,
                    width - margin - lw,
                    height - margin - lh + 6,
                    width=lw,
                    height=lh,
                    mask="auto",
                )
        except Exception:
            # El informe debe generarse aunque el logo falle
            pass

    y -= 12

    # -------------------------------------------------------------------------
    # IDENTIFICACIÓN (opcional)
    # -------------------------------------------------------------------------
    if cfg_pdf.get("mostrar_identificacion", True):
        box_h = 54
        _box_stroked(c, margin, y, width - 2 * margin, box_h, radius=8, stroke_color=BORDER_GEN, stroke_width=BORDER_W_THIN)
        y_inside = y - 16

        c.setFont("Helvetica-Bold", font_small)
        c.drawString(margin + 10, y_inside + 8, T("identificacion", "Identificación"))
        c.setFont("Helvetica", font_body)

        c.drawString(margin + 10, y_inside - 6, f"NHC: {nhc}")
        c.drawString(margin + 240, y_inside - 6, f"Sample ID: {sample_id}")
        c.drawString(margin + 10, y_inside - 20, f"Ronda: {ronda}   |   Celularidad: {celularidad}")
        c.drawString(margin + 10, y_inside - 34, f"Fecha IHQ (Excel): {fecha_excel}   |   Fecha informe MMT: {fecha_mmt}")

        y -= (box_h + 14)

    # -------------------------------------------------------------------------
    # PANEL INTEGRADO (recomendado)
    # -------------------------------------------------------------------------
    if cfg_pdf.get("mostrar_panel_integrado", True):
        y = _draw_panel_resumen_integrado(
            c=c,
            x=margin,
            y_top=y,
            w=(width - 2 * margin),
            muestra=muestra,
            settings_mmt=cfg_mmt,
        )
    else:
        # Fallback: tabla simple de genes si alguien desactiva el panel
        if cfg_pdf.get("mostrar_tabla_genes", True):
            c.setFont("Helvetica-Bold", font_small)
            c.setFillColor(colors.black)
            c.drawString(margin, y, T("tabla_genes", "MammaTyper® – Biomarcadores qRT-PCR"))
            y -= 8

            table_h = 66
            _box_stroked(c, margin, y, width - 2 * margin, table_h, radius=8, stroke_color=BORDER_PDF, stroke_width=BORDER_W_THICK)

            c.setFont("Helvetica-Bold", font_small)
            c.drawString(margin + 10, y - 14, "Gen")
            c.drawString(margin + 110, y - 14, "Valor")
            c.drawString(margin + 210, y - 14, "Estado")

            c.setFont("Helvetica", font_body)
            yy = y - 28
            for g, val, stt in genes:
                c.drawString(margin + 10, yy, g)
                c.drawString(margin + 110, yy, val)
                c.drawString(margin + 210, yy, stt)
                yy -= 12

            y -= (table_h + 14)

    # -------------------------------------------------------------------------
    # MAPAS TIPO MammaTyper (barras con gradiente + thresholds + valor)
    # -------------------------------------------------------------------------
    if cfg_pdf.get("mostrar_mapas_calor", True):
        c.setFont("Helvetica-Bold", font_small)
        c.setFillColor(colors.black)
        c.drawString(margin, y, T("mapas_calor", "Mapas de calor (MammaTyper®) – Rojo: Valor. Negro: Límites"))
        y -= 12

        # Barra más ancha (menor margen lateral)
        x_bar = MARGIN_WIDE_MAPS
        w_bar = width - 2 * MARGIN_WIDE_MAPS

        # Helper: merge de cfg por gen con fallback si falta algo
        def _get_gene_cfg(g: str, fallback: dict) -> dict:
            xcfg = cfg_mmt.get(g, {}) or {}
            out = dict(fallback)
            out.update({k: xcfg.get(k, out.get(k)) for k in out.keys()})
            if xcfg.get("labels"):
                out["labels"] = xcfg["labels"]
            if xcfg.get("thresholds") is not None:
                out["thresholds"] = xcfg["thresholds"]
            return out

        # Fallbacks por gen (si settings no tiene mmt_ranges definidos)
        ERBB2_F = {
            "vmin": 34.0, "vmax": 42.0, "thresholds": [38.3, 40.4],
            "labels": [
                {"text": "HER2 zero/ultra low", "pos": 36.5},
                {"text": "HER2 Low", "pos": 39.1},
                {"text": "HER2 Positive", "pos": 41.2},
            ],
        }
        ESR1_F = {
            "vmin": 34.0, "vmax": 42.0, "thresholds": [37.1, 38.2],
            "labels": [
                {"text": "ER Negative", "pos": 35.5},
                {"text": "ER Low Positive", "pos": 37.6},
                {"text": "ER Positive", "pos": 40.4},
            ],
        }
        PGR_F = {
            "vmin": 34.0, "vmax": 42.0, "thresholds": [35.0, 36.3],
            "labels": [
                {"text": "PR Negative", "pos": 34.8},
                {"text": "PR Positive", "pos": 40.4},
            ],
        }
        MKI67_F = {
            "vmin": 32.0, "vmax": 40.0, "thresholds": [35.1, 36.3, 37.0, 37.7],
            "labels": [
                {"text": "Ki-67 Negative", "pos": 33.2},
                {"text": "Ki-67 Positive", "pos": 37.2},
            ],
        }

        # HER2 (ERBB2)
        gcfg = _get_gene_cfg("ERBB2", ERBB2_F)
        y = _draw_mmt_bar(
            c, x_bar, y, w_bar,
            title="HER2 (ERBB2)",
            value_raw=muestra.get("ERBB2_value"),
            status=_fmt(muestra.get("ERBB2_status"), "NC"),
            vmin=float(gcfg["vmin"]), vmax=float(gcfg["vmax"]),
            thresholds=[float(x) for x in (gcfg.get("thresholds") or [])],
            labels=[(lab["text"], float(lab["pos"])) for lab in (gcfg.get("labels") or [])],
        )

        # ER (ESR1)
        gcfg = _get_gene_cfg("ESR1", ESR1_F)
        y = _draw_mmt_bar(
            c, x_bar, y, w_bar,
            title="ER (ESR1)",
            value_raw=muestra.get("ESR1_value"),
            status=_fmt(muestra.get("ESR1_status"), "NC"),
            vmin=float(gcfg["vmin"]), vmax=float(gcfg["vmax"]),
            thresholds=[float(x) for x in (gcfg.get("thresholds") or [])],
            labels=[(lab["text"], float(lab["pos"])) for lab in (gcfg.get("labels") or [])],
        )

        # PR (PGR)
        gcfg = _get_gene_cfg("PGR", PGR_F)
        y = _draw_mmt_bar(
            c, x_bar, y, w_bar,
            title="PR (PGR)",
            value_raw=muestra.get("PGR_value"),
            status=_fmt(muestra.get("PGR_status"), "NC"),
            vmin=float(gcfg["vmin"]), vmax=float(gcfg["vmax"]),
            thresholds=[float(x) for x in (gcfg.get("thresholds") or [])],
            labels=[(lab["text"], float(lab["pos"])) for lab in (gcfg.get("labels") or [])],
        )

        # Ki-67 (MKI67)
        gcfg = _get_gene_cfg("MKI67", MKI67_F)
        y = _draw_mmt_bar(
            c, x_bar, y, w_bar,
            title="Ki-67 (MKI67)",
            value_raw=muestra.get("MKI67_value"),
            status=_fmt(muestra.get("MKI67_status"), "NC"),
            vmin=float(gcfg["vmin"]), vmax=float(gcfg["vmax"]),
            thresholds=[float(x) for x in (gcfg.get("thresholds") or [])],
            labels=[(lab["text"], float(lab["pos"])) for lab in (gcfg.get("labels") or [])],
        )

        # Nota: no dibujamos un rectángulo externo rojo envolviendo todo el bloque
        # porque puede “cortar” etiquetas si hay poco margen.
        y -= 8

    # -------------------------------------------------------------------------
    # VISUAL CUT-OFFS (Δabs)
    # -------------------------------------------------------------------------
    if cfg_pdf.get("mostrar_visual_cutoffs", True):
        est_h = 14 + 4 * 14 + 14 + 14
        if y - est_h > min_y_allowed:
            y = _draw_mmt_proximity_visual(
                c=c,
                x=margin,
                y_top=y,
                w=(width - 2 * margin),
                muestra=muestra,
                max_delta=float(cfg_pdf.get("cutoffs_visual_max_delta", 1.0)),
            )

    # -------------------------------------------------------------------------
    # AVISOS (si hay espacio)
    # -------------------------------------------------------------------------
    aviso_txt = _fmt(muestra.get("aviso"), "")
    incluir_avisos = bool(cfg_avisos.get("activar", True) and cfg_avisos.get("incluir_en_pdf", True))

    if incluir_avisos and aviso_txt and aviso_txt != "No consta":
        max_lines_aviso = int(cfg_pdf.get("max_lines_aviso", 4))
        est_h = 14 + (max_lines_aviso * 9.0) + 22

        if y - est_h > min_y_allowed:
            titulo_aviso = _fmt(cfg_avisos.get("texto_cabecera_pdf"), "Avisos / Revisión")
            y = _draw_aviso_box(
                c=c,
                x=margin,
                y_top=y,
                w=(width - 2 * margin),
                aviso_text=aviso_txt,
                title=titulo_aviso,
                font_small=font_small,
                max_lines=max_lines_aviso,
            )

    # -------------------------------------------------------------------------
    # PIE DE PÁGINA (siempre)
    # -------------------------------------------------------------------------
    c.saveState()
    c.setFillColor(colors.black)
    c.setFont("Helvetica", FOOTER_FONT)

    y_footer_top = margin + FOOTER_HEIGHT - 12
    y_footer_bottom = margin + 8

    disclaimer = _fmt(cfg_pdf.get("footer_disclaimer"), "")
    _draw_wrapped_lines(
        c,
        x=margin,
        y=y_footer_top,
        text=disclaimer,
        max_width=(width - 2 * margin),
        font_name="Helvetica",
        font_size=FOOTER_FONT,
        line_h=FOOTER_LINE_H,
        max_lines=2,
    )

    if cfg_pdf.get("mostrar_footer_firmantes", True):
        c.drawString(margin, y_footer_bottom, f"Firmantes (Patwin): {_fmt(muestra.get('firmantes_diag'), 'No consta')}")

    c.drawRightString(width - margin, y_footer_bottom, f"Generado: {fecha_gen}")
    c.restoreState()

    # Finalizar PDF
    c.showPage()
    c.save()
    return buf.getvalue()