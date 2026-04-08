from typing import Mapping, Any, Optional, List, Dict
import re

from ajustes import load_settings


def _na(x) -> bool:
    """
    Devuelve True si un valor se considera “no disponible”.

    Criterios:
    - None
    - cadena vacía o solo espacios

    Se usa para homogeneizar comprobaciones en todo el módulo y evitar
    condicionales repetidos del estilo: x is None or x == "".
    """
    return x is None or (isinstance(x, str) and x.strip() == "")


def _low(s: Any) -> str:
    """
    Convierte un valor a texto en minúsculas y sin espacios laterales.

    Si el valor es “no disponible” (_na), devuelve cadena vacía.
    Es útil para comparaciones robustas (por ejemplo, “Positivo”, “positivo”, “ POSITIVO ”).
    """
    return "" if _na(s) else str(s).strip().lower()


def _to_float(x) -> Optional[float]:
    """
    Intenta convertir un valor a float.

    - Acepta comas como separador decimal.
    - Si el valor no existe o no se puede convertir, devuelve None.

    Se usa para manejar entradas heterogéneas provenientes de Excel/PDF.
    """
    try:
        if _na(x):
            return None
        return float(str(x).replace(",", "."))
    except Exception:
        return None


def _to_int(x) -> Optional[int]:
    """
    Intenta convertir un valor numérico a int, redondeando si viene como float.

    - Acepta comas como separador decimal.
    - Si el valor no existe o no se puede convertir, devuelve None.
    """
    try:
        if _na(x):
            return None
        return int(round(float(str(x).replace(",", "."))))
    except Exception:
        return None


def _is_pos(status: Any) -> Optional[bool]:
    """
    Interpreta un estado “positivo/negativo” en texto y lo convierte a booleano.

    Devuelve:
    - True  si detecta positivo
    - False si detecta negativo
    - None  si no puede interpretarlo

    Nota:
    Se basa en búsqueda de fragmentos (“pos”, “neg”) para tolerar variaciones
    típicas del origen de datos.
    """
    s = _low(status)
    if not s:
        return None
    if "pos" in s or "positivo" in s:
        return True
    if "neg" in s or "negativo" in s:
        return False
    return None


def _fmt(x: Any, fallback="NC") -> str:
    """
    Formatea un valor para mostrarlo en mensajes.

    - Si el valor está vacío o no existe, devuelve 'NC' (no consta) por defecto.
    - Si existe, devuelve el texto tal cual.
    """
    return fallback if _na(x) else str(x)


def extraer_sample_ids_con_aviso(registros: List[Dict[str, Any]]) -> List[str]:
    """
    Devuelve una lista de sample_id de aquellas muestras que llevan un aviso asociado.

    Uso típico:
    - Tras procesar un lote, mostrar un aviso general en pantalla con los sample_id
      que requieren revisión.

    Criterio:
    - Se considera que una muestra “tiene aviso” si el campo 'aviso' no está vacío.
    """
    ids = []
    for r in registros:
        aviso = r.get("aviso")
        sample_id = r.get("sample_id")
        if aviso and sample_id:
            ids.append(str(sample_id))
    return ids


# =========================================================
# Helpers: thresholds desde settings + cálculo de “cercanía a cutoff”
# =========================================================

def _get_gene_thresholds(gene: str) -> list[float]:
    """
    Lee los umbrales (thresholds) configurados en settings.json para un gen.

    - Carga settings con load_settings() para respetar la configuración actual.
    - Devuelve una lista de floats (si algún valor no se puede convertir, se ignora).

    Nota:
    Esto permite que el criterio de “cercanía al cutoff” sea configurable desde la UI.
    """
    s = load_settings()
    cfg = (s.get("clinico", {}).get("mmt_ranges", {}) or {})
    g = (cfg.get(gene, {}) or {})
    th = g.get("thresholds", []) or []
    out = []
    for x in th:
        try:
            out.append(float(x))
        except Exception:
            pass
    return out


def _closest_threshold(value: Optional[float], thresholds: list[float]) -> tuple[Optional[float], Optional[float]]:
    """
    Calcula el umbral más cercano a un valor y devuelve:

    - delta absoluto: |value - threshold_mas_cercano|
    - threshold_mas_cercano

    Si no hay valor o no hay thresholds, devuelve (None, None).
    """
    if value is None or not thresholds:
        return None, None
    closest = min(thresholds, key=lambda t: abs(value - t))
    return abs(value - closest), closest


def _extract_ihq_score(score_raw: Any) -> Optional[str]:
    """
    Normaliza el score IHQ de HER2 a una etiqueta estándar.

    Devuelve:
    - '0', '1+', '2+', '3+' si se reconoce
    - None si no hay un patrón claro

    Motivo:
    En Patwin / informes puede aparecer como '3+', '+++', 'score 0', '(+)', etc.
    """
    s = _low(score_raw)
    if not s:
        return None

    # Prioridad: 3+, 2+, 1+, 0 (y variantes típicas)
    if "3+" in s or "+++" in s:
        return "3+"
    if "2+" in s or "++" in s:
        return "2+"
    if "1+" in s or re.search(r"\b1\+\b", s) or "(+)" in s:
        return "1+"
    if "0" == s or "score 0" in s or re.search(r"\b0\b", s):
        return "0"

    # Caso raro: si ya viene como uno de los formatos esperables
    if s in {"0+", "1+", "2+", "3+"}:
        return s.upper()

    return None


def _her2_bucket_from_ihq(m: Mapping[str, Any]) -> Optional[str]:
    """
    Clasifica HER2 según la información de IHQ/SISH/texto para poder comparar con MMT.

    La función intenta seguir un orden de fiabilidad:
    1) SISH (si está informado)
    2) Score IHQ (si está informado)
    3) Texto libre (HER2_final / ERBB2_IHQ_SISH)

    Devuelve una etiqueta interna (bucket) para usar en reglas de discordancia.
    """
    # 1) SISH (si existe, manda)
    sish = _low(m.get("HER2_SISH_result"))
    if sish:
        if "con ampl" in sish or "amplificación" in sish:
            return "pos_sish"
        if "sin ampl" in sish or "no se observa ampl" in sish:
            return "neg_sish"
        return "indet_sish"

    # 2) Score IHQ
    score = _extract_ihq_score(m.get("HER2_IHQ_score"))
    if score:
        if score == "3+":
            return "pos_ihq"
        if score in {"0", "0+", "1+"}:
            return "neg_ihq"
        if score == "2+":
            return "equivoco_ihq"

    # 3) Texto libre
    base = " ".join([
        _low(m.get("HER2_final")),
        _low(m.get("ERBB2_IHQ_SISH")),
    ])
    if "low" in base:
        return "low_sin_score"
    if "equivoc" in base:
        return "equivoco_txt"
    if "pos" in base or "positivo" in base:
        return "pos_txt"
    if "neg" in base or "negativo" in base:
        return "neg_txt"
    return None


def _mmt_bucket_her2(m: Mapping[str, Any]) -> Optional[str]:
    """
    Clasifica HER2 según MammaTyper (ERBB2_status).

    Devuelve:
    - 'pos_mmt' / 'neg_mmt' si se interpreta
    - None si no consta o es ambiguo
    """
    s = _low(m.get("ERBB2_status"))
    if not s:
        return None
    if "pos" in s:
        return "pos_mmt"
    if "neg" in s:
        return "neg_mmt"
    return None


def _subtipo_bucket(s: Any) -> Optional[str]:
    """
    Reduce el texto de subtipo a una categoría “estable” para comparar IHQ vs MMT.

    Devuelve:
    - 'tn' para triple negativo
    - 'lum_a', 'lum_b', 'lum' para luminal
    - 'her2_enriched' para HER2-enriched
    - 'otro' si existe texto pero no encaja
    - None si no hay subtipo
    """
    t = _low(s)
    if not t:
        return None

    if "triple" in t or "tnbc" in t:
        return "tn"

    if "luminal" in t:
        # Nota: este criterio es simple; depende de cómo venga el texto.
        if "a" in t:
            return "lum_a"
        if "b" in t:
            return "lum_b"
        return "lum"

    if "her2" in t and ("enriched" in t or "positivo" in t or "pos" in t):
        return "her2_enriched"

    return "otro"




def construir_aviso_rico(m: Mapping[str, Any]) -> Optional[str]:
    """
    Construye un texto de aviso clínico “rico” para una muestra.

    Entrada:
    - m: diccionario/Mapping con campos combinados (Excel + PDF), por ejemplo:
      ESR1_IHQ, ESR1_status, HER2_IHQ_score, ERBB2_status, subtipo_ihq, subtipo_mmt, etc.

    Salida:
    - None si no hay motivos para avisar
    - Un string con viñetas ("• ...") si hay uno o varios hallazgos a revisar

    Filosofía:
    - Los avisos intentan priorizar discordancias relevantes y casos “límite”
      (cercanos a umbrales) que pueden cambiar interpretación clínica.
    - El comportamiento es configurable desde settings (activar/desactivar tipos de avisos
      y umbrales de cercanía).
    """
    cfg_cli  = load_settings().get("clinico", {})
    cfg      = cfg_cli.get("avisos", {})

    # Umbrales clínicos configurables (con fallback a valores por defecto)
    ki67_cutoff = float(cfg_cli.get("ki67_cutoff_ihq", 20.0))
    pr_bajo_pct = float(cfg_cli.get("pr_bajo_pct",     10.0))
    er_bajo_pct = float(cfg_cli.get("er_bajo_pct",     10.0))

    # Si los avisos están desactivados por configuración, no se genera nada.
    if not bool(cfg.get("activar", True)):
        return None

    bullets: List[str] = []
    incompleto = False  # marca si hay faltas de datos relevantes
    # Flags de configuración para activar/desactivar reglas específicas.
    f_er = bool(cfg.get("avisar_discordancia_er", True))
    f_pr = bool(cfg.get("avisar_discordancia_pr", True))
    f_her2 = bool(cfg.get("avisar_discordancia_her2", True))
    f_subtipo = bool(cfg.get("avisar_discordancia_subtipo", True))
    f_her2_low = bool(cfg.get("avisar_her2_low_sin_score", True))

    # Flags “nuevos” (si no existen en settings, por defecto se activan)
    f_er_low = bool(cfg.get("avisar_er_low_ihq", True))
    f_her2_equiv_sin_sish = bool(cfg.get("avisar_her2_2plus_sin_sish", True))
    f_her2_3plus_sin_sish = bool(cfg.get("avisar_her2_3plus_sin_sish", True))
    f_faltan = bool(cfg.get("avisar_faltan_datos_clave", True))

    # Cutoffs: compatibilidad con nombres antiguos (si existiesen)
    f_prox = bool(cfg.get("avisar_proximidad_cutoff", cfg.get("avisar_cerca_cutoff_mmt", True)))

    # Umbrales para “cercanía a cutoff” (Ct)
    umbral_crit = _to_float(cfg.get("cutoff_prox_critico_ct", 0.20))
    umbral_cerca = _to_float(cfg.get("cutoff_prox_cercano_ct", cfg.get("umbral_cerca_cutoff_mmt", 0.50)))
    umbral_supercrit = _to_float(cfg.get("cutoff_prox_supercritico_ct", 0.05))

    # Fallbacks por si algo viene mal en settings
    umbral_crit = umbral_crit if umbral_crit is not None else 0.20
    umbral_cerca = umbral_cerca if umbral_cerca is not None else 0.50
    umbral_supercrit = umbral_supercrit if umbral_supercrit is not None else 0.05

    # Si están invertidos, se corrigen para mantener la lógica.
    if umbral_crit > umbral_cerca:
        umbral_crit, umbral_cerca = umbral_cerca, umbral_crit

    # Epsilon para comparaciones con float (evitar efectos de redondeo).
    eps = 1e-9

    # -------------------------
    # 1) ER/PR: discordancia IHQ vs MMT
    # -------------------------
    er_ihq = _is_pos(m.get("ESR1_IHQ"))
    pr_ihq = _is_pos(m.get("PGR_IHQ"))
    er_mmt = _is_pos(m.get("ESR1_status"))
    pr_mmt = _is_pos(m.get("PGR_status"))

    # Porcentajes (si constan) para contextualizar casos “low”
    er_pct = _to_float(m.get("ESR1_IHQ_pct"))
    pr_pct = _to_float(m.get("PGR_IHQ_pct"))

    # Discordancia ER
    if f_er and (er_ihq is not None) and (er_mmt is not None) and (er_ihq != er_mmt):
        bullets.append(
            f"Discordancia ER: IHQ={_fmt(m.get('ESR1_IHQ'))}"
            + (f" ({int(round(er_pct))}%)" if er_pct is not None else "")
            + f" vs MMT(ESR1)={_fmt(m.get('ESR1_status'))} (valor={_fmt(m.get('ESR1_value'))}). "
            "Requiere revisión."
        )

    # Discordancia PR
    if f_pr and (pr_ihq is not None) and (pr_mmt is not None) and (pr_ihq != pr_mmt):
        bullets.append(
            f"Discordancia PR: IHQ={_fmt(m.get('PGR_IHQ'))}"
            + (f" ({int(round(pr_pct))}%)" if pr_pct is not None else "")
            + f" vs MMT(PGR)={_fmt(m.get('PGR_status'))} (valor={_fmt(m.get('PGR_value'))}). "
            "Requiere revisión."
        )

    # PR bajo (IHQ) con interpretación positiva: alerta de “low”
    # Umbral configurable desde ajustes → Clínico → "Umbral PR bajo".
    if f_pr and pr_pct is not None and pr_pct < pr_bajo_pct and pr_ihq is True:
        bullets.append(
            f"PR bajo por IHQ: {int(round(pr_pct))}% "
            f"(umbral servicio: {int(pr_bajo_pct)}%; interpretación dependiente del contexto)."
        )

    # ER bajo (IHQ) con interpretación positiva: alerta de “low”
    # Umbral configurable desde ajustes → Clínico → "Umbral ER bajo".
    if f_er_low and er_pct is not None and er_pct < er_bajo_pct and er_ihq is True:
        bullets.append(
            f"ER bajo por IHQ: {int(round(er_pct))}% "
            f"(umbral servicio: {int(er_bajo_pct)}%; zona 'low positive'; interpretar con cautela)."
        )

    # -------------------------
    # 2) Ki-67: discordancia simple IHQ vs MMT en extremos
    # -------------------------
    ki67_ihq = _to_int(m.get("KI67_IHQ"))
    ki67_mmt = _is_pos(m.get("MKI67_status"))

    alerta_ki67 = False
    if (ki67_ihq is not None) and (ki67_mmt is not None):
        # Umbral Ki-67 configurable desde ajustes → Clínico → "Cutoff Ki-67 IHQ".
        # Bajo: mitad del cutoff. Alto: cutoff + 10 pts (margen conservador).
        ki67_bajo   = ki67_cutoff / 2.0
        ki67_alto   = ki67_cutoff + 10.0
        if ki67_ihq <= ki67_bajo and ki67_mmt is True:
            alerta_ki67 = True
            bullets.append(
                f"Posible discordancia proliferación: Ki-67 IHQ={ki67_ihq}% (bajo, cutoff={int(ki67_cutoff)}%) vs "
                f"MMT(MKI67)={_fmt(m.get('MKI67_status'))} (valor={_fmt(m.get('MKI67_value'))}). Requiere revisión."
            )
        if ki67_ihq >= ki67_alto and ki67_mmt is False:
            alerta_ki67 = True
            bullets.append(
                f"Posible discordancia proliferación: Ki-67 IHQ={ki67_ihq}% (alto, cutoff={int(ki67_cutoff)}%) vs "
                f"MMT(MKI67)={_fmt(m.get('MKI67_status'))} (valor={_fmt(m.get('MKI67_value'))}). Requiere revisión."
            )

    # -------------------------
    # 3) HER2: datos incompletos + discordancia con MMT
    # -------------------------
    her2_ihq_bucket = _her2_bucket_from_ihq(m)
    her2_mmt_bucket = _mmt_bucket_her2(m)

    # HER2-low basado solo en texto (sin score)
    if f_her2_low and her2_ihq_bucket == "low_sin_score":
        bullets.append("HER2-low sin score IHQ documentado: categoría basada en comentario/texto. Interpretar con cautela.")

    # IHQ 2+ sin SISH (dato incompleto según protocolo)
    if f_her2_equiv_sin_sish:
        score = _extract_ihq_score(m.get("HER2_IHQ_score"))
        sish = _low(m.get("HER2_SISH_result"))
        if score == "2+" and not sish:
            bullets.append("HER2 IHQ 2+ (equívoco) sin SISH informado: requiere confirmación por ISH según protocolo.")

    # IHQ 3+ sin SISH (no siempre es “necesario”, pero es un dato que puede faltar en el volcado)
    if f_her2_3plus_sin_sish:
        score = _extract_ihq_score(m.get("HER2_IHQ_score"))
        sish = _low(m.get("HER2_SISH_result"))
        if score == "3+" and not sish:
            bullets.append("HER2 IHQ 3+ sin SISH registrado (dato incompleto): confirmar si falta el resultado de ISH en el informe.")

    # Discordancias HER2 (positivos por IHQ/SISH vs negativos por MMT, y viceversa)
    if f_her2 and her2_ihq_bucket in {"pos_sish", "pos_ihq"} and her2_mmt_bucket == "neg_mmt":
        bullets.append(
            f"Discordancia HER2: IHQ/SISH sugiere POSITIVO "
            f"({_fmt(m.get('HER2_final'))}; score={_fmt(m.get('HER2_IHQ_score'))}; SISH={_fmt(m.get('HER2_SISH_result'))}) "
            f"vs MMT(ERBB2)={_fmt(m.get('ERBB2_status'))} (valor={_fmt(m.get('ERBB2_value'))}). Requiere revisión."
        )

    if f_her2 and her2_ihq_bucket in {"neg_sish", "neg_ihq"} and her2_mmt_bucket == "pos_mmt":
        bullets.append(
            f"Discordancia HER2: IHQ/SISH sugiere NEGATIVO "
            f"({_fmt(m.get('HER2_final'))}; score={_fmt(m.get('HER2_IHQ_score'))}; SISH={_fmt(m.get('HER2_SISH_result'))}) "
            f"vs MMT(ERBB2)={_fmt(m.get('ERBB2_status'))} (valor={_fmt(m.get('ERBB2_value'))}). Requiere revisión."
        )

    # -------------------------
    # 4) Subtipo: comparación “normalizada” IHQ vs MMT
    # -------------------------
    if f_subtipo:
        b_ihq = _subtipo_bucket(m.get("subtipo_ihq"))
        b_mmt = _subtipo_bucket(m.get("subtipo_mmt"))
        if b_ihq and b_mmt and b_ihq != b_mmt:
            bullets.append(
                f"Subtipo discordante: IHQ='{_fmt(m.get('subtipo_ihq'))}' vs MMT='{_fmt(m.get('subtipo_mmt'))}'"
                + (f" ({_fmt(m.get('subtipo_mmt_detalle'), '')})" if not _na(m.get("subtipo_mmt_detalle")) else "")
                + ". Requiere revisión."
            )

    # =========================================================
    # Contexto: decide cuándo tiene sentido avisar por “cercanía a cutoff”
    # =========================================================
    def _tiene_discordancia_er() -> bool:
        return (er_ihq is not None) and (er_mmt is not None) and (er_ihq != er_mmt)

    def _tiene_discordancia_pr() -> bool:
        return (pr_ihq is not None) and (pr_mmt is not None) and (pr_ihq != pr_mmt)

    def _tiene_contexto_her2_importante() -> bool:
        """
        Define cuándo HER2 es “relevante” para activar avisos de cutoffs en ERBB2.

        Incluye:
        - HER2 incompleto (2+ o 3+ sin SISH)
        - Discordancia HER2 IHQ/SISH vs MMT
        - HER2-low sin score (basado en texto)
        """
        score = _extract_ihq_score(m.get("HER2_IHQ_score"))
        sish = _low(m.get("HER2_SISH_result"))
        her2_incompleto = ((score == "2+" or score == "3+") and not sish)
        her2_disc = (
            (f_her2 and her2_ihq_bucket in {"pos_sish", "pos_ihq"} and her2_mmt_bucket == "neg_mmt")
            or (f_her2 and her2_ihq_bucket in {"neg_sish", "neg_ihq"} and her2_mmt_bucket == "pos_mmt")
        )
        her2_low = (f_her2_low and her2_ihq_bucket == "low_sin_score")
        return her2_incompleto or her2_disc or her2_low

    def _genes_prioritarios_cutoff() -> List[str]:
        """
        Decide qué genes mirar para “cercanía a cutoff” en función del contexto clínico.

        Idea:
        - Si el problema está en HER2, interesa ERBB2.
        - Si hay discordancia ER o ER low, interesa ESR1.
        - Si hay discordancia PR o PR low, interesa PGR.
        - Si hay discordancia Ki-67, interesa MKI67.
        """
        prios: List[str] = []
        if _tiene_contexto_her2_importante():
            prios.append("ERBB2")
        if _tiene_discordancia_er() or (f_er_low and er_pct is not None and er_pct < er_bajo_pct and er_ihq is True):
            prios.append("ESR1")
        if _tiene_discordancia_pr() or (pr_pct is not None and pr_pct < pr_bajo_pct and pr_ihq is True):
            prios.append("PGR")
        if alerta_ki67:
            prios.append("MKI67")
        return prios

    # “Hay contexto” = hay algo clínicamente llamativo; entonces se permite avisar por “cercanía”.
    hay_contexto = (
        _tiene_discordancia_er()
        or _tiene_discordancia_pr()
        or alerta_ki67
        or _tiene_contexto_her2_importante()
        or (f_er_low and er_pct is not None and er_pct < er_bajo_pct and er_ihq is True)
        or (pr_pct is not None and pr_pct < pr_bajo_pct and pr_ihq is True)
    )

    # -------------------------
    # 5) Cutoffs: avisos de “cercano” y “crítico” filtrando por contexto
    # -------------------------
    if f_prox:
        genes_crit: List[str] = []
        genes_cerca: List[str] = []

        genes = _genes_prioritarios_cutoff()

        # Sin contexto, se evita avisar de “cerca” para no saturar (solo se considera crítico).
        allow_cerca = bool(hay_contexto)

        # Lista general para fallback si no hay genes prioritarios claros.
        genes_fallback = ["ERBB2", "ESR1", "PGR", "MKI67"]

        def _eval_gene(gen: str) -> Optional[tuple[float, Optional[float]]]:
            """
            Evalúa un gen y devuelve:
            - delta respecto al cutoff más cercano
            - cutoff más cercano (si consta)

            Preferencia:
            1) Si ya viene calculado en la muestra (columna delta_cutoff), se usa directamente.
            2) Si no viene, se intenta calcular con value + thresholds desde settings.
            """
            delta = _to_float(m.get(f"{gen}_delta_cutoff"))
            near = _to_float(m.get(f"{gen}_cutoff_nearest"))
            if delta is not None:
                return float(delta), near

            v = _to_float(m.get(f"{gen}_value"))
            ths = _get_gene_thresholds(gen)
            delta, near = _closest_threshold(v, ths)
            if delta is None:
                return None
            return float(delta), near

        # 5.1) Evaluación de genes prioritarios
        for gen in genes:
            res = _eval_gene(gen)
            if not res:
                continue
            delta, _near = res

            tag = f"{gen} (Δ={delta:.2f})"
            if delta <= umbral_crit + eps:
                genes_crit.append(tag)
            elif allow_cerca and delta <= umbral_cerca + eps:
                genes_cerca.append(tag)

        # 5.2) Fallback: si no hay genes prioritarios, solo avisar si está MUY cerca
        # para no llenar la app de avisos cuando no hay contexto clínico.
        if not genes and not genes_crit:
            crit_candidates = []
            for gen in genes_fallback:
                res = _eval_gene(gen)
                if not res:
                    continue
                delta, _near = res

                if delta <= umbral_crit + eps:
                    # Sin contexto: solo se acepta si es “supercrítico”
                    if hay_contexto or (delta <= umbral_supercrit + eps):
                        crit_candidates.append((delta, gen))

            # Se quedan con los dos más cercanos para no saturar.
            crit_candidates.sort(key=lambda x: x[0])
            for delta, gen in crit_candidates[:2]:
                genes_crit.append(f"{gen} (Δ={delta:.2f})")

        if genes_crit:
            bullets.append(
                "MMT muy cercano a cutoff (CRÍTICO): "
                + ", ".join(genes_crit)
                + f". (umbral ≤{umbral_crit:.2f} Ct) Interpretar con cautela."
            )

        if genes_cerca:
            bullets.append(
                "MMT cercano a cutoff: "
                + ", ".join(genes_cerca)
                + f". (umbral ≤{umbral_cerca:.2f} Ct) Interpretar con cautela."
            )

    # -------------------------
    # 6) Celularidad baja
    # -------------------------
    # Si la celularidad tumoral es muy baja, los resultados IHQ pueden ser
    # poco representativos. Se avisa al facultativo para que lo considere.
    celularidad = _to_float(m.get("celularidad"))
    umbral_celularidad = float(cfg_cli.get("celularidad_minima_pct", 20.0))
    if celularidad is not None and celularidad < umbral_celularidad:
        bullets.append(
            f"Celularidad tumoral baja: {int(round(celularidad))}% "
            f"(umbral mínimo recomendado: {int(umbral_celularidad)}%). "
            "Los resultados IHQ y MMT pueden ser menos representativos. "
            "Revisar con el caso original."
        )

    # -------------------------
    # 7) Datos incompletos
    # -------------------------
    # Idea: si hay “algo” de IHQ y “algo” de MMT, pero faltan demasiados campos clave,
    # se avisa para no interpretar un resultado parcial.
    hay_ihq = any([
        not _na(m.get("ESR1_IHQ")), not _na(m.get("PGR_IHQ")),
        not _na(m.get("KI67_IHQ")), not _na(m.get("HER2_IHQ_score")),
        not _na(m.get("HER2_SISH_result")), not _na(m.get("HER2_final")),
    ])

    hay_mmt = any([
        not _na(m.get("ESR1_status")), not _na(m.get("PGR_status")),
        not _na(m.get("ERBB2_status")), not _na(m.get("MKI67_status")),
        not _na(m.get("ESR1_value")), not _na(m.get("PGR_value")),
        not _na(m.get("ERBB2_value")), not _na(m.get("MKI67_value")),
    ])

    if f_faltan and (hay_ihq and hay_mmt):
        faltan = []
        if _is_pos(m.get("ESR1_IHQ")) is None: faltan.append("ER(IHQ)")
        if _is_pos(m.get("PGR_IHQ")) is None: faltan.append("PR(IHQ)")
        if _to_int(m.get("KI67_IHQ")) is None: faltan.append("Ki-67(IHQ)")
        if _is_pos(m.get("ESR1_status")) is None: faltan.append("ESR1(MMT)")
        if _is_pos(m.get("PGR_status")) is None: faltan.append("PGR(MMT)")
        if _is_pos(m.get("ERBB2_status")) is None: faltan.append("ERBB2(MMT)")
        if _is_pos(m.get("MKI67_status")) is None: faltan.append("MKI67(MMT)")

        if _extract_ihq_score(m.get("HER2_IHQ_score")) is None and _na(m.get("HER2_SISH_result")) and _na(m.get("HER2_final")):
            faltan.append("HER2(IHQ/SISH)")

        # Se avisa siempre que falten demasiados campos, incluso si ya hay otros avisos.
        # Importante: una discordancia basada en datos parciales puede ser artefactual.
        if len(faltan) >= 5:
            msg = "Datos incompletos: faltan/NC " + ", ".join(faltan) + "."
            if bullets:
                msg += " Los avisos anteriores deben interpretarse con cautela por datos parciales."
            bullets.append(msg)
            incompleto = True

    # -------------------------
    # 8) Coherencias internas mínimas (solo si el caso no se marcó como incompleto)
    # -------------------------
    # Si IHQ es positivo pero falta el porcentaje, se avisa porque puede ser relevante
    # para interpretar “low positive”.
    if not incompleto:
        if f_er and _is_pos(m.get("ESR1_IHQ")) is True and er_pct is None:
            bullets.append("ER IHQ positivo pero porcentaje no consta (dato incompleto).")
        if f_pr and _is_pos(m.get("PGR_IHQ")) is True and pr_pct is None:
            bullets.append("PR IHQ positivo pero porcentaje no consta (dato incompleto).")

    # Limpieza final: elimina elementos vacíos o con espacios.
    bullets = [b.strip() for b in bullets if isinstance(b, str) and b.strip()]

    if not bullets:
        return None

    # Formato final: lista con viñetas para facilitar lectura en app/PDF.
    return "• " + "\n• ".join(bullets)