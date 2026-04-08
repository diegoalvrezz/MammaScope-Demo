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
  - IC 95% del Kappa (fórmula de Fleiss; equivalente a psych::cohen.kappa en R)
  - McNemar p-value (exacto si n<25; chi-cuadrado con corrección si n>=25;
    equivalente a mcnemar.test() en R)
  - Sensibilidad y Especificidad
    (equivalente a epiR::epi.tests() en R)
  - VPP y VPN (Valores Predictivos Positivo y Negativo)
    (equivalente a epiR::epi.tests() en R)
  - Odds Ratio diagnóstico (TP*TN / FP*FN)
    (equivalente a epiR::epi.tests() en R)
  - b y c (discordancias asimétricas):
        b = IHQ=1 y MMT=0  (IHQ+ -> MMT-)
        c = IHQ=0 y MMT=1  (IHQ- -> MMT+)
  - Tendencia: si c>b, MMT tiende a "+"; si b>c, MMT tiende a "-".
  - Advertencia si N < 30 (estadísticos de valor exploratorio).

Nota de equivalencia R/Python
------------------------------
Todos los cálculos implementados en este módulo son metodológicamente
equivalentes a los siguientes paquetes de R:
  - Kappa de Cohen e IC 95%: psych::cohen.kappa()
  - McNemar: mcnemar.test() con correct=TRUE (n>=25) o test exacto binomial (n<25)
  - Sensibilidad, Especificidad, VPP, VPN, OR diagnóstico: epiR::epi.tests()

La implementación en Python se justifica por razones de despliegue en entorno
hospitalario, donde la instalación de R no está garantizada.

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
- Cuando N < 30, se añade una advertencia en la columna 'Aviso_N'.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple
import math

import numpy as np
import pandas as pd


# Umbral bajo el cual los estadísticos se consideran de valor exploratorio
N_MINIMO = 30


# =============================================================================
# Helpers de normalización
# =============================================================================

def _norm_txt(x: Any) -> str:
    """
    Normaliza texto a string en minúsculas sin espacios laterales.

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


def ihq_bin_her2(x: Any) -> Optional[int]:
    """
    HER2 IHQ/SISH -> binario:
      - positivo / amplificado / 3+ => 1
      - 0/1+/2+ / low / negativo    => 0

    Asume que 'HER2_final' consolida IHQ+SISH con tokens interpretables.
    """
    s = _norm_txt(x)
    if not s:
        return None
    if "ampl" in s or "positivo" in s or "3+" in s or s == "3":
        return 1
    if "low" in s or "neg" in s or "negativo" in s:
        return 0
    for token in ["0", "0+", "1", "1+", "2", "2+"]:
        if token in s:
            return 0
    return None


def mmt_bin_status(x: Any) -> Optional[int]:
    """
    Status de MMT (genérico ER/PR/MKI67) -> binario:
      - si contiene "pos" => 1
      - si contiene "neg" => 0
      - si no interpretable => None
    """
    s = _norm_txt(x)
    if not s:
        return None
    if "pos" in s:
        return 1
    if "neg" in s:
        return 0
    return None


def mmt_bin_erbb2(x: Any) -> Optional[int]:
    """
    ERBB2_status (MMT) -> binario:
      - "positive" => 1
      - "low"/"zero"/"ultra"/"negative" => 0

    MMT puede reportar "low" o "zero/ultra-low" que clínicamente
    NO son HER2 positivo (amplificado).
    """
    s = _norm_txt(x)
    if not s:
        return None
    if "positive" in s or ("pos" in s and "neg" not in s):
        return 1
    if "low" in s or "zero" in s or "ultra" in s or "negative" in s or "neg" in s:
        return 0
    return None


def ihq_bin_ki67_pct(x: Any, cutoff: float = 20.0) -> Optional[int]:
    """
    Ki-67 IHQ (% numérico) -> binario según cutoff clínico:
      - >= cutoff => 1 (alto)
      - <  cutoff => 0 (bajo)

    Cutoff por defecto: 20% (criterio clínico estándar St. Gallen).
    """
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return None
        v = float(x)
        return 1 if v >= cutoff else 0
    except Exception:
        return None


# =============================================================================
# Conteos de confusión
# =============================================================================

@dataclass
class Counts:
    """
    Conteos para matriz de confusión y McNemar.

    Definiciones (IHQ como referencia, MMT como test):
      TP: IHQ=1, MMT=1  (ambos positivos)
      TN: IHQ=0, MMT=0  (ambos negativos)
      FP: IHQ=0, MMT=1  (MMT positivo, IHQ negativo)
      FN: IHQ=1, MMT=0  (MMT negativo, IHQ positivo)

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

    Solo se usan filas donde ambos valores están presentes (dropna por pares).
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

    return Counts(n=int(len(df)), tp=tp, tn=tn, fp=fp, fn=fn, b=fn, c=fp)


# =============================================================================
# Kappa de Cohen + IC 95% (fórmula de Fleiss)
# Equivalente a psych::cohen.kappa() en R
# =============================================================================

def kappa_from_counts(ct: Counts) -> float:
    """
    Kappa de Cohen desde conteos.

    Fórmula:
      po = (TP+TN) / N
      pe = P(IHQ=1)*P(MMT=1) + P(IHQ=0)*P(MMT=0)
      kappa = (po - pe) / (1 - pe)

    Devuelve NaN si N=0 o si el denominador es <= 0.
    """
    if ct.n == 0:
        return float("nan")

    po = (ct.tp + ct.tn) / ct.n
    pihq_pos = (ct.tp + ct.fn) / ct.n
    pmmt_pos = (ct.tp + ct.fp) / ct.n
    pe = pihq_pos * pmmt_pos + (1 - pihq_pos) * (1 - pmmt_pos)
    denom = 1 - pe

    if denom <= 0:
        return float("nan")

    return (po - pe) / denom


def kappa_ic95(ct: Counts) -> Tuple[float, float]:
    """
    Intervalo de confianza al 95% del Kappa de Cohen.

    Fórmula de Fleiss (1981), equivalente a psych::cohen.kappa() en R.

    Devuelve (ic_inf, ic_sup). Si no es calculable devuelve (nan, nan).
    """
    if ct.n == 0:
        return float("nan"), float("nan")

    kap = kappa_from_counts(ct)
    if math.isnan(kap):
        return float("nan"), float("nan")

    po = (ct.tp + ct.tn) / ct.n
    pihq_pos = (ct.tp + ct.fn) / ct.n
    pmmt_pos = (ct.tp + ct.fp) / ct.n
    pe = pihq_pos * pmmt_pos + (1 - pihq_pos) * (1 - pmmt_pos)
    denom = 1 - pe

    if denom <= 0:
        return float("nan"), float("nan")

    # Error estándar según Fleiss
    se = math.sqrt(po * (1 - po) / (ct.n * denom ** 2))
    z = 1.95996  # z al 95%

    return kap - z * se, kap + z * se


# =============================================================================
# McNemar
# Equivalente a mcnemar.test() en R
# =============================================================================

def mcnemar_p_exact(b: int, c: int) -> float:
    """
    McNemar exacto (binomial) para n=b+c < 25.
    Equivalente a mcnemar.test() en R con datos escasos.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    denom = 2 ** n
    s = sum(math.comb(n, i) for i in range(0, k + 1))
    return float(min(1.0, 2 * s / denom))


def mcnemar_p_chi2_cc(b: int, c: int) -> float:
    """
    McNemar chi-cuadrado con corrección de continuidad para n >= 25.
    Equivalente a mcnemar.test(correct=TRUE) en R.
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
    return mcnemar_p_exact(b, c) if (b + c) < 25 else mcnemar_p_chi2_cc(b, c)


# =============================================================================
# Sensibilidad, Especificidad, VPP, VPN, Odds Ratio diagnóstico
# Equivalente a epiR::epi.tests() en R
# =============================================================================

def sensibilidad(ct: Counts) -> float:
    """
    Sensibilidad = TP / (TP + FN).
    Proporción de positivos IHQ correctamente detectados por MMT.
    Devuelve NaN si no hay positivos IHQ.
    """
    denom = ct.tp + ct.fn
    if denom == 0:
        return float("nan")
    return ct.tp / denom


def especificidad(ct: Counts) -> float:
    """
    Especificidad = TN / (TN + FP).
    Proporción de negativos IHQ correctamente detectados por MMT.
    Devuelve NaN si no hay negativos IHQ.
    """
    denom = ct.tn + ct.fp
    if denom == 0:
        return float("nan")
    return ct.tn / denom


def vpp(ct: Counts) -> float:
    """
    Valor Predictivo Positivo = TP / (TP + FP).
    Probabilidad de que un positivo MMT sea realmente positivo por IHQ.
    Devuelve NaN si no hay positivos MMT.
    """
    denom = ct.tp + ct.fp
    if denom == 0:
        return float("nan")
    return ct.tp / denom


def vpn(ct: Counts) -> float:
    """
    Valor Predictivo Negativo = TN / (TN + FN).
    Probabilidad de que un negativo MMT sea realmente negativo por IHQ.
    Devuelve NaN si no hay negativos MMT.
    """
    denom = ct.tn + ct.fn
    if denom == 0:
        return float("nan")
    return ct.tn / denom


def odds_ratio_diagnostico(ct: Counts) -> float:
    """
    Odds Ratio diagnóstico = (TP * TN) / (FP * FN).
    Mide la capacidad global de discriminación del test MMT respecto a IHQ.
    Un OR > 1 indica que MMT discrimina mejor que el azar.
    Devuelve NaN si FP=0 o FN=0 (caso degenerado).
    Equivalente a epiR::epi.tests()$diag.or en R.
    """
    if ct.fp == 0 or ct.fn == 0:
        return float("nan")
    return (ct.tp * ct.tn) / (ct.fp * ct.fn)


# =============================================================================
# Tabla final (salida)
# =============================================================================

def build_stats_table_from_df(
    df: pd.DataFrame,
    ki67_cutoff_ihq: float = 20.0,
) -> pd.DataFrame:
    """
    Construye una tabla resumen por biomarcador con todas las métricas.

    Parámetros
    ----------
    df : pd.DataFrame
        DataFrame con columnas IHQ/MMT (ver docstring del módulo).
    ki67_cutoff_ihq : float
        Cutoff de Ki-67 IHQ para binarizar (por defecto 20%).

    Retorna
    -------
    pd.DataFrame con columnas:
      Biomarcador, N, TP, TN, FP, FN,
      %Concord,
      Kappa, Kappa_IC95_inf, Kappa_IC95_sup,
      McNemar_p,
      Sensibilidad, Especificidad, VPP, VPN,
      OR_diagnostico,
      b(IHQ+->MMT-), c(IHQ-->MMT+),
      Tendencia,
      Aviso_N
    """
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
        if y_ihq is None or y_mmt is None:
            continue

        ct = confusion_counts(y_ihq, y_mmt)

        # Fila vacía si no hay datos
        if ct.n == 0:
            rows.append({
                "Biomarcador": name,
                "N": 0,
                "TP": 0, "TN": 0, "FP": 0, "FN": 0,
                "%Concord": None,
                "Kappa": None,
                "Kappa_IC95_inf": None,
                "Kappa_IC95_sup": None,
                "McNemar_p": None,
                "Sensibilidad": None,
                "Especificidad": None,
                "VPP": None,
                "VPN": None,
                "OR_diagnostico": None,
                "b(IHQ+->MMT-)": 0,
                "c(IHQ-->MMT+)": 0,
                "Tendencia": "Sin datos",
                "Aviso_N": "Sin datos",
            })
            continue

        # --- Métricas ---
        concord = (ct.tp + ct.tn) / ct.n * 100.0
        kap = kappa_from_counts(ct)
        ic_inf, ic_sup = kappa_ic95(ct)
        p = mcnemar_p(ct.b, ct.c)
        sens = sensibilidad(ct)
        espec = especificidad(ct)
        vpp_val = vpp(ct)
        vpn_val = vpn(ct)
        or_val = odds_ratio_diagnostico(ct)

        # Tendencia
        if ct.c > ct.b:
            trend = "MMT tiende a +"
        elif ct.b > ct.c:
            trend = "MMT tiende a -"
        else:
            trend = "Sin asimetria"

        # Advertencia N reducido
        aviso_n = (
            f"N reducido (n={ct.n}): estadisticos de valor exploratorio. "
            "Interpretar con cautela."
            if ct.n < N_MINIMO else ""
        )

        def _r(v, dec=4):
            # Devuelve None (celda vacía en Excel) en lugar de np.nan o inf,
            # evitando que XlsxWriter los escriba como #NUM! con nan_inf_to_errors=True.
            try:
                if math.isnan(v) or math.isinf(v):
                    return None
                return round(v, dec)
            except (TypeError, ValueError):
                return None

        rows.append({
            "Biomarcador": name,
            "N": ct.n,
            "TP": ct.tp,
            "TN": ct.tn,
            "FP": ct.fp,
            "FN": ct.fn,
            "%Concord": _r(concord, 2),
            "Kappa": _r(kap, 4),
            "Kappa_IC95_inf": _r(ic_inf, 4),
            "Kappa_IC95_sup": _r(ic_sup, 4),
            "McNemar_p": _r(p, 6),
            "Sensibilidad": _r(sens, 4),
            "Especificidad": _r(espec, 4),
            "VPP": _r(vpp_val, 4),
            "VPN": _r(vpn_val, 4),
            "OR_diagnostico": _r(or_val, 4),
            "b(IHQ+->MMT-)": ct.b,
            "c(IHQ-->MMT+)": ct.c,
            "Tendencia": trend,
            "Aviso_N": aviso_n,
        })

    df_out = pd.DataFrame(rows)
    # Pandas convierte None a NaN en columnas float64, lo que XlsxWriter escribe
    # como #NUM! cuando nan_inf_to_errors=True esta activo. Forzamos dtype object
    # para preservar None como celda vacia en Excel.
    return df_out.astype(object).where(pd.notnull(df_out), None)