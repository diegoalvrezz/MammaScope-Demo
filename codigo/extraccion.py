import re
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
from pypdf import PdfReader

from discordancia import construir_aviso_rico
from ajustes import load_settings


# =============================================================================
# EXTRACCIÓN Y FUSIÓN DE DATOS (Patwin Excel + PDF MammaTyper)
# =============================================================================
# Objetivo de este módulo:
#   1) Leer el Excel de Patwin (texto clínico “pegado” en una columna) y extraer
#      variables de IHQ (ER/PR/Ki-67/HER2/P53/CK19, firmantes, fecha, etc.).
#   2) Leer el PDF de MammaTyper y extraer variables de qRT-PCR (valores y estado
#      de ESR1/PGR/ERBB2/MKI67, subtipo, fecha informe, etc.).
#   3) Fusionar ambos registros por sample_id y:
#        - calcular derivados MMT (cutoff más cercano, delta, equivalencias)
#        - construir avisos clínicos automáticos (construir_aviso_rico)
#
# Nota de compatibilidad:
#   - Uso Optional[...] en lugar de "str | None" por compatibilidad con Python < 3.10.
# =============================================================================


# =============================================================================
# EXCEL (Patwin / IHQ)
# =============================================================================

def _extraer_sample_id(texto: str) -> Optional[str]:
    """
    Extrae un identificador de muestra con patrón típico de Patwin:
        - 25B11111
        - 25B1 4444
        - 25B1888888
    Devuelve siempre el sample_id SIN espacios: 25B11111, 25B14444, etc.

    Parámetros
    ----------
    texto : str
        Texto completo de la celda/registro.

    Retorna
    -------
    Optional[str]
        sample_id normalizado o None si no se encuentra.
    """
    if not texto:
        return None

    # 2 dígitos + 'B' + 4..9 dígitos permitiendo espacios intermedios
    m = re.search(r"(\d{2}B(?:\s*\d){4,9})", str(texto))
    if not m:
        return None

    bruto = m.group(1)
    return re.sub(r"\s+", "", bruto)


def _extraer_her2_ihq(texto: str) -> Optional[str]:
    """
    Extrae el bloque de HER2 por IHQ del texto Patwin.

    Requisitos:
      - Capturar SOLO la parte de HER2 (sin arrastrar Ki-67, CK19, etc.)
      - No confundir con resultados de ISH/SISH (HER2/CEP, ratio, etc.)

    Retorna el fragmento textual de HER2 IHQ (p.ej. "POSITIVO (+++)", "NEGATIVO (ULTRA LOW)").
    """
    if not texto:
        return None

    patrones: List[Tuple[str, int]] = [
        # Caso tipo: " - 4B5 (HER2). POSITIVO (+++).  - KI67: 60%..."
        (r"4B5\s*\(HER2\)\.\s*([^.]+)", 1),

        # Caso clásico: "4B5: NEGATIVO (ULTRA LOW) ... "
        (r"4B5[^:]{0,40}:\s*([^.]+)", 1),

        # HER2 escrito como HER-2 / HER 2 / etc. (evitando capturar formatos de SISH con '/')
        (r"HER[-\s]*2[^:/]{0,40}:\s*([^.]+)", 1),

        # HER2NEU: (distinto de HER2/NEU Ratio de SISH)
        (r"HER2NEU[^:]{0,10}:\s*([^.]+)", 1),
    ]

    for pat, grp in patrones:
        m = re.search(pat, texto, flags=re.IGNORECASE)
        if not m:
            continue

        raw = m.group(grp)

        # Cortamos antes de otros marcadores si vienen como "- " o salto de línea con guión
        raw = re.split(r"(?:\n\s*-\s+| - )", raw)[0]
        return raw.strip()

    return None


def _extraer_firmantes(texto: str) -> Optional[str]:
    """
    Extrae la cadena de firmantes a partir de:
        'Fdo.: Gómez Jiménez / Tinajero Ramírez'
    Devuelve solo la parte de nombres, sin 'Fdo.'.

    Retorna None si no hay firmantes.
    """
    if not texto:
        return None

    m = re.search(r"Fdo\.\s*:?\s*(.+)", texto, flags=re.IGNORECASE)
    if not m:
        return None

    firmantes = re.sub(r"\s+", " ", m.group(1).strip())
    return firmantes or None


def _extraer_fecha_excel(texto: str) -> Optional[str]:
    """
    Extrae una fecha del texto del Excel en formatos habituales:
      - 'Burgos a, 02/10/2052'
      - 'Burgos a, 6 de noviembre de 2025'
      - '02/10/2052'
      - '6 de noviembre de 2025'

    Normaliza a 'dd/mm/aaaa' (como string).

    Nota:
      - Si el año viene con 2 dígitos, se asume 20xx.
    """
    if not texto:
        return None

    # 1) Numérico: 02/10/2052 o 2-10-25
    patron_num = r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})"
    m_num = re.search(patron_num, texto)
    if m_num:
        dia, mes, anio = m_num.groups()
        dia = dia.zfill(2)
        mes = mes.zfill(2)
        if len(anio) == 2:
            anio = "20" + anio
        return f"{dia}/{mes}/{anio}"

    # 2) Texto: 6 de noviembre de 2025
    patron_texto = (
        r"(\d{1,2})\s+de\s+"
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
        r"\s+de\s+(\d{4})"
    )
    m_txt = re.search(patron_texto, texto, flags=re.IGNORECASE)
    if not m_txt:
        return None

    dia, mes_texto, anio = m_txt.groups()

    meses = {
        "enero": "01",
        "febrero": "02",
        "marzo": "03",
        "abril": "04",
        "mayo": "05",
        "junio": "06",
        "julio": "07",
        "agosto": "08",
        "septiembre": "09",
        "octubre": "10",
        "noviembre": "11",
        "diciembre": "12",
    }

    mes_num = meses[mes_texto.lower()]
    return f"{dia.zfill(2)}/{mes_num}/{anio}"


def _extraer_pct_receptor(texto: str, tipo: str) -> Optional[float]:
    """
    Extrae el porcentaje (%) de células tumorales positivas para receptor hormonal.

    Parámetros
    ----------
    texto : str
        Texto Patwin.
    tipo : str
        "ER" -> bloque RECEPTORES DE ESTRÓGENOS
        "PR" -> bloque RECEPTORES DE PROGESTERONA

    Retorna
    -------
    Optional[float]
        Porcentaje (float) o None si no se encuentra.
    """
    if not texto:
        return None

    if tipo == "ER":
        patron_bloque = (
            r"RECEPTORES\s+DE\s+ESTR[ÓO]GENOS:?(.+?)"
            r"(?:RECEPTORES\s+DE\s+PROGESTERONA|FACTORES\s+PRON[ÓO]STICOS|"
            r"FACTORES\s+PRONOSTICOS|P-?\s*53|Ki\s*-?\s*67|CK-?19|Burgos|$)"
        )
    else:  # PR
        patron_bloque = (
            r"RECEPTORES\s+DE\s+PROGESTERONA[:\.]?(.+?)"
            r"(?:FACTORES\s+PRON[ÓO]STICOS|FACTORES\s+PRONOSTICOS|"
            r"P-?\s*53|Ki\s*-?\s*67|CK-?19|Burgos|$)"
        )

    m = re.search(patron_bloque, texto, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None

    bloque = m.group(1)

    # Cogemos el último porcentaje encontrado en el bloque (si hay varios)
    matches = re.findall(
        r"en\s+el\s+(\d+)\s*%\s+de\s+(?:los\s+n[úu]cleos\s+de\s+)?las\s+c[ée]lulas\s+tumorales",
        bloque,
        flags=re.IGNORECASE,
    )
    if not matches:
        return None

    return float(matches[-1])


def _extraer_her2_score(her2_ihq: Optional[str]) -> Optional[str]:
    """
    A partir del texto HER2 IHQ, infiere un score normalizado:
      - "0", "1+", "2+", "3+"

    Retorna None si no se reconoce.
    """
    if not her2_ihq:
        return None

    t = her2_ihq.lower()

    if re.search(r"\b3\+\b", t) or "+++" in t:
        return "3+"
    if re.search(r"\b2\+\b", t) or "(++)" in t or "++" in t:
        return "2+"
    if re.search(r"\b1\+\b", t) or "(+)" in t or " 1+" in t:
        return "1+"
    if "score 0" in t or re.search(r"\b0\b", t):
        return "0"

    return None


def _extraer_receptor(texto: str, tipo: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extrae receptor hormonal ER/PR desde el texto Patwin.

    Devuelve:
      - status: "Positivo" / "Negativo" / None
      - intensidad: "+++/+++" / "++/+++" / "+" / "++" ... o None

    Nota:
      - Se captura la intensidad si aparece entre paréntesis como (+/+++), (++), etc.
    """
    if not texto:
        return None, None

    if tipo == "ER":
        patron = r"RECEPTORES\s+DE\s+ESTROGENOS\s*:\s*([^\n\.]+)"
    elif tipo == "PR":
        patron = r"RECEPTORES\s+DE\s+PROGESTERONA\s*:\s*([^\n\.]+)"
    else:
        return None, None

    m = re.search(patron, texto, flags=re.IGNORECASE)
    if not m:
        return None, None

    detalle = m.group(1).strip()
    low = detalle.lower()

    # Estado (positivo/negativo)
    if "positiv" in low:
        status = "Positivo"
    elif "negativ" in low:
        status = "Negativo"
    else:
        status = None

    # Intensidad dentro de paréntesis
    inten = None
    m_int = re.search(r"\((\+{1,3}(?:\s*\/\s*\+{1,3})?)\)", detalle)
    if m_int:
        inten = m_int.group(1).replace(" ", "")

    return status, inten


def _extraer_p53_ihq(texto: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Extrae P53 por IHQ desde el texto Patwin.

    Retorna (status, porcentaje):
      - status: "Wild-type", "Mutado", "Positivo", "Negativo" o None
      - porcentaje: int (0-100) o None
    """
    if not texto:
        return None, None

    m = re.search(r"P\s*-?\s*53\s*:\s*([^\n\.]+)", texto, flags=re.IGNORECASE)
    if not m:
        return None, None

    detalle = m.group(1).strip().lower()

    pct_match = re.search(r"(\d{1,3})\s*[%％]", detalle)
    pct = int(pct_match.group(1)) if pct_match else None

    if "wild" in detalle:
        status = "Wild-type"
    elif "mutad" in detalle:
        status = "Mutado"
    elif "positiv" in detalle or "focal" in detalle:
        status = "Positivo"
    elif "negativ" in detalle:
        status = "Negativo"
    else:
        status = None

    return status, pct


def _extraer_ck19_ihq(texto: str) -> Optional[str]:
    """
    Extrae CK19 por IHQ.
    Devuelve "Positiva" / "Negativa" o None si no se reconoce.
    """
    if not texto:
        return None

    m = re.search(r"CK-?19\s*:\s*([^\n\.]+)", texto, flags=re.IGNORECASE)
    if not m:
        return None

    detalle = m.group(1).strip().lower()
    if "positiv" in detalle:
        return "Positiva"
    if "negativ" in detalle:
        return "Negativa"
    return None


def _extraer_ki67_ihq(texto: str) -> Optional[int]:
    """
    Extrae el porcentaje de Ki-67 por IHQ.
    Retorna un entero (0-100) o None.

    Nota:
      - Permitimos 1-3 dígitos por robustez (p.ej. 5%, 30%, 100%).
    """
    if not texto:
        return None

    patron = re.compile(r"KI?\s*[- ]*\s*67[^0-9]{0,10}(\d{1,3})\s*%", re.IGNORECASE)
    m = patron.search(texto)
    if not m:
        return None

    try:
        return int(m.group(1))
    except ValueError:
        return None


def _extraer_her2_sish(texto: str) -> Optional[str]:
    """
    Extrae el resultado de HER2 por SISH/ISH si aparece en el texto Patwin.

    Retorna:
      - "Con amplificación (SISH)"
      - "Sin amplificación (SISH)"
      - "Resultado SISH indeterminado"
      - None si no hay indicios de SISH/ISH.
    """
    if not texto:
        return None

    t = texto.lower()
    if "sish" not in t and "hibridación" not in t:
        return None

    if "sin amplificación" in t or "no se observa amplificación" in t:
        return "Sin amplificación (SISH)"
    if "amplificación" in t:
        return "Con amplificación (SISH)"

    return "Resultado SISH indeterminado"


def clasificar_her2_final(her2_ihq: Optional[str], her2_sish: Optional[str]) -> Optional[str]:
    """
    Clasifica HER2 final combinando IHQ y SISH.

    Reglas:
      1) Si hay SISH, prevalece sobre IHQ.
      2) Si no hay SISH, se intenta clasificar por IHQ.

    Retorna un texto normalizado o None si no hay datos.
    """
    # 1) SISH manda
    if her2_sish:
        low = her2_sish.lower()
        if "con amplificación" in low:
            return "HER2 positivo (SISH)"
        if "sin amplificación" in low or "no se observa amplificación" in low:
            return "HER2 negativo (SISH)"
        return "HER2 indeterminado (SISH)"

    # 2) IHQ
    if not her2_ihq:
        return None

    low = her2_ihq.lower()

    if "+++" in low or "3+" in low:
        return "HER2 positivo (IHQ)"
    if "equivoc" in low or "2+" in low or "(++)" in low:
        return "HER2 equívoco (IHQ)"
    if "low" in low or "ultra low" in low or "ultralow" in low:
        return "HER2 low (IHQ)"
    if "negativ" in low:
        return "HER2 negativo (IHQ)"

    return None


def _detectar_columna_texto(df: pd.DataFrame) -> Any:
    """
    Intenta identificar la columna del Excel donde está el texto clínico.
    Heurística:
      - Busca en las primeras filas si aparece la palabra "BIOPSIA".
      - Si no se encuentra, usa la última columna.

    Retorna el nombre/índice real de la columna (puede ser int si header=None).
    """
    for col in df.columns:
        serie = df[col].dropna()
        if serie.empty:
            continue
        muestra = " ".join(str(x) for x in serie.head(10))
        if "BIOPSIA" in muestra.upper():
            return col
    return df.columns[-1]


def extraer_registros_patwin(excel_file) -> List[Dict[str, Any]]:
    """
    Lee el Excel de Patwin (texto clínico en una columna) y devuelve una lista de
    diccionarios con la información IHQ relevante, uno por muestra.

    Cada registro contiene (entre otros):
      - sample_id
      - HER2 por IHQ/SISH (y clasificación final)
      - ER/PR (estado + intensidad + porcentajes)
      - Ki67, P53, CK19
      - firmantes, fecha_excel
    """
    df = pd.read_excel(excel_file, header=None)
    col_texto = _detectar_columna_texto(df)

    registros: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        bruto = row[col_texto]
        if pd.isna(bruto):
            continue

        texto = str(bruto)

        # Identificador de muestra (clave para fusionar con PDF)
        sample_id = _extraer_sample_id(texto)
        if not sample_id:
            continue

        # Fecha del informe en Excel (normalizada)
        fecha_excel = _extraer_fecha_excel(texto)

        # HER2
        her2_ihq = _extraer_her2_ihq(texto)
        her2_sish = _extraer_her2_sish(texto)
        her2_final = clasificar_her2_final(her2_ihq, her2_sish)
        her2_score = _extraer_her2_score(her2_ihq)

        # Receptores hormonales
        er_status, er_int = _extraer_receptor(texto, "ER")
        pr_status, pr_int = _extraer_receptor(texto, "PR")
        er_pct = _extraer_pct_receptor(texto, "ER")
        pr_pct = _extraer_pct_receptor(texto, "PR")

        # Otros marcadores
        ki67_ihq = _extraer_ki67_ihq(texto)
        p53_status, p53_pct = _extraer_p53_ihq(texto)
        ck19_status = _extraer_ck19_ihq(texto)

        # Firmantes
        firmantes = _extraer_firmantes(texto)

        registros.append(
            {
                "sample_id": sample_id,

                # HER2 (IHQ/SISH)
                "ERBB2_IHQ_SISH": her2_ihq,
                "HER2_SISH_result": her2_sish,
                "HER2_final": her2_final,
                "HER2_IHQ_score": her2_score,

                # Receptores hormonales IHQ
                "ESR1_IHQ": er_status,
                "ESR1_IHQ_intensidad": er_int,
                "ESR1_IHQ_pct": er_pct,

                "PGR_IHQ": pr_status,
                "PGR_IHQ_intensidad": pr_int,
                "PGR_IHQ_pct": pr_pct,

                # Ki67 / P53 / CK19
                "KI67_IHQ": ki67_ihq,
                "P53_IHQ_status": p53_status,
                "P53_IHQ_pct": p53_pct,
                "CK19_IHQ_status": ck19_status,

                # Metadatos
                "firmantes_diag": firmantes,
                "fecha_excel": fecha_excel,
            }
        )

    return registros


# =============================================================================
# PDF (MammaTyper) — extracción por página
# =============================================================================

def _extraer_biomarcador(texto: str, nombre: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Extrae (valor, estado) de un biomarcador MammaTyper en el texto del PDF.

    Espera una estructura del tipo:
        <NOMBRE> <valor> <estado>

    Ejemplo típico:
        ESR1 38.2 Positive

    Problema conocido en PDFs reales de MammaTyper:
        El gen aparece también en la tabla de controles ("HEX ESR1\n2\nFAM"),
        lo que hace que re.search() capture esa ocurrencia antes que la de
        resultados (p.ej. "ESR1\n2\nFAM" -> valor=2, estado=FAM).
        Se resuelve iterando TODAS las ocurrencias y eligiendo la que tenga
        un valor de Ct válido (15-50) y un estado reconocible.

    Retorna (None, None) si no se encuentra.
    """
    patron = rf"{nombre}\s+([\d\.,]+)\s+(\w+)"
    estados_validos = {"positive", "negative", "low", "zero", "ultralow"}

    for m in re.finditer(patron, texto):
        valor_str = m.group(1).replace(",", ".")
        estado = m.group(2)
        try:
            valor = float(valor_str)
        except ValueError:
            continue

        # Descartar valores fuera del rango fisiológico de Ct
        if not (15.0 <= valor <= 50.0):
            continue
        # Descartar estados que no son resultados MMT (p.ej. "FAM", "HEX", "B2M")
        if not any(s in estado.lower() for s in estados_validos):
            continue

        return valor, estado

    return None, None


def _extraer_registro_pagina(texto: str) -> Optional[Dict[str, Any]]:
    """
    Extrae UNA muestra desde UNA página del PDF.

    Devuelve un dict con:
      - sample_id
      - fecha_informe
      - subtipo_mmt / subtipo_mmt_detalle
      - valores/estados de ERBB2/ESR1/PGR/MKI67
    """
    lineas = [ln.strip() for ln in texto.splitlines() if ln.strip()]

    # ---------------------------------------------------------
    # 1) Sample ID (clave primaria para fusionar con Excel)
    # ---------------------------------------------------------
    sample_id = None
    for ln in lineas:
        if "Sample ID:" in ln:
            raw = ln.split("Sample ID:")[1].strip()
            # Reutilizamos el mismo extractor que en Excel para normalizar
            sample_id = _extraer_sample_id(raw) or raw.replace(" ", "")
            break

    if not sample_id:
        return None

    # ---------------------------------------------------------
    # 2) Fecha informe
    # ---------------------------------------------------------
    fecha = None
    for ln in lineas:
        if "Date of report:" in ln:
            # Nos quedamos con el primer token (típicamente "YYYY-MM-DD" o similar)
            fecha = ln.split("Date of report:")[1].strip().split()[0]
            break

    # ---------------------------------------------------------
    # 3) Subtipo
    #    (estructura típica del PDF: “Subtype According ...” y líneas siguientes)
    # ---------------------------------------------------------
    subtipo_mmt = None
    subtipo_detalle = None

    idx = None
    for i, ln in enumerate(lineas):
        if "Subtype According" in ln:
            idx = i
            break

    if idx is not None:
        if idx + 2 < len(lineas):
            subtipo_mmt = lineas[idx + 2]
        if idx + 3 < len(lineas):
            subtipo_detalle = lineas[idx + 3]
            # Cortes defensivos si el PDF pega títulos a continuación
            for cortar in ["Biomarker", "ResultsStatus"]:
                if cortar in subtipo_detalle:
                    subtipo_detalle = subtipo_detalle.split(cortar)[0].strip()

    # ---------------------------------------------------------
    # 4) Biomarcadores (valor + status)
    # ---------------------------------------------------------
    erbb2_v, erbb2_s = _extraer_biomarcador(texto, "ERBB2")
    esr1_v, esr1_s = _extraer_biomarcador(texto, "ESR1")
    pgr_v, pgr_s = _extraer_biomarcador(texto, "PGR")
    mk_v, mk_s = _extraer_biomarcador(texto, "MKI67")

    return {
        "nhc": None,  # En PDF normalmente no viene NHC (se mantiene por compatibilidad)
        "sample_id": sample_id,
        "fecha_informe": fecha,
        "subtipo_mmt": subtipo_mmt,
        "subtipo_mmt_detalle": subtipo_detalle,
        "ERBB2_value": erbb2_v,
        "ERBB2_status": erbb2_s,
        "ESR1_value": esr1_v,
        "ESR1_status": esr1_s,
        "PGR_value": pgr_v,
        "PGR_status": pgr_s,
        "MKI67_value": mk_v,
        "MKI67_status": mk_s,
        "texto_parcial": texto[:2000],  # útil en depuración/validación visual
    }


def extraer_registros_pdf(file) -> List[Dict[str, Any]]:
    """
    Devuelve una lista de registros del PDF, asumiendo “1 muestra por página”.

    Si una página no contiene texto extraíble o no se detecta sample_id, se ignora.
    """
    reader = PdfReader(file)
    registros: List[Dict[str, Any]] = []

    for page in reader.pages:
        txt = page.extract_text()
        if not txt:
            continue
        reg = _extraer_registro_pagina(txt)
        if reg:
            registros.append(reg)

    return registros


# =============================================================================
# DERIVADOS MMT: cutoffs (nearest/delta) + equivalencias por gene
# =============================================================================

def _to_float_local(x: Any) -> Optional[float]:
    """Convierte a float de forma segura (acepta coma decimal)."""
    try:
        if x is None:
            return None
        return float(str(x).replace(",", "."))
    except Exception:
        return None


def _equiv_mmt(gene: str, v: float, ths_sorted: List[float]) -> Optional[str]:
    """
    Traduce un valor MMT a una etiqueta de “zona/equivalencia” usando thresholds.

    Convenciones usadas:
      - ERBB2: [t1, t2] -> zero/ultra-low, low, positivo
      - ESR1:  [t1, t2] -> <1%, 1–10%, ≥10%
      - PGR:   [t1, t2] -> <1%, 1–20%, ≥20%
      - MKI67: [t0, t1, t2, t3] -> aproximación 5/20/30/60 con interpolación lineal
    """
    g = (gene or "").upper().strip()

    if g == "ERBB2" and len(ths_sorted) >= 2:
        t1, t2 = ths_sorted[0], ths_sorted[1]
        return "zero/ultra-low" if v < t1 else ("low" if v < t2 else "positivo")

    if g == "ESR1" and len(ths_sorted) >= 2:
        t1, t2 = ths_sorted[0], ths_sorted[1]
        return "<1%" if v < t1 else ("1–10%" if v < t2 else "≥10%")

    if g == "PGR" and len(ths_sorted) >= 2:
        t1, t2 = ths_sorted[0], ths_sorted[1]
        return "<1%" if v < t1 else ("1–20%" if v < t2 else "≥20%")

    if g == "MKI67" and len(ths_sorted) >= 4:
        t0, t1, t2, t3 = ths_sorted[0], ths_sorted[1], ths_sorted[2], ths_sorted[3]
        if v <= t0:
            return "≤5%"
        if v >= t3:
            return "≥60%"

        pts = [(t0, 5.0), (t1, 20.0), (t2, 30.0), (t3, 60.0)]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= v <= x1:
                t = 0.0 if x1 == x0 else (v - x0) / (x1 - x0)
                y = y0 + t * (y1 - y0)
                return f"~{int(round(y))}%"

    return None


def _enriquecer_mmt_cutoffs(m: Dict[str, Any], cfg_mmt: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enriquece el diccionario de muestra combinada con campos derivados por gen:

      - {GEN}_cutoff_nearest : threshold más cercano (float)
      - {GEN}_delta_cutoff   : |valor - nearest| (float)
      - {GEN}_equiv          : etiqueta de equivalencia (str)

    Fuente de thresholds:
      settings["clinico"]["mmt_ranges"][GEN]["thresholds"]

    Importante:
      - Esta función NO depende del PDF/Excel: solo necesita que existan {GEN}_value.
      - Si falta value o thresholds, deja None en los derivados.
    """
    genes = ["ERBB2", "ESR1", "PGR", "MKI67"]

    for g in genes:
        v = _to_float_local(m.get(f"{g}_value"))
        thresholds = (cfg_mmt.get(g, {}) or {}).get("thresholds") or []

        ths: List[float] = []
        for t in thresholds:
            try:
                if t is None:
                    continue
                ths.append(float(t))
            except Exception:
                continue
        ths_sorted = sorted(ths)

        near = None
        delta = None
        eq = None

        if v is not None and ths_sorted:
            near = min(ths_sorted, key=lambda t: abs(v - t))
            delta = abs(v - near)
            eq = _equiv_mmt(g, v, ths_sorted)

        m[f"{g}_cutoff_nearest"] = near
        m[f"{g}_delta_cutoff"] = delta
        m[f"{g}_equiv"] = eq

    return m


# =============================================================================
# FUSIÓN EXCEL + PDF
# =============================================================================

def fusionar_registro_patwin_pdf(reg_excel: Dict[str, Any], reg_pdf: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fusiona un registro Patwin (Excel) con un registro MammaTyper (PDF)
    que comparten el mismo sample_id.

    Resultado:
      - Diccionario “combinado” listo para:
          * guardarse en BD (tabla muestras)
          * generar avisos
          * calcular derivados de cutoffs/deltas/equivalencias

    Nota:
      - Si los sample_id no coinciden (caso raro), se genera un aviso de mismatch.
    """
    id_excel = reg_excel.get("sample_id")
    id_pdf = reg_pdf.get("sample_id")

    combinado: Dict[str, Any] = {}

    # ---------------------------------------------------------
    # 1) Identificadores (clave de fusión)
    # ---------------------------------------------------------
    combinado["nhc"] = reg_excel.get("nhc") or reg_pdf.get("nhc")
    combinado["sample_id"] = id_pdf or id_excel

    # ---------------------------------------------------------
    # 2) Contexto desde Excel (si existe)
    # ---------------------------------------------------------
    combinado["ronda"] = reg_excel.get("ronda")
    combinado["celularidad"] = reg_excel.get("celularidad")

    # ---------------------------------------------------------
    # 3) Subtipos (preferencia PDF si existe)
    # ---------------------------------------------------------
    combinado["subtipo_ihq"] = reg_excel.get("subtipo_ihq")
    combinado["subtipo_mmt"] = reg_pdf.get("subtipo_mmt") or reg_excel.get("subtipo_mmt")
    combinado["subtipo_mmt_detalle"] = reg_pdf.get("subtipo_mmt_detalle")

    # ---------------------------------------------------------
    # 4) Fecha del informe MammaTyper (PDF)
    # ---------------------------------------------------------
    combinado["fecha_informe_mmt"] = reg_pdf.get("fecha_informe")

    # ---------------------------------------------------------
    # 5) Marcadores MammaTyper (qRT-PCR) desde PDF
    #    (campos mínimos para métricas MMT y avisos)
    # ---------------------------------------------------------
    for gen in ["ERBB2", "ESR1", "PGR", "MKI67"]:
        combinado[f"{gen}_value"] = reg_pdf.get(f"{gen}_value")
        combinado[f"{gen}_status"] = reg_pdf.get(f"{gen}_status")

    # ---------------------------------------------------------
    # 6) HER2 por IHQ/SISH desde Excel (Patwin)
    # ---------------------------------------------------------
    combinado["ERBB2_IHQ_SISH"] = reg_excel.get("ERBB2_IHQ_SISH")
    combinado["HER2_SISH_result"] = reg_excel.get("HER2_SISH_result")
    combinado["HER2_final"] = reg_excel.get("HER2_final")
    combinado["HER2_IHQ_score"] = reg_excel.get("HER2_IHQ_score")

    # ---------------------------------------------------------
    # 7) Receptores hormonales IHQ (Excel) + % si existen
    # ---------------------------------------------------------
    combinado["ESR1_IHQ"] = reg_excel.get("ESR1_IHQ")
    combinado["ESR1_IHQ_intensidad"] = reg_excel.get("ESR1_IHQ_intensidad")
    combinado["ESR1_IHQ_pct"] = reg_excel.get("ESR1_IHQ_pct")

    combinado["PGR_IHQ"] = reg_excel.get("PGR_IHQ")
    combinado["PGR_IHQ_intensidad"] = reg_excel.get("PGR_IHQ_intensidad")
    combinado["PGR_IHQ_pct"] = reg_excel.get("PGR_IHQ_pct")

    # ---------------------------------------------------------
    # 8) Ki67 / P53 / CK19 desde Excel
    # ---------------------------------------------------------
    combinado["KI67_IHQ"] = reg_excel.get("KI67_IHQ")
    combinado["P53_IHQ_status"] = reg_excel.get("P53_IHQ_status")
    combinado["P53_IHQ_pct"] = reg_excel.get("P53_IHQ_pct")
    combinado["CK19_IHQ_status"] = reg_excel.get("CK19_IHQ_status")

    # ---------------------------------------------------------
    # 9) Firmantes + fecha Excel
    # ---------------------------------------------------------
    combinado["firmantes_diag"] = reg_excel.get("firmantes_diag")
    combinado["fecha_excel"] = reg_excel.get("fecha_excel")

    # ---------------------------------------------------------
    # 10) Derivados MMT (cutoffs/delta/equivalencias)
    #     Se calcula UNA sola vez usando thresholds configurados en settings.
    # ---------------------------------------------------------
    cfg_mmt = load_settings().get("clinico", {}).get("mmt_ranges", {})
    _enriquecer_mmt_cutoffs(combinado, cfg_mmt)

    # ---------------------------------------------------------
    # 11) Avisos automáticos
    # ---------------------------------------------------------
    avisos: List[str] = []

    # Mismatch defensivo (por si llega un PDF/Excel mal alineado)
    if id_excel and id_pdf and id_excel != id_pdf:
        avisos.append(f"Mismatch sample_id: Excel={id_excel} vs PDF={id_pdf}")

    # Aviso clínico “rico” (discordancias, datos incompletos, proximidad a cutoffs...)
    aviso_rico = construir_aviso_rico(combinado)
    if aviso_rico:
        avisos.append(aviso_rico)

    combinado["aviso"] = " | ".join(avisos) if avisos else None

    # Nota: evitamos print aquí para no ensuciar logs en Streamlit.
    return combinado