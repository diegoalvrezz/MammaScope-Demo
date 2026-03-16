# stats_biomarcadores.py
"""
Cálculo de métricas de concordancia IHQ vs MammaTyper® por biomarcador.

Qué hace este módulo
--------------------
A partir de un DataFrame (lote o base histórica) que contiene columnas IHQ y MMT,
convierte cada biomarcador a binario (0/1) y calcula:

  - Matriz de confusión: TP, TN, FP, FN
  - % Concordancia (acuerdo observado)
  - Kappa de Cohen (acuerdo ajustado por azar)
  - McNemar p-value (exacto si n<25; chi-cuadrado con corrección si n>=25)
  - b y c (discordancias asimétricas):
        b = IHQ=1 y MMT=0  (IHQ+ → MMT-)
        c = IHQ=0 y MMT=1  (IHQ- → MMT+)
  - Tendencia: si c>b, MMT tiende a “+”; si b>c, MMT tiende a “-”.

Columnas esperadas en df
------------------------
ER:
  - ESR1_IHQ      (texto tipo Positivo/Negativo)
  - ESR1_status   (texto tipo Positive/Negative o Pos/Neg)

PR:
  - PGR_IHQ
  - PGR_status

HER2:
  - HER2_final    (texto combinando IHQ/SISH, p.ej. "HER2 positivo (SISH)")
  - ERBB2_status  (MMT: puede traer "positive", "low", "zero/ultra-low", etc.)

Ki-67:
  - KI67_IHQ      (numérico en %)
  - MKI67_status  (texto pos/neg)

Notas importantes
-----------------
- Este módulo NO inventa datos: si no se puede binarizar (NA/NC), devuelve None.
- Se dropean filas donde falte IHQ o MMT para ese biomarcador (dropna por pareja).
- Ki-67 IHQ se binariza por cutoff clínico configurable (por defecto 20%).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
import math

import numpy as np
import pandas as pd


# =============================================================================
# Helpers de normalización
# =============================================================================

def _norm_txt(x: Any) -> str:
    """
    Normaliza texto a:
      - string
      - strip
      - lower
      - colapsa espacios múltiples

    Ej:
      "  Positivo   " -> "positivo"
      None -> ""
    """
    if x is None:
        return ""
    s = str(x).strip().lower()
    return " ".join(s.split())


# =============================================================================
# Conversión a binario (0/1) por biomarcador
# =============================================================================

# -------------------------
# HR (ER / PR) IHQ
# -------------------------
def ihq_bin_hr(x: Any) -> Optional[int]:
    """
    IHQ para ER/PR -> binario:
      - contiene "pos"/"positivo" => 1
      - contiene "neg"/"negativo" => 0
      - si no se puede interpretar => None
    """
    s = _norm_txt(x)
    if not s:
        return None
    if "pos" in s or "positivo" in s:
        return 1
    if "neg" in s or "negativo" in s:
        return 0
    return None


# -------------------------
# HER2 IHQ/SISH (usando HER2_final)
# -------------------------
def ihq_bin_her2(x: Any) -> Optional[int]:
    """
    HER2 IHQ/SISH -> binario:
      - positivo / amplificado / 3+ => 1
      - 0/1+/2+ / low / negativo    => 0

    Nota:
      - Aquí estamos asumiendo que 'HER2_final' ya consolida IHQ+SISH
        y contiene tokens interpretables ("positivo", "negativo", "amplificación", "low", "3+").
    """
    s = _norm_txt(x)
    if not s:
        return None

    # POSITIVO / AMPLIFICACIÓN / 3+
    if "ampl" in s or "positivo" in s or "3+" in s or s == "3":
        return 1

    # NEGATIVO / LOW
    if "low" in s or "neg" in s or "negativo" in s:
        return 0

    # Scores típicos que se consideran NO positivo si aparecen en el texto
    for token in ["0", "0+", "1", "1+", "2", "2+"]:
        if token in s:
            return 0

    return None


# -------------------------
# MMT Status (ER, PR, MKI67)
# -------------------------
def mmt_bin_status(x: Any) -> Optional[int]:
    """
    Status de MMT (genérico) -> binario:
      - si contiene "pos" => 1
      - si contiene "neg" => 0
      - si no interpretable => None

    Nota:
      - Para ER/PR/MKI67 suele venir "Positive"/"Negative" (o similar).
    """
    s = _norm_txt(x)
    if not s:
        return None
    if "pos" in s:
        return 1
    if "neg" in s:
        return 0
    return None


# -------------------------
# MMT HER2 (ERBB2_status tiene categorías low/zero/ultra-low)
# -------------------------
def mmt_bin_erbb2(x: Any) -> Optional[int]:
    """
    ERBB2_status (MMT) -> binario:
      - "positive" (o "pos" sin "neg") => 1
      - "low"/"zero"/"ultra"/"negative"/"neg" => 0
      - si no interpretable => None

    Motivo:
      - MMT para HER2 puede reportar "low" o "zero/ultra-low" que
        clínicamente NO son "HER2 positivo" (amplificado).
    """
    s = _norm_txt(x)
    if not s:
        return None

    # POS
    if "positive" in s or ("pos" in s and "neg" not in s):
        return 1

    # NO POS (incluye low / zero / ultra-low / negative)
    if "low" in s or "zero" in s or "ultra" in s or "negative" in s or "neg" in s:
        return 0

    return None


# -------------------------
# Ki-67 IHQ (criterio clínico)
# -------------------------
def ihq_bin_ki67_pct(x: Any, cutoff: float = 20.0) -> Optional[int]:
    """
    Ki-67 IHQ (% numérico) -> binario según cutoff clínico:
      - >= cutoff => 1 (alto)
      - < cutoff  => 0 (bajo)

    Si no es numérico / vacío => None
    """
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        v = float(x)
        return 1 if v >= cutoff else 0
    except Exception:
        return None


# =============================================================================
# Métricas: matriz de confusión + kappa + McNemar
# =============================================================================

@dataclass
class Counts:
    """
    Conteos para matriz de confusión y McNemar.

    Definiciones:
      TP: IHQ=1, MMT=1
      TN: IHQ=0, MMT=0
      FP: IHQ=0, MMT=1
      FN: IHQ=1, MMT=0

    Para McNemar (discordancias):
      b = FN = IHQ=1, MMT=0
      c = FP = IHQ=0, MMT=1
    """
    n: int
    tp: int
    tn: int
    fp: int
    fn: int
    b: int
    c: int


def confusion_counts(y_ihq: pd.Series, y_mmt: pd.Series) -> Counts:
    """
    Calcula los conteos de confusión a partir de series binarias (0/1) con NA.

    Importante:
      - Se hace dropna por pares (solo filas con ambos valores presentes).
      - Si no quedan filas, devuelve todo a cero con n=0.
    """
    df = pd.DataFrame({"ihq": y_ihq, "mmt": y_mmt}).dropna()
    if df.empty:
        return Counts(0, 0, 0, 0, 0, 0, 0)

    ihq = df["ihq"].astype(int).values
    mmt = df["mmt"].astype(int).values

    tp = int(np.sum((ihq == 1) & (mmt == 1)))
    tn = int(np.sum((ihq == 0) & (mmt == 0)))
    fp = int(np.sum((ihq == 0) & (mmt == 1)))
    fn = int(np.sum((ihq == 1) & (mmt == 0)))

    n = int(len(df))
    b = fn
    c = fp

    return Counts(n, tp, tn, fp, fn, b, c)


def kappa_from_counts(ct: Counts) -> float:
    """
    Kappa de Cohen desde conteos.

    Fórmula:
      po = (TP+TN)/N
      pe = P(IHQ=1)*P(MMT=1) + P(IHQ=0)*P(MMT=0)
      kappa = (po - pe) / (1 - pe)

    Devuelve NaN si:
      - N=0
      - denom = 1-pe <= 0 (casos degenerados)
    """
    if ct.n == 0:
        return float("nan")

    po = (ct.tp + ct.tn) / ct.n

    pihq_pos = (ct.tp + ct.fn) / ct.n
    pmmt_pos = (ct.tp + ct.fp) / ct.n
    pihq_neg = 1 - pihq_pos
    pmmt_neg = 1 - pmmt_pos

    pe = pihq_pos * pmmt_pos + pihq_neg * pmmt_neg
    denom = 1 - pe

    if denom <= 0:
        return float("nan")

    return (po - pe) / denom


def mcnemar_p_exact(b: int, c: int) -> float:
    """
    McNemar exacto (binomial) para discordancias pequeñas.

    n = b+c
    p = 2 * sum_{i=0..min(b,c)} C(n,i) / 2^n

    Se trunca a 1.0 máximo.
    """
    n = b + c
    if n == 0:
        return 1.0

    k = min(b, c)
    denom = 2 ** n
    s = 0
    for i in range(0, k + 1):
        s += math.comb(n, i)

    p = 2 * (s / denom)
    return float(min(1.0, p))


def mcnemar_p_chi2_cc(b: int, c: int) -> float:
    """
    Aproximación chi-cuadrado con corrección de continuidad.

    chi2 = (|b-c|-1)^2 / (b+c)
    p = erfc(sqrt(chi2/2))  (equivalente a cola superior de chi2 1 g.l.)

    Nota:
      - Se usa math.erfc para evitar dependencias extra.
    """
    n = b + c
    if n == 0:
        return 1.0

    chi2 = (abs(b - c) - 1) ** 2 / n
    return float(math.erfc(math.sqrt(chi2 / 2)))


def mcnemar_p(b: int, c: int) -> float:
    """
    Selector automático:
      - exacto si n=b+c < 25
      - chi2 con corrección de continuidad si n >= 25
    """
    n = b + c
    if n < 25:
        return mcnemar_p_exact(b, c)
    return mcnemar_p_chi2_cc(b, c)


# =============================================================================
# Tabla final (salida)
# =============================================================================

def build_stats_table_from_df(
    df: pd.DataFrame,
    ki67_cutoff_ihq: float = 20.0,
) -> pd.DataFrame:
    """
    Construye una tabla resumen por biomarcador.

    Parámetros
    ----------
    df : pd.DataFrame
        DataFrame de entrada con columnas IHQ/MMT (ver docstring arriba).
    ki67_cutoff_ihq : float
        Cutoff de Ki-67 IHQ para binarizar (por defecto 20%).

    Retorna
    -------
    pd.DataFrame
        Columnas:
          - Biomarcador
          - N, TP, TN, FP, FN
          - %Concord
          - Kappa
          - McNemar_p
          - b(IHQ+→MMT-), c(IHQ-→MMT+)
          - Tendencia
    """
    # Especificaciones por biomarcador: (nombre, serie IHQ binaria, serie MMT binaria)
    specs = [
        (
            "ER (ESR1)",
            df.get("ESR1_IHQ").map(ihq_bin_hr),
            df.get("ESR1_status").map(mmt_bin_status),
        ),
        (
            "PR (PGR)",
            df.get("PGR_IHQ").map(ihq_bin_hr),
            df.get("PGR_status").map(mmt_bin_status),
        ),
        (
            "HER2 (ERBB2)",
            df.get("HER2_final").map(ihq_bin_her2),
            df.get("ERBB2_status").map(mmt_bin_erbb2),
        ),
        (
            "Ki-67 (MKI67)",
            df.get("KI67_IHQ").map(lambda x: ihq_bin_ki67_pct(x, cutoff=ki67_cutoff_ihq)),
            df.get("MKI67_status").map(mmt_bin_status),
        ),
    ]

    rows = []

    for name, y_ihq, y_mmt in specs:
        # Si falta alguna columna, df.get devolverá None -> evitamos error
        if y_ihq is None or y_mmt is None:
            continue

        ct = confusion_counts(y_ihq, y_mmt)

        # Sin datos válidos para ese biomarcador
        if ct.n == 0:
            rows.append({
                "Biomarcador": name,
                "N": 0,
                "TP": 0, "TN": 0, "FP": 0, "FN": 0,
                "%Concord": np.nan,
                "Kappa": np.nan,
                "McNemar_p": np.nan,
                "b(IHQ+→MMT-)": 0,
                "c(IHQ-→MMT+)": 0,
                "Tendencia": "Sin datos",
            })
            continue

        # Métricas principales
        concord = (ct.tp + ct.tn) / ct.n * 100.0
        kap = kappa_from_counts(ct)
        p = mcnemar_p(ct.b, ct.c)

        # Tendencia (asimetría de discordancias)
        if ct.c > ct.b:
            trend = "MMT tiende a +"
        elif ct.b > ct.c:
            trend = "MMT tiende a -"
        else:
            trend = "Sin asimetría"

        rows.append({
            "Biomarcador": name,
            "N": ct.n,
            "TP": ct.tp,
            "TN": ct.tn,
            "FP": ct.fp,
            "FN": ct.fn,
            "%Concord": round(concord, 2),
            "Kappa": round(kap, 4) if not math.isnan(kap) else np.nan,
            "McNemar_p": round(p, 6),
            "b(IHQ+→MMT-)": ct.b,
            "c(IHQ-→MMT+)": ct.c,
            "Tendencia": trend,
        })

    return pd.DataFrame(rows)