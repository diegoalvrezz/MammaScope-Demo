# ajustes.py
import io
import json
import os
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Tuple

import streamlit as st

from auth import current_user
from db import (
    DB_PATH,
    export_db_filtered,
    list_users,
    create_user,
    set_user_role,
    set_user_active,
    set_user_must_change_password,
    update_user_password,
    get_audit_log,
    log_action,
)
from sync_pack import import_transfer_zip


# =========================================================
# Rutas
# =========================================================
BASE_DIR = os.path.dirname(__file__)
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")

ASSETS_DIR = os.path.join(BASE_DIR, "assets")

HISTORY_DIR = os.path.join(BASE_DIR, "settings_history")



# =========================================================
# Valores por defecto
# =========================================================
DEFAULT_SETTINGS: Dict[str, Any] = {
    "settings_meta": {
        "last_modified": None,   
        "modified_by": "usuario",
        "version": "1.0",
    },
    "clinico": {
        "mmt_ranges": {
            "ERBB2": {
                "vmin": 34.0,
                "vmax": 42.0,
                "thresholds": [38.3, 40.4],
                "labels": [
                    {"text": "HER2 zero/ultra low", "pos": 36.5},
                    {"text": "HER2 Low", "pos": 39.1},
                    {"text": "HER2 Positive", "pos": 41.2},
                ],
            },
            "ESR1": {
                "vmin": 34.0,
                "vmax": 42.0,
                "thresholds": [37.1, 38.2],
                "labels": [
                    {"text": "ER Negative", "pos": 35.5},
                    {"text": "ER Low Positive", "pos": 37.6},
                    {"text": "ER Positive", "pos": 40.4},
                ],
            },
            "PGR": {
                "vmin": 34.0,
                "vmax": 42.0,
                "thresholds": [35.0, 36.3],
                "labels": [
                    {"text": "PR Negative", "pos": 34.8},
                    {"text": "PR Positive", "pos": 40.4},
                ],
            },
            "MKI67": {
                "vmin": 32.0,
                "vmax": 40.0,
                "thresholds": [35.1, 36.3, 37.0, 37.7],
                "labels": [
                    {"text": "Ki-67 Negative", "pos": 33.2},
                    {"text": "Ki-67 Positive", "pos": 37.2},
                ],
            },
        },
        "ki67_cutoff_ihq": 20.0,
        "pr_bajo_pct": 10.0,
        "er_bajo_pct": 10.0,
        "celularidad_minima_pct": 20.0,

        "avisos": {
            "activar": True,
            "incluir_en_pdf": False,   
            "incluir_en_app": True,

            "avisar_her2_low_sin_score": True,
            "avisar_discordancia_er": True,
            "avisar_discordancia_pr": True,
            "avisar_discordancia_her2": True,
            "avisar_discordancia_subtipo": True,


            "avisar_proximidad_cutoff": True,
            "cutoff_prox_critico_ct": 0.20,
            "cutoff_prox_cercano_ct": 0.50,
            "cutoff_prox_supercritico_ct": 0.05,

            "avisar_er_low_ihq": True,
            "avisar_her2_2plus_sin_sish": True,
            "avisar_her2_3plus_sin_sish": True,
            "avisar_faltan_datos_clave": True,

            "nivel_por_defecto": "WARNING",  # INFO / WARNING / CRITICO

            "texto_cabecera_pdf": "Avisos / Revisión",
            "texto_cabecera_app": "Avisos automáticos del lote",
            "texto_disclaimer": "Aviso automático: indica discordancias potenciales y requiere revisión por facultativo responsable.",
        },
    },
    "pdf": {

        "mostrar_mapas_calor": True,
        "mostrar_comentario_automatico": False,  


        "mostrar_identificacion": True,
        "mostrar_vista_rapida": True,
        "mostrar_tabla_genes": True,
        "mostrar_ihq_her2": True,
        "mostrar_concordancia_ihq_mmt": True,
        "mostrar_footer_firmantes": True,


        "mostrar_panel_integrado": True,

        "mostrar_resumen_cutoffs": True,
        "mostrar_visual_cutoffs": True,


        "cutoffs_visual_max_delta": 1.0,
        "cutoff_visual_critico_ct": 0.20,
        "cutoff_visual_cercano_ct": 0.50,


        "logo_path": "hubu_escudo.png",
        "titulo_servicio": "SERVICIO DE ANATOMÍA PATOLÓGICA – HUBU",
        "titulo_informe": "INFORME INTEGRADO IHQ + MammaTyper®",


        "section_titles": {
            "identificacion": "Identificación",
            "vista_rapida": "Vista rápida",
            "tabla_genes": "MammaTyper® – Biomarcadores qRT-PCR",
            "mapas_calor": "Mapas de calor (MammaTyper®) – Rojo: Valor. Negro: Límites",
            "ihq_her2": "IHQ / HER2",
            "barras_ihq": "IHQ – Distribución porcentual",
            "resumen_cutoffs": "Resumen MMT (valor, cutoffs y cercanía)",
            "visual_cutoffs": "Proximidad a cutoffs (Δabs, Ct)",
            "comentario": "Comentario automático según la info. de los informes",
        },

        "max_lines_aviso": 4,
        "max_lines_comentario": 3,

        "footer_disclaimer": (
            "Informe generado automáticamente a partir de datos IHQ + MammaTyper®. "
            "Validación por facultativo responsable. "
            "HER2-low se atribuye al comentario del informe original si el score IHQ no está documentado."
        ),
    },
    "exportacion": {
        "zip_nombre_template": "informes_{timestamp}",
        "timestamp_format": "%Y-%m-%d_%H%M",
        "incluir_excel_resumen_en_zip": False,
    },
    "app": {
        "validacion_estricta": True,
        "mostrar_columnas_tecnicas": True,
    },
}


# =========================================================
# Helpers (meta / history)
# =========================================================
def _now_iso() -> str:
    """
    Devuelve la fecha/hora actual en formato ISO 8601 con precisión de segundos.

    Se usa para:
    - Rellenar `settings_meta.last_modified`.
    - Mantener trazabilidad básica de cuándo se modificó la configuración.

    Nota: se toma la hora local del sistema donde se ejecuta la app.
    """
    return datetime.now().isoformat(timespec="seconds")


def _timestamp_compacto() -> str:
    """
    Devuelve un sello temporal compacto pensado para nombres de archivo.

    Ejemplo: 2026-02-25_143012

    Se usa sobre todo para crear copias históricas de settings sin colisiones
    (si se guarda varias veces en un mismo día).
    """
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def _write_history_copy(settings: Dict[str, Any]) -> None:
    """
    Guarda una copia del settings actual en la carpeta de histórico.

    Objetivo:
    - Tener trazabilidad de cambios en `settings.json`.
    - Poder recuperar estados anteriores si algo se configura mal.

    No valida el contenido: asume que ya viene validado/autocorregido antes
    de llamar a esta función.
    """
    os.makedirs(HISTORY_DIR, exist_ok=True)
    fname = f"settings_{_timestamp_compacto()}.json"
    fpath = os.path.join(HISTORY_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# =========================================================
# Validación y autocorrección
# =========================================================
def ensure_settings_file():
    """
    Garantiza que existe `settings.json`.

    Si no existe:
    - Crea la carpeta destino si hace falta.
    - Guarda una copia de `DEFAULT_SETTINGS` como configuración inicial.

    Importante:
    - `create_history=False` porque en un primer arranque no tiene sentido
      generar histórico aún: el histórico se vuelve útil cuando ya hay cambios.
    """
    if not os.path.exists(SETTINGS_PATH):
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        save_settings(deepcopy(DEFAULT_SETTINGS), create_history=False)


def validate_settings(settings: Dict[str, Any], autocorrect: bool = True) -> Tuple[Dict[str, Any], list]:
    """
    Valida (y, si se permite, autocorrige) el diccionario de configuración.

    Qué hace:
    - Asegura que existan bloques clave (`clinico`, `pdf`, etc.).
    - Rellena valores faltantes con defaults.
    - Corrige valores claramente inválidos (por ejemplo negativos, tipos erróneos).
    - Mantiene compatibilidad con nombres antiguos de claves si existiesen.

    Qué devuelve:
    - settings (posiblemente modificado)
    - warnings: lista de textos para informar al usuario de correcciones aplicadas

    Filosofía:
    - "Autocorrección suave": intenta arreglar sin bloquear al usuario.
    - Si no se puede arreglar de forma segura, se restaura el valor por defecto.
    """
    warnings = []

    # ---- meta ----
    # Aseguramos que settings_meta exista y tenga forma de diccionario.
    meta = settings.get("settings_meta")
    if not isinstance(meta, dict):
        settings["settings_meta"] = deepcopy(DEFAULT_SETTINGS["settings_meta"])

    # ---- CLÍNICO / avisos ----
    # Garantiza que exista el bloque clínico y, dentro, el bloque de avisos.
    if "clinico" not in settings or not isinstance(settings.get("clinico"), dict):
        settings["clinico"] = deepcopy(DEFAULT_SETTINGS["clinico"])

    # Umbrales clínicos configurables: ki67, PR bajo, ER bajo.
    for _key, _default in [
        ("ki67_cutoff_ihq",        20.0),
        ("pr_bajo_pct",            10.0),
        ("er_bajo_pct",            10.0),
        ("celularidad_minima_pct", 20.0),
    ]:
        try:
            v = float(settings["clinico"].get(_key, _default))
            if v <= 0 or v >= 100:
                raise ValueError
            settings["clinico"][_key] = v
        except Exception:
            warnings.append(f"clinico.{_key} inválido. Se restaura default ({_default}).")
            settings["clinico"][_key] = float(_default)

    avisos = settings.get("clinico", {}).get("avisos")
    if not isinstance(avisos, dict):
        settings["clinico"]["avisos"] = deepcopy(DEFAULT_SETTINGS["clinico"]["avisos"])
        avisos = settings["clinico"]["avisos"]

    # Compatibilidad con nombres antiguos: si en versiones previas existían claves
    # con nombres diferentes, intentamos mapearlas a las actuales.
    if "avisar_cerca_cutoff_mmt" in avisos and "avisar_proximidad_cutoff" not in avisos:
        avisos["avisar_proximidad_cutoff"] = bool(avisos.get("avisar_cerca_cutoff_mmt", True))
    if "umbral_cerca_cutoff_mmt" in avisos and "cutoff_prox_cercano_ct" not in avisos:
        try:
            avisos["cutoff_prox_cercano_ct"] = float(avisos.get("umbral_cerca_cutoff_mmt", 0.50))
        except Exception:
            # Si el valor antiguo no se puede convertir, se ignora y se usará default.
            pass

    # Normalización de flags esperados (por si venían como string u otros tipos).
    avisos["activar"] = bool(avisos.get("activar", True))
    avisos["incluir_en_pdf"] = bool(
        avisos.get("incluir_en_pdf", DEFAULT_SETTINGS["clinico"]["avisos"]["incluir_en_pdf"])
    )
    avisos["incluir_en_app"] = bool(avisos.get("incluir_en_app", True))

    avisos["avisar_proximidad_cutoff"] = bool(avisos.get("avisar_proximidad_cutoff", True))

    # Flags nuevos: se garantiza que existen con su valor por defecto.
    for _flag, _default in [
        ("avisar_er_low_ihq",         True),
        ("avisar_her2_2plus_sin_sish", True),
        ("avisar_her2_3plus_sin_sish", True),
        ("avisar_faltan_datos_clave",  True),
    ]:
        avisos[_flag] = bool(avisos.get(_flag, _default))

    # Umbral supercrítico: debe ser menor que el crítico.
    try:
        avisos["cutoff_prox_supercritico_ct"] = float(
            avisos.get("cutoff_prox_supercritico_ct", 0.05)
        )
        if avisos["cutoff_prox_supercritico_ct"] <= 0:
            raise ValueError
    except Exception:
        avisos["cutoff_prox_supercritico_ct"] = 0.05

    # Validación numérica de los umbrales de proximidad.
    # Se asume que deben ser > 0 (en Ct), y que el crítico debe ser <= cercano.
    for k, default in [
        ("cutoff_prox_critico_ct", 0.20),
        ("cutoff_prox_cercano_ct", 0.50),
    ]:
        try:
            avisos[k] = float(avisos.get(k, default))
            if avisos[k] <= 0:
                raise ValueError
        except Exception:
            warnings.append(f"clinico.avisos.{k} inválido. Se restaura default.")
            avisos[k] = float(DEFAULT_SETTINGS["clinico"]["avisos"][k])

    if avisos["cutoff_prox_critico_ct"] > avisos["cutoff_prox_cercano_ct"]:
        warnings.append("clinico.avisos.cutoff_prox_critico_ct > cutoff_prox_cercano_ct. Se corrige.")
        if autocorrect:
            avisos["cutoff_prox_critico_ct"], avisos["cutoff_prox_cercano_ct"] = (
                avisos["cutoff_prox_cercano_ct"],
                avisos["cutoff_prox_critico_ct"],
            )

    # ---- MMT ranges ----
    # Este bloque define vmin/vmax, thresholds y labels para el renderizado de mapas de calor.
    # Se valida estructura básica y se corrige el orden de thresholds.
    mmt = settings.get("clinico", {}).get("mmt_ranges", {})
    if not isinstance(mmt, dict):
        settings["clinico"]["mmt_ranges"] = deepcopy(DEFAULT_SETTINGS["clinico"]["mmt_ranges"])
        mmt = settings["clinico"]["mmt_ranges"]

    for gen, cfg in mmt.items():
        if not isinstance(cfg, dict):
            warnings.append(f"{gen}: cfg inválido. Se restaura default.")
            settings["clinico"]["mmt_ranges"][gen] = deepcopy(DEFAULT_SETTINGS["clinico"]["mmt_ranges"][gen])
            continue

        try:
            vmin = float(cfg.get("vmin", 0))
            vmax = float(cfg.get("vmax", 0))
        except Exception:
            warnings.append(f"{gen}: vmin/vmax inválidos. Se restauran defaults.")
            settings["clinico"]["mmt_ranges"][gen] = deepcopy(DEFAULT_SETTINGS["clinico"]["mmt_ranges"][gen])
            continue

        # Si vmin >= vmax el rango no es usable para visualización.
        # Autocorrección: genera un rango razonable alrededor de un punto medio.
        if vmin >= vmax:
            warnings.append(f"{gen}: vmin>=vmax. Se corrige.")
            if autocorrect:
                mid = (vmin + vmax) / 2 if (vmin + vmax) != 0 else 38.0
                cfg["vmin"] = mid - 2
                cfg["vmax"] = mid + 2

        # Umbrales: deben ser lista de números.
        th = cfg.get("thresholds", [])
        if not isinstance(th, list):
            warnings.append(f"{gen}: thresholds no es lista. Se restaura.")
            cfg["thresholds"] = deepcopy(DEFAULT_SETTINGS["clinico"]["mmt_ranges"][gen]["thresholds"])
        else:
            try:
                th_f = sorted([float(x) for x in th])
                cfg["thresholds"] = th_f
            except Exception:
                warnings.append(f"{gen}: thresholds inválidos. Se restaura.")
                cfg["thresholds"] = deepcopy(DEFAULT_SETTINGS["clinico"]["mmt_ranges"][gen]["thresholds"])

        # Etiquetas: se intenta asegurar que la posición cae dentro de [vmin, vmax].
        labels = cfg.get("labels", [])
        if isinstance(labels, list):
            for lab in labels:
                if "pos" in lab:
                    try:
                        p = float(lab["pos"])
                        if p < float(cfg["vmin"]) or p > float(cfg["vmax"]):
                            warnings.append(f"{gen}: label pos fuera de rango. Se ajusta.")
                            lab["pos"] = min(max(p, float(cfg["vmin"])), float(cfg["vmax"]))
                    except Exception:
                        warnings.append(f"{gen}: label pos inválido. Se fija a vmin.")
                        lab["pos"] = float(cfg["vmin"])

    # ---- PDF limits + switches ----
    pdf = settings.get("pdf", {})
    if not isinstance(pdf, dict):
        settings["pdf"] = deepcopy(DEFAULT_SETTINGS["pdf"])
        pdf = settings["pdf"]

    # Límites de líneas: protegen el layout del PDF para que no se "rompa".
    for k in ["max_lines_aviso", "max_lines_comentario"]:
        try:
            v = int(pdf.get(k, 1))
            if v < 1:
                raise ValueError
            pdf[k] = v
        except Exception:
            warnings.append(f"pdf.{k} inválido. Se restaura default.")
            pdf[k] = int(DEFAULT_SETTINGS["pdf"][k])

    # Switches booleanos esperados en el bloque PDF.
    bool_keys = [
        "mostrar_mapas_calor",
        "mostrar_comentario_automatico",
        "mostrar_identificacion",
        "mostrar_vista_rapida",
        "mostrar_tabla_genes",
        "mostrar_ihq_her2",
        "mostrar_concordancia_ihq_mmt",
        "mostrar_footer_firmantes",
        "mostrar_resumen_cutoffs",
        "mostrar_visual_cutoffs",
        "mostrar_panel_integrado",
    ]
    for k in bool_keys:
        pdf[k] = bool(pdf.get(k, DEFAULT_SETTINGS["pdf"].get(k, True)))

    # Parámetros numéricos para el bloque visual de cutoffs.
    for k, default in [
        ("cutoffs_visual_max_delta", 1.0),
        ("cutoff_visual_critico_ct", 0.20),
        ("cutoff_visual_cercano_ct", 0.50),
    ]:
        try:
            pdf[k] = float(pdf.get(k, default))
            if pdf[k] <= 0:
                raise ValueError
        except Exception:
            warnings.append(f"pdf.{k} inválido. Se restaura default.")
            pdf[k] = float(DEFAULT_SETTINGS["pdf"][k])

    if pdf["cutoff_visual_critico_ct"] > pdf["cutoff_visual_cercano_ct"]:
        warnings.append("pdf.cutoff_visual_critico_ct > pdf.cutoff_visual_cercano_ct. Se corrige.")
        if autocorrect:
            pdf["cutoff_visual_critico_ct"], pdf["cutoff_visual_cercano_ct"] = (
                pdf["cutoff_visual_cercano_ct"],
                pdf["cutoff_visual_critico_ct"],
            )

    # section_titles: se asegura que exista y que tenga al menos las claves del default.
    stitles = pdf.get("section_titles")
    if not isinstance(stitles, dict):
        pdf["section_titles"] = deepcopy(DEFAULT_SETTINGS["pdf"]["section_titles"])
    else:
        for kk, vv in DEFAULT_SETTINGS["pdf"]["section_titles"].items():
            if kk not in stitles:
                stitles[kk] = vv

    return settings, warnings


# =========================================================
# I/O settings
# =========================================================
def _merge_defaults(base: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mezcla recursiva de configuración.

    Comportamiento:
    - Si una clave no existe en `base`, se copia desde `defaults`.
    - Si existe y ambos valores son diccionarios, se desciende recursivamente.
    - No elimina claves "extra" presentes en `base` (esto permite extensiones futuras
      o configuraciones importadas con parámetros adicionales).

    Se usa para:
    - Completar configuraciones importadas o antiguas.
    - Garantizar que siempre existan las claves esperadas por el código.
    """
    out = deepcopy(base)
    for k, v in defaults.items():
        if k not in out:
            out[k] = deepcopy(v)
        else:
            if isinstance(v, dict) and isinstance(out[k], dict):
                out[k] = _merge_defaults(out[k], v)
    return out


def load_settings() -> Dict[str, Any]:
    """
    Carga la configuración desde `settings.json` y garantiza consistencia.

    Pasos:
    1) Asegura que el archivo exista (si no existe, crea uno con defaults).
    2) Lee el JSON.
    3) Rellena claves faltantes con defaults (_merge_defaults).
    4) Valida y autocorrige valores incompatibles.

    Si algo falla (archivo corrupto, JSON inválido, permisos, etc.):
    - Devuelve `DEFAULT_SETTINGS` para no bloquear el uso de la app.
    """
    ensure_settings_file()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data = _merge_defaults(data, DEFAULT_SETTINGS)
        data, _ = validate_settings(data, autocorrect=True)
        return data
    except Exception:
        return deepcopy(DEFAULT_SETTINGS)


def save_settings(settings: Dict[str, Any], create_history: bool = True) -> None:
    """
    Guarda la configuración en disco (settings.json), de forma robusta.

    Qué asegura antes de escribir:
    - Completa claves faltantes con defaults.
    - Garantiza que exista el bloque `settings_meta`.
    - Actualiza `settings_meta.last_modified`.
    - Valida y autocorrige.

    Histórico:
    - Si `create_history=True`, guarda además una copia en `settings_history/`.
      El histórico es útil para trazabilidad y recuperación ante cambios erróneos.

    Nota:
    - Si falla la creación del histórico, el guardado principal sigue adelante.
    """
    settings = _merge_defaults(settings, DEFAULT_SETTINGS)
    if "settings_meta" not in settings or not isinstance(settings["settings_meta"], dict):
        settings["settings_meta"] = deepcopy(DEFAULT_SETTINGS["settings_meta"])
    settings["settings_meta"]["last_modified"] = _now_iso()

    settings, _ = validate_settings(settings, autocorrect=True)

    if create_history:
        try:
            _write_history_copy(settings)
        except Exception:
            # El histórico es deseable, pero no debe impedir el guardado principal.
            pass

    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def reset_settings() -> None:
    """
    Restaura la configuración a los valores por defecto.

    Se guarda con histórico para poder auditar qué había antes del reset.
    """
    save_settings(deepcopy(DEFAULT_SETTINGS), create_history=True)


# =========================================================
# UI Streamlit
# =========================================================
from html import escape

import textwrap
import streamlit.components.v1 as components


def _fmt(x: float) -> str:
    """
    Formatea un número con una decimal y coma como separador.

    Se usa en el render HTML para mostrar rangos de Ct de forma más natural
    para usuarios en entorno español.
    """
    return f"{x:.1f}".replace(".", ",")

def render_tabla_cutoffs_mmt(mmt_ranges: Dict[str, Any]) -> None:
    """
    Renderiza una tabla visual (HTML) con los tramos definidos por vmin/vmax y thresholds.

    Objetivo:
    - Ofrecer una vista rápida, fácil de leer, de cómo se segmentan los valores
      de cada gen en función de los puntos de corte.

    Cómo se construye:
    - Para cada gen:
      - `edges = [vmin] + thresholds + [vmax]`
      - Cada tramo se representa como un bloque de color con su rango (o < / >=).
    - Se mantiene un orden preferente de genes (ERBB2, ESR1, PGR, MKI67) y luego el resto.

    Notas prácticas:
    - Si un gen no tiene thresholds o el rango es inválido (vmin >= vmax), se omite.
    - La altura del componente HTML se ajusta en función del número de filas.
    """

    # Paleta sobria orientada a entorno clínico (evita colores chillones).
    COLORS = {
        "green": "#2f855a",
        "amber": "#b7791f",
        "red":   "#c53030",
        "card":  "#ffffff",
        "head":  "#f8fafc",
        "line":  "#e5e7eb",
        "text":  "#111827",
        "muted": "#6b7280",
    }

    def tramo_color(i: int, n: int) -> str:
        """
        Devuelve el color del tramo i, dado el número total de tramos n.

        Se contemplan algunos patrones típicos (2, 3 y 5 tramos) para que el gradiente
        tenga sentido clínico/visual.
        """
        if n == 3:
            return [COLORS["green"], COLORS["amber"], COLORS["red"]][i]
        if n == 2:
            return [COLORS["green"], COLORS["red"]][i]
        if n == 5:
            return [COLORS["green"], COLORS["amber"], COLORS["amber"], COLORS["red"], COLORS["red"]][i]
        return COLORS["amber"]

    def tramo_texto(th: list[float], i: int, edges: list[float]) -> str:
        """
        Genera el texto que se muestra dentro del tramo.

        - Primer tramo: "< threshold_0"
        - Último tramo: ">= threshold_last"
        - Tramos intermedios: "a–b"
        """
        if i == 0:
            return f"&lt;{_fmt(th[0])}"
        if i == len(edges) - 2:
            return f"&ge;{_fmt(th[-1])}"
        return f"{_fmt(edges[i])}–{_fmt(edges[i+1])}"

    gene_order = ["ERBB2", "ESR1", "PGR", "MKI67"]
    genes = [g for g in gene_order if g in mmt_ranges] + [g for g in mmt_ranges if g not in gene_order]

    rows_html = []
    max_tramos = 0  # Se usa para dimensionar el alto del componente.

    for gen in genes:
        cfg = mmt_ranges[gen]
        vmin = float(cfg.get("vmin", 0))
        vmax = float(cfg.get("vmax", 0))
        th = sorted([float(x) for x in cfg.get("thresholds", [])])

        # Si no hay umbrales o el rango no es válido, no tiene sentido dibujarlo.
        if not th or vmin >= vmax:
            continue

        edges = [vmin] + th + [vmax]
        n = len(edges) - 1
        max_tramos = max(max_tramos, n)

        segs = []
        for i in range(n):
            base = tramo_color(i, n)
            txt = tramo_texto(th, i, edges)

            segs.append(f"""
              <div class="seg" style="--seg:{base}">
                <div class="segText">{txt}</div>
              </div>
            """)

        rows_html.append(f"""
          <div class="row">
            <div class="gene">
              <div class="geneName">{escape(gen)}</div>
              <div class="geneSub">40-ΔΔCq</div>
            </div>
            <div class="segs" style="grid-template-columns: repeat({n}, minmax(0, 1fr));">
              {''.join(segs)}
            </div>
          </div>
        """)

    # HTML/CSS encapsulado para que el resultado sea consistente dentro de Streamlit.
    html = f"""
    <style>
      .mmtCard {{
        border: 1px solid {COLORS["line"]};
        border-radius: 16px;
        overflow: hidden;
        background: {COLORS["card"]};
        box-shadow: 0 2px 10px rgba(17,24,39,0.06);
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto;
      }}

      .mmtHead {{
        display: grid;
        grid-template-columns: 190px 1fr;
        padding: 12px 14px;
        background: {COLORS["head"]};
        border-bottom: 1px solid {COLORS["line"]};
        font-weight: 800;
        letter-spacing: .2px;
        color: {COLORS["text"]};
      }}
      .mmtHead div {{
        font-size: 13px;
      }}

      .row {{
        display: grid;
        grid-template-columns: 190px 1fr;
        border-bottom: 1px solid {COLORS["line"]};
      }}
      .row:last-child {{ border-bottom: none; }}

      .gene {{
        padding: 16px 14px;
        background: {COLORS["head"]};
        border-right: 1px solid {COLORS["line"]};
      }}
      .geneName {{
        font-size: 22px;
        font-weight: 900;
        color: {COLORS["text"]};
        line-height: 1.05;
      }}
      .geneSub {{
        margin-top: 6px;
        font-size: 13px;
        color: {COLORS["muted"]};
        font-weight: 700;
      }}

      .segs {{
        display: grid;
      }}

      .seg {{
        position: relative;
        display:flex;
        align-items:center;
        justify-content:center;
        padding: 16px 10px;
        background: linear-gradient(180deg, rgba(255,255,255,0.10), rgba(0,0,0,0.08)), var(--seg);
        border-right: 1px solid rgba(255,255,255,0.18);
      }}
      .seg:last-child {{ border-right: none; }}

      .segText {{
        font-size: 20px;
        font-weight: 900;
        color: white;
        text-align:center;
        line-height: 1.05;
        letter-spacing: .2px;
        text-shadow: 0 1px 2px rgba(0,0,0,0.20);
        white-space: nowrap;
      }}

      @media (max-width: 760px) {{
        .mmtHead, .row {{ grid-template-columns: 150px 1fr; }}
        .segText {{ white-space: normal; }}
      }}
    </style>

    <div class="mmtCard">
      <div class="mmtHead">
        <div>Gen</div>
        <div>Tramos (40-ΔΔCq)</div>
      </div>
      {''.join(rows_html)}
    </div>
    """

    html = textwrap.dedent(html).strip()
    components.html(html, height=120 + 84 * max(1, len(rows_html)), scrolling=False)



def mostrar_ajustes():
    """
    Renderiza el panel de ajustes de la aplicación.

    Esta pantalla centraliza la configuración operativa y clínica del sistema:
    - Parámetros clínicos (rangos/umbrales MammaTyper y reglas de avisos).
    - Contenido y formato del informe PDF.
    - Opciones de exportación del Excel de salida.
    - Preferencias generales de la app.
    - Importación/exportación de configuración y sincronización offline.
    - (Solo administrador) restauración, gestión de usuarios y auditoría.

    La interfaz es dinámica según el rol del usuario:
    - basico: acceso a herramientas operativas, sin importación de settings ni administración.
    - jefe: acceso a lectura y configuración visual, pero sin permiso para guardar cambios.
    - admin: acceso completo, incluyendo guardado, importación y trazabilidad.

    Los cambios se almacenan en `settings.json` y, cuando procede, se crea una copia
    en el histórico para poder auditar o revertir configuraciones anteriores.
    """
    # Encabezado principal de la pantalla de ajustes.
    # Nota: Streamlit no admite `help=` en st.header; si se mantiene, puede provocar error.
    st.header(
        "Ajustes de la aplicación",
        help="Panel de configuración: parámetros clínicos, PDF, exportación y operación offline.",
    )

    # Asegura que existe `settings.json` antes de permitir visualizar o editar parámetros.
    ensure_settings_file()

    # -------------------------
    # Rol actual
    # -------------------------
    # Se obtiene el usuario actual desde el módulo de autenticación.
    # Si no hay usuario (caso excepcional), se trabaja con un diccionario vacío y rol básico.
    u = current_user() or {}
    rol = u.get("role", "basico")

    # -------------------------
    # Cargar settings en sesión
    # -------------------------
    # Los settings se guardan en st.session_state para:
    # - evitar recargar el archivo en cada interacción
    # - mantener cambios temporales hasta que el usuario pulse "Guardar"
    if "settings" not in st.session_state:
        st.session_state["settings"] = load_settings()

    settings = st.session_state["settings"]

    # Valida y autocorrige la configuración en memoria.
    # Esto evita que valores inválidos rompan la interfaz (por ejemplo, rangos invertidos o tipos incorrectos).
    settings, warns = validate_settings(settings, autocorrect=True)
    st.session_state["settings"] = settings

    # Metadatos informativos del archivo de configuración (trazabilidad básica).
    meta = settings.get("settings_meta", {})
    with st.expander("Estado de la configuración (metadatos)", expanded=False):
        st.write(f"**Última modificación:** {meta.get('last_modified', '—')}")
        st.write(f"**Versión de settings:** {meta.get('version', '—')}")
        st.caption(f"Ruta: {SETTINGS_PATH}")
        st.caption(f"Histórico: {HISTORY_DIR}")

    # Si la validación ha tenido que corregir o restaurar valores, se informa al usuario.
    # Esto es importante cuando se importa un settings.json externo o tras actualizaciones del esquema.
    if warns:
        with st.expander("Avisos de validación", expanded=False):
            for w in warns:
                st.warning(w)

    # Mensaje general de uso: el usuario entiende dónde se guardan los cambios y que existe histórico.
    st.caption(
        "Aquí puedes modificar parámetros clínicos, del PDF y de exportación. "
        "Los cambios se guardan en settings.json (con histórico automático)."
    )

    # =========================
    # PESTAÑAS DINÁMICAS POR ROL
    # =========================
    # Se construye el conjunto de pestañas en función del rol para limitar funcionalidades sensibles.
    tab_names = []

    # Jefe/Admin pueden ver (y configurar) parámetros clínicos/PDF/exportación/app,
    # pero solo Admin podrá guardar cambios persistentes.
    if rol in ("jefe", "admin"):
        tab_names += ["Clínico", "Informe PDF", "Exportación de resultados", "Aplicación"]

    # Esta pestaña la ve todo el mundo, pero con restricciones internas (por ejemplo, rol básico no importa settings).
    tab_names += ["Importar/Exportar"]

    # Funcionalidades sensibles: solo visibles para Administrador.
    if rol == "admin":
        tab_names += ["Restaurar", "Usuarios", "Trazabilidad"]

    tabs = st.tabs(tab_names)
    i = 0  # Índice de pestaña actual. Se incrementa a medida que se consumen pestañas según el rol.

    # =========================
    # PESTAÑA: CLÍNICO (jefe/admin)
    # =========================
    if rol in ("jefe", "admin"):
        with tabs[i]:
            i += 1

            # El rol "jefe" puede revisar parámetros, pero no debe persistir cambios.
            # Aun así, se permite interactuar para explorar el efecto de los parámetros en pantalla.
            if rol != "admin":
                st.warning("Modo solo lectura (rol Jefe). Para guardar cambios se requiere Administrador.")

            # Vista rápida de los puntos de corte para facilitar revisión clínica.
            # Se presenta como una tabla visual basada en vmin/vmax y thresholds del settings.
            st.subheader("Vista rápida: puntos de corte (MMT)")
            st.caption("Resumen rápido de los puntos de corte usados para interpretar CT y clasificar cada gen.")
            render_tabla_cutoffs_mmt(settings["clinico"]["mmt_ranges"])

            # ── Umbrales clínicos ───────────────────────────────────────────────────
            st.markdown("---")
            st.subheader("Umbrales clínicos")
            st.caption(
                "Valores de corte usados en las reglas de discordancia y en el módulo estadístico. "
                "Ajústalos según el protocolo del servicio."
            )

            col_k, col_p, col_e = st.columns(3)
            with col_k:
                settings["clinico"]["ki67_cutoff_ihq"] = st.number_input(
                    "Cutoff Ki-67 IHQ (%)",
                    value=float(settings["clinico"].get("ki67_cutoff_ihq", 20.0)),
                    min_value=1.0,
                    max_value=99.0,
                    step=1.0,
                    help=(
                        "Umbral de Ki-67 por IHQ para clasificar alta/baja proliferación. "
                        "Usado en el módulo estadístico (Kappa, McNemar) y en las reglas de aviso. "
                        "Valor habitual: 14% (St. Gallen) o 20% (ASCO/CAP)."
                    ),
                )
            with col_p:
                settings["clinico"]["pr_bajo_pct"] = st.number_input(
                    "Umbral PR bajo (%)",
                    value=float(settings["clinico"].get("pr_bajo_pct", 10.0)),
                    min_value=1.0,
                    max_value=50.0,
                    step=1.0,
                    help=(
                        "Porcentaje por debajo del cual PR IHQ positivo se considera 'PR bajo'. "
                        "Genera aviso específico de interpretación dependiente del contexto."
                    ),
                )
            with col_e:
                settings["clinico"]["er_bajo_pct"] = st.number_input(
                    "Umbral ER bajo (%)",
                    value=float(settings["clinico"].get("er_bajo_pct", 10.0)),
                    min_value=1.0,
                    max_value=50.0,
                    step=1.0,
                    help=(
                        "Porcentaje por debajo del cual ER IHQ positivo se considera 'ER low positive'. "
                        "Genera aviso específico de zona gris interpretativa."
                    ),
                )

            settings["clinico"]["celularidad_minima_pct"] = st.number_input(
                "Celularidad tumoral mínima recomendada (%)",
                value=float(settings["clinico"].get("celularidad_minima_pct", 20.0)),
                min_value=1.0,
                max_value=80.0,
                step=5.0,
                help=(
                    "Si la celularidad tumoral de la muestra está por debajo de este umbral, "
                    "se genera un aviso indicando que los resultados IHQ y MMT pueden ser "
                    "menos representativos. Valor habitual en la práctica: 20-30%."
                ),
            )

            # Configuración detallada de rangos y umbrales del mapa de calor.
            # Estos parámetros afectan tanto a la visualización como, en algunos casos,
            # a la interpretación cuando se señalan proximidades a umbrales.
            st.markdown("---")
            st.subheader("Rangos y umbrales MammaTyper® (mapas de calor)")
            st.caption("Ajusta la escala del mapa de calor (vmin/vmax), umbrales y etiquetas de zonas para cada gen.")

            mmt = settings["clinico"]["mmt_ranges"]

            # Selección del gen/biomarcador a editar.
            gene_sel = st.selectbox(
                "Selecciona el gen",
                options=list(mmt.keys()),
                index=0,
                help="Elige el biomarcador para editar su escala, umbrales y etiquetas del mapa de calor.",
            )

            cfg = mmt[gene_sel]

            # vmin/vmax definen el rango de Ct representado en el mapa de calor.
            # Se usan como límites de escala para que el gráfico sea consistente entre muestras.
            col1, col2 = st.columns(2)
            with col1:
                cfg["vmin"] = st.number_input(
                    "Valor mínimo (vmin)",
                    value=float(cfg["vmin"]),
                    step=0.1,
                    key=f"vmin_{gene_sel}",
                    help="Límite inferior de la escala del mapa de calor (CT mínimo mostrado).",
                )
            with col2:
                cfg["vmax"] = st.number_input(
                    "Valor máximo (vmax)",
                    value=float(cfg["vmax"]),
                    step=0.1,
                    key=f"vmax_{gene_sel}",
                    help="Límite superior de la escala del mapa de calor (CT máximo mostrado).",
                )

            # Los thresholds marcan puntos de corte internos (zonas) que se reflejan en la visualización.
            # Se introducen como texto para permitir una edición rápida sin varios campos.
            st.markdown("**Umbrales (thresholds)**")
            th_str = st.text_input(
                "Introduce umbrales separados por coma (ej.: 38.3, 40.4)",
                value=", ".join(str(x) for x in cfg.get("thresholds", [])),
                key=f"th_{gene_sel}",
                help="Lista de CT donde cambian las zonas/interpretación. Se usa para colorear y marcar regiones.",
            )
            try:
                cfg["thresholds"] = [float(x.strip()) for x in th_str.split(",") if x.strip() != ""]
            except ValueError:
                # Si el usuario escribe algo no numérico, se muestra error pero no se bloquea el resto de la pestaña.
                st.error("Umbrales inválidos: usa números separados por coma.")

            # Etiquetas dibujadas en el mapa: ayudan a interpretar visualmente cada zona.
            # Se guarda texto y posición aproximada sobre la escala.
            st.markdown("**Etiquetas de zonas (texto + posición)**")
            st.caption("Etiquetas que se dibujan sobre el mapa (texto) y su posición (CT aproximado).")
            labels = cfg.get("labels", [])
            for j, lab in enumerate(labels):
                c1, c2 = st.columns([3, 1])
                with c1:
                    lab["text"] = st.text_input(
                        f"Texto de la etiqueta #{j+1}",
                        value=str(lab.get("text", "")),
                        key=f"lab_text_{gene_sel}_{j}",
                        help="Texto visible en el mapa de calor (p. ej., 'Positivo', 'Negativo', 'Zona gris').",
                    )
                with c2:
                    lab["pos"] = st.number_input(
                        f"Posición #{j+1}",
                        value=float(lab.get("pos", cfg["vmin"])),
                        step=0.1,
                        key=f"lab_pos_{gene_sel}_{j}",
                        help="CT aproximado donde se coloca la etiqueta dentro de la escala vmin–vmax.",
                    )

            # Configuración de avisos automáticos: reglas que señalan discordancias o casos límite.
            # Estos avisos no sustituyen la interpretación clínica: están pensados como apoyo para revisión.
            st.markdown("---")
            st.subheader("Avisos automáticos (discordancias)")
            st.caption("Configura si la app genera avisos cuando hay discordancias o casos límite.")

            avisos = settings["clinico"]["avisos"]
            avisos["activar"] = st.checkbox(
                "Activar avisos automáticos",
                value=avisos["activar"],
                help="Si está activo, se generan avisos según reglas clínicas (discordancias, cercanía a cutoffs, etc.).",
            )
            avisos["incluir_en_app"] = st.checkbox(
                "Mostrar avisos en la aplicación",
                value=avisos["incluir_en_app"],
                help="Muestra los avisos en pantalla para cada muestra procesada.",
            )
            avisos["incluir_en_pdf"] = st.checkbox(
                "Incluir avisos en el PDF (solo si cabe)",
                value=avisos["incluir_en_pdf"],
                help="Añade avisos al PDF si el diseño lo permite sin desbordes.",
            )


            st.markdown("---")
            st.caption("Reglas específicas de aviso (activa o desactiva cada tipo individualmente).")

            col_a, col_b = st.columns(2)
            with col_a:
                avisos["avisar_discordancia_er"] = st.checkbox(
                    "Discordancia ER (IHQ vs MMT)",
                    value=bool(avisos.get("avisar_discordancia_er", True)),
                    help="Avisa cuando el estado ER difiere entre IHQ y MammaTyper®.",
                )
                avisos["avisar_discordancia_pr"] = st.checkbox(
                    "Discordancia PR (IHQ vs MMT)",
                    value=bool(avisos.get("avisar_discordancia_pr", True)),
                    help="Avisa cuando el estado PR difiere entre IHQ y MammaTyper®.",
                )
                avisos["avisar_discordancia_her2"] = st.checkbox(
                    "Discordancia HER2 (IHQ/SISH vs MMT)",
                    value=bool(avisos.get("avisar_discordancia_her2", True)),
                    help="Avisa cuando el estado HER2 difiere entre IHQ/SISH y MammaTyper®.",
                )
                avisos["avisar_discordancia_subtipo"] = st.checkbox(
                    "Discordancia de subtipo (IHQ vs MMT)",
                    value=bool(avisos.get("avisar_discordancia_subtipo", True)),
                    help="Avisa cuando el subtipo molecular difiere entre IHQ y MammaTyper®.",
                )

            with col_b:
                avisos["avisar_her2_low_sin_score"] = st.checkbox(
                    "HER2-low sin score IHQ documentado",
                    value=bool(avisos.get("avisar_her2_low_sin_score", True)),
                    help="Avisa cuando HER2-low se clasifica solo por texto, sin score IHQ.",
                )
                avisos["avisar_er_low_ihq"] = st.checkbox(
                    "ER bajo positivo por IHQ (< 10%)",
                    value=bool(avisos.get("avisar_er_low_ihq", True)),
                    help="Avisa cuando ER IHQ es positivo pero con porcentaje bajo (zona 'low positive').",
                )
                avisos["avisar_her2_2plus_sin_sish"] = st.checkbox(
                    "HER2 IHQ 2+ sin SISH",
                    value=bool(avisos.get("avisar_her2_2plus_sin_sish", True)),
                    help="Avisa cuando HER2 score 2+ (equívoco) no tiene SISH/ISH registrado.",
                )
                avisos["avisar_her2_3plus_sin_sish"] = st.checkbox(
                    "HER2 IHQ 3+ sin SISH registrado",
                    value=bool(avisos.get("avisar_her2_3plus_sin_sish", True)),
                    help="Avisa cuando HER2 score 3+ no tiene SISH registrado en el volcado.",
                )

            avisos["avisar_faltan_datos_clave"] = st.checkbox(
                "Datos clave incompletos",
                value=bool(avisos.get("avisar_faltan_datos_clave", True)),
                help="Avisa cuando faltan demasiados campos clave para una interpretación fiable.",
            )
            avisos["avisar_proximidad_cutoff"] = st.checkbox(
                "Proximidad a punto de corte (MMT)",
                value=bool(avisos.get("avisar_proximidad_cutoff", True)),
                help="Avisa cuando el valor MMT está cerca del umbral de clasificación.",
            )

            st.markdown("**Umbrales de proximidad a cutoff (Ct)**")
            col_c, col_d, col_e = st.columns(3)
            with col_c:
                avisos["cutoff_prox_critico_ct"] = st.number_input(
                    "Crítico (Ct)",
                    value=float(avisos.get("cutoff_prox_critico_ct", 0.20)),
                    min_value=0.01, max_value=1.0, step=0.01,
                    help="Distancia al cutoff por debajo de la cual se genera aviso crítico.",
                )
            with col_d:
                avisos["cutoff_prox_cercano_ct"] = st.number_input(
                    "Cercano (Ct)",
                    value=float(avisos.get("cutoff_prox_cercano_ct", 0.50)),
                    min_value=0.01, max_value=2.0, step=0.01,
                    help="Distancia al cutoff por debajo de la cual se genera aviso de proximidad.",
                )
            with col_e:
                avisos["cutoff_prox_supercritico_ct"] = st.number_input(
                    "Supercrítico (Ct)",
                    value=float(avisos.get("cutoff_prox_supercritico_ct", 0.05)),
                    min_value=0.01, max_value=0.5, step=0.01,
                    help="Umbral interno para avisos sin contexto clínico previo (muy estricto).",
                )

            st.markdown("---")
            # Texto estándar que acompaña a los avisos para dejar clara su naturaleza de ayuda a revisión.
            avisos["texto_disclaimer"] = st.text_area(
                "Texto estándar del aviso (disclaimer)",
                value=avisos.get("texto_disclaimer", ""),
                height=80,
                help="Texto base que acompaña a los avisos (p. ej., precaución/interpretación clínica).",
            )

            # Guardado persistente solo para Administrador.
            # Se valida de nuevo para asegurar consistencia antes de escribir settings.json.
            if rol == "admin":
                if st.button(
                    "Guardar cambios (Clínico)",
                    help="Guarda la configuración clínica en settings.json y crea una copia en el histórico.",
                ):
                    settings, _ = validate_settings(settings, autocorrect=True)
                    st.session_state["settings"] = settings
                    save_settings(settings, create_history=True)
                    log_action(u.get("username"), "settings_save_clinico", None)
                    st.success("Ajustes guardados (con histórico).")
                    st.rerun()

        # =========================
        # PESTAÑA: PDF (jefe/admin)
        # =========================
        with tabs[i]:
            i += 1
            if rol != "admin":
                st.warning("Modo solo lectura (rol Jefe). Para guardar cambios se requiere Administrador.")

            pdf = settings["pdf"]

            # Esta pestaña controla el contenido del informe y opciones de layout.
            # Se separa en identidad (logo/títulos), secciones, títulos personalizados y límites de texto.
            st.subheader("Informe PDF · Contenido y formato")
            st.caption("Estos parámetros afectan a la generación del PDF (plantilla, secciones y visualización).")

            # -------------------------
            # Identidad (logo + títulos)
            # -------------------------
            with st.expander("Identidad del informe", expanded=True):
                st.caption("Configura los títulos del encabezado y el logotipo institucional del informe.")
                col1, col2 = st.columns([2, 1])

                # Textos visibles en el encabezado del PDF.
                with col1:
                    pdf["titulo_servicio"] = st.text_input(
                        "Título del servicio",
                        value=pdf.get("titulo_servicio", ""),
                        help="Texto superior del informe (p. ej., nombre del servicio/unidad).",
                    )
                    pdf["titulo_informe"] = st.text_input(
                        "Título del informe",
                        value=pdf.get("titulo_informe", "Informe MammaTyper"),
                        help="Título principal visible en el encabezado del PDF.",
                    )

                # Carga de logo. Se copia a `assets/` para que el proyecto mantenga un recurso local.
                # La ruta final queda guardada en settings para su uso en el generador de PDFs.
                with col2:
                    st.markdown("### Logotipo del informe")
                    st.caption("Imagen que aparece en el encabezado. Se recomienda PNG/JPG en buena resolución.")

                    current_logo = pdf.get("logo_path", "")
                    if current_logo and os.path.exists(current_logo):
                        st.image(current_logo, width=150)
                        st.caption(f"Logotipo actual: {current_logo}")

                    uploaded_logo = st.file_uploader(
                        "Seleccionar nuevo logotipo (PNG/JPG)",
                        type=["png", "jpg", "jpeg"],
                        key="logo_uploader",
                        help="Sube un archivo para reemplazar el logotipo actual. Se copiará a la carpeta 'assets/'.",
                    )

                    if uploaded_logo is not None:
                        os.makedirs("assets", exist_ok=True)
                        logo_path = os.path.join("assets", uploaded_logo.name)
                        with open(logo_path, "wb") as f:
                            f.write(uploaded_logo.getbuffer())
                        pdf["logo_path"] = logo_path
                        st.success(f"Logotipo guardado en {logo_path}")

            # -------------------------
            # Secciones (qué aparece en el PDF)
            # -------------------------
            # Activar/desactivar secciones permite adaptar el informe al flujo real del servicio
            # o acortarlo si hay limitación de espacio o de página.
            st.markdown("---")
            st.subheader("Secciones visibles en el PDF")
            st.caption("Activa/desactiva bloques del informe. Útil si quieres un PDF más corto o adaptado al servicio.")

            colA, colB, colC = st.columns(3)
            with colA:
                pdf["mostrar_identificacion"] = st.checkbox(
                    "Identificación del caso",
                    value=bool(pdf.get("mostrar_identificacion", True)),
                    help="Incluye datos de identificación de la muestra/caso en el PDF.",
                )
                pdf["mostrar_vista_rapida"] = st.checkbox(
                    "Vista rápida (resumen)",
                    value=bool(pdf.get("mostrar_vista_rapida", True)),
                    help="Incluye un resumen breve de resultados clave al inicio del informe.",
                )
                pdf["mostrar_panel_integrado"] = st.checkbox(
                    "Panel integrado",
                    value=bool(pdf.get("mostrar_panel_integrado", True)),
                    help="Muestra el panel/interpretación integrada (subtipo, HR/HER2, etc.).",
                )

            with colB:
                pdf["mostrar_tabla_genes"] = st.checkbox(
                    "Tabla de genes (valores + estado)",
                    value=bool(pdf.get("mostrar_tabla_genes", True)),
                    help="Incluye la tabla con CT/valores y el estado (Positivo/Negativo) por gen.",
                )
                pdf["mostrar_mapas_calor"] = st.checkbox(
                    "Mapas de calor (MammaTyper®)",
                    value=bool(pdf.get("mostrar_mapas_calor", True)),
                    help="Genera mapas de calor por biomarcador para visualizar rangos y umbrales.",
                )

            with colC:
                pdf["mostrar_ihq_her2"] = st.checkbox(
                    "Sección HER2 por IHQ",
                    value=bool(pdf.get("mostrar_ihq_her2", True)),
                    help="Incluye el bloque específico de HER2 por IHQ (si está disponible en los datos).",
                )
                pdf["mostrar_concordancia_ihq_mmt"] = st.checkbox(
                    "Tabla de concordancia IHQ vs MMT",
                    value=bool(pdf.get("mostrar_concordancia_ihq_mmt", True)),
                    help=(
                        "Añade una tabla que compara directamente los resultados IHQ e MMT "
                        "para cada biomarcador, indicando si hay concordancia o discordancia. "
                        "Se considera esencial para el informe clínico — si no cabe en la página, "
                        "se genera en una segunda página automáticamente."
                    ),
                )
                pdf["mostrar_comentario_automatico"] = st.checkbox(
                    "Comentario automático",
                    value=bool(pdf.get("mostrar_comentario_automatico", True)),
                    help="Añade un comentario automático generado por reglas/plantilla según el caso.",
                )
                pdf["mostrar_footer_firmantes"] = st.checkbox(
                    "Pie con firmantes",
                    value=bool(pdf.get("mostrar_footer_firmantes", True)),
                    help="Añade un pie de firma/validación en el informe PDF.",
                )

            # -------------------------
            # Títulos de secciones (personalizados)
            # -------------------------
            # Permite adaptar el vocabulario del informe a la plantilla del servicio
            # sin tocar el código del generador de PDFs.
            st.markdown("---")
            with st.expander("Títulos personalizados de secciones", expanded=False):
                st.caption("Renombra títulos internos del PDF para adaptarlos a la plantilla del servicio.")
                section_titles = pdf.get("section_titles", {})
                if not isinstance(section_titles, dict):
                    section_titles = {}

                default_keys = [
                    "identificacion",
                    "vista_rapida",
                    "panel_integrado",
                    "tabla_genes",
                    "mapas_calor",
                    "barras_ihq",
                    "comentario",
                    "avisos",
                    "firmantes",
                ]
                for k in default_keys:
                    section_titles[k] = st.text_input(
                        f"Título: {k}",
                        value=str(section_titles.get(k, "")),
                        key=f"pdf_title_{k}",
                        help="Si lo dejas vacío, se usará el título por defecto de la plantilla.",
                    )

                pdf["section_titles"] = section_titles

            # -------------------------
            # Límites de texto (para que no se desmonte el diseño)
            # -------------------------
            # Estos límites protegen la maquetación del PDF (evitan textos largos que desbordan).
            st.markdown("---")
            st.subheader("Límites de texto y Nota aclaratoria (pie del informe)")
            st.caption(" **Se recomienda no modificar.** Limita texto para evitar desbordes y mantener el PDF legible.")

            col1, col2 = st.columns(2)
            with col1:
                pdf["max_lines_aviso"] = st.number_input(
                    "Máximo de líneas por aviso (PDF)",
                    value=int(pdf.get("max_lines_aviso", 2)),
                    min_value=0,
                    max_value=20,
                    step=1,
                    help="Recorta avisos largos para que no rompan el diseño del informe.",
                )
                pdf["max_lines_comentario"] = st.number_input(
                    "Máximo de líneas del comentario automático",
                    value=int(pdf.get("max_lines_comentario", 4)),
                    min_value=0,
                    max_value=50,
                    step=1,
                    help="Limita la extensión del comentario automático en el informe.",
                )

            # Texto fijo de pie de informe para aclaraciones de uso y responsabilidades.
            # La clave debe ser footer_disclaimer para que el generador de PDFs la lea correctamente.
            with col2:
                pdf["footer_disclaimer"] = st.text_area(
                    "Nota aclaratoria (pie del informe)",
                    value=str(pdf.get("footer_disclaimer", "")),
                    height=120,
                    help="Texto de precaución/uso clínico/interpretación que aparecerá al final del PDF.",
                )

            # -------------------------
            # Cutoffs visuales / resumen
            # -------------------------
            # Parámetros para resaltar visualmente si un valor está cercano o crítico respecto a umbrales.
            st.markdown("---")
            st.subheader("Puntos de corte (resumen y visualización)")
            st.caption("Parámetros para resaltar proximidad a umbrales (zonas cercanas/críticas).")

            colX, colY = st.columns(2)
            with colX:
                pdf["mostrar_resumen_cutoffs"] = st.checkbox(
                    "Mostrar resumen de puntos de corte",
                    value=bool(pdf.get("mostrar_resumen_cutoffs", True)),
                    help="Incluye un bloque resumen con los puntos de corte/umbrales usados.",
                )
                pdf["mostrar_visual_cutoffs"] = st.checkbox(
                    "Mostrar señalización visual de puntos de corte",
                    value=bool(pdf.get("mostrar_visual_cutoffs", True)),
                    help="Activa marcadores visuales cuando un CT está cerca del umbral.",
                )

            with colY:
                pdf["cutoffs_visual_max_delta"] = st.number_input(
                    "Δ máximo para considerar 'cercano'",
                    value=float(pdf.get("cutoffs_visual_max_delta", 0.5)),
                    step=0.1,
                    help="Diferencia máxima respecto al punto de corte para marcar un resultado como 'cercano'.",
                )
                pdf["cutoff_visual_cercano_ct"] = st.number_input(
                    "Umbral 'cercano' (CT)",
                    value=float(pdf.get("cutoff_visual_cercano_ct", 0.3)),
                    step=0.1,
                    help="Sensibilidad del marcador 'cercano' en CT (más bajo = más estricto).",
                )
                pdf["cutoff_visual_critico_ct"] = st.number_input(
                    "Umbral 'crítico' (CT)",
                    value=float(pdf.get("cutoff_visual_critico_ct", 0.2)),
                    step=0.1,
                    help="Sensibilidad del marcador 'crítico' en CT (más bajo = más estricto).",
                )

            # Guardado persistente solo para Administrador.
            if rol == "admin":
                if st.button(
                    "Guardar cambios (PDF)",
                    key="save_pdf_settings",
                    help="Guarda los ajustes del PDF en settings.json y crea copia en el histórico.",
                ):
                    settings, _ = validate_settings(settings, autocorrect=True)
                    st.session_state["settings"] = settings
                    save_settings(settings, create_history=True)
                    log_action((u or {}).get("username"), "settings_save_pdf", None)
                    st.success("Ajustes de PDF guardados (con histórico).")
                    st.rerun()

    # =========================
    # PESTAÑA: EXPORTACIÓN (jefe/admin)
    # =========================
    if rol in ("jefe", "admin"):
        with tabs[i]:
            i += 1
            if rol != "admin":
                st.warning("Modo solo lectura (rol Jefe). Para guardar cambios se requiere Administrador.")

            exp = settings["exportacion"]

            st.subheader("Exportación de resultados")
            st.caption("Configuración del formato de los archivos generados al exportar lotes.")

            exp["zip_nombre_template"] = st.text_input(
                "Plantilla de nombre del ZIP",
                value=str(exp.get("zip_nombre_template", "informes_{timestamp}")),
                help="Nombre base del ZIP de exportación. {timestamp} se reemplaza automáticamente.",
            )
            exp["timestamp_format"] = st.text_input(
                "Formato del timestamp",
                value=str(exp.get("timestamp_format", "%Y-%m-%d_%H%M")),
                help="Formato strftime para el timestamp del nombre del ZIP (ej: %Y-%m-%d_%H%M).",
            )
            exp["incluir_excel_resumen_en_zip"] = st.checkbox(
                "Incluir Excel de resumen en el ZIP de exportación",
                value=bool(exp.get("incluir_excel_resumen_en_zip", False)),
                help="Si está activo, el ZIP de exportación incluirá un Excel con el resumen del lote.",
            )

            if rol == "admin":
                if st.button(
                    "Guardar cambios (Exportación)",
                    help="Guarda los ajustes de exportación en settings.json y crea copia en el histórico.",
                ):
                    settings, _ = validate_settings(settings, autocorrect=True)
                    st.session_state["settings"] = settings
                    save_settings(settings, create_history=True)
                    log_action(u.get("username"), "settings_save_exportacion", None)
                    st.success("Ajustes guardados (con histórico).")
                    st.rerun()

    # =========================
    # PESTAÑA: APP (jefe/admin)
    # =========================
    if rol in ("jefe", "admin"):
        with tabs[i]:
            i += 1
            if rol != "admin":
                st.warning("Modo solo lectura (rol Jefe). Para guardar cambios se requiere Administrador.")

            app = settings["app"]

            st.subheader("Comportamiento de la aplicación")
            st.caption("Opciones generales de funcionamiento y validación.")

            app["validacion_estricta"] = st.checkbox(
                "Validación estricta de archivos",
                value=bool(app.get("validacion_estricta", True)),
                help=(
                    "Si está activo, además de extraer registros, se exige que al menos el 70% "
                    "tengan Sample ID válido. Recomendado en producción."
                ),
            )
            app["mostrar_columnas_tecnicas"] = st.checkbox(
                "Mostrar columnas técnicas en vistas de datos",
                value=bool(app.get("mostrar_columnas_tecnicas", True)),
                help=(
                    "Muestra columnas derivadas (cutoff_nearest, delta_cutoff, equiv, etc.) "
                    "en las tablas del histórico. Desactivar para una vista más limpia."
                ),
            )

            if rol == "admin":
                if st.button(
                    "Guardar cambios (Aplicación)",
                    help="Guarda los ajustes de comportamiento en settings.json y crea copia en el histórico.",
                ):
                    settings, _ = validate_settings(settings, autocorrect=True)
                    st.session_state["settings"] = settings
                    save_settings(settings, create_history=True)
                    log_action(u.get("username"), "settings_save_app", None)
                    st.success("Ajustes guardados (con histórico).")
                    st.rerun()

    # =========================
    # PESTAÑA: IMPORTAR / EXPORTAR (todos, con permisos)
    # =========================
    with tabs[i]:
        i += 1

        # Esta pestaña cubre dos necesidades:
        # - sincronización offline mediante ZIP (para equipos sin conexión directa)
        # - exportación/importación de configuración (settings.json)
        st.subheader("Importar / Exportar (operativo)")
        st.caption("Herramientas para sincronización offline y para exportar/importar la configuración.")

        # -------------------------
        # Sincronización sin conexión (ZIP)
        # -------------------------
        st.markdown("## Sincronización sin conexión (ZIP)")
        zip_up = st.file_uploader(
            "Sube el paquete ZIP del otro equipo",
            type=["zip"],
            key="sync_zip",
            help="Importa un ZIP de transferencia (p. ej., auditoría/configuración/datos) para fusionar con este equipo.",
        )

        # Importa y fusiona el paquete. El resultado se registra en auditoría.
        if zip_up is not None and st.button(
            "Importar y fusionar paquete",
            help="Desempaqueta el ZIP y aplica la fusión según las reglas de sincronización (registrado en auditoría).",
        ):
            u = current_user() or {}
            resumen = import_transfer_zip(zip_up.getvalue())
            log_action(u.get("username"), "sync_import_package", resumen)
            st.success("Importación completada")
            st.write(resumen)

        # -------------------------
        # Exportar configuración actual (settings.json)
        # -------------------------
        st.markdown("### Exportar configuración actual")
        st.caption(
            "Para transferir las preferencias establecidas de ajustes a otro equipo. "
            "Al importar el archivo en otro equipo, los ajustes guardados se clonarán en el equipo receptor"
        )

        data = json.dumps(settings, ensure_ascii=False, indent=2).encode("utf-8")
        if st.download_button(
            "Descargar settings.json",
            data=data,
            file_name="settings.json",
            mime="application/json",
            key="dl_settings",
            help="Descarga la configuración actual para respaldo o para moverla a otro equipo.",
        ):
            log_action(u.get("username"), "settings_export", {"role": rol})

        # -------------------------
        # Importar settings.json (solo roles con permiso)
        # -------------------------
        st.markdown("---")
        st.markdown("### Importar settings.json")
        st.caption("Lugar para subir el archivo _.json_ e importar los ajustes")

        # El rol básico no puede importar configuración para evitar cambios accidentales en entorno asistencial.
        if rol == "basico":
            st.info("La importación de settings está desactivada para el rol Básico.")
        else:
            st.info(
                "Se validará, se hará una fusión con los valores por defecto (si faltan claves) "
                "y se guardará con histórico."
            )
            up = st.file_uploader(
                "Subir settings.json",
                type=["json"],
                key="import_settings_json",
                help="Sube un settings.json. Se validará y se completarán claves faltantes con valores por defecto.",
            )

            # El guardado real ocurre solo al pulsar botón, evitando aplicar cambios por accidente al seleccionar un archivo.
            if up is not None:
                if st.button(
                    "Importar configuración",
                    key="btn_import_settings",
                    help="Importa el archivo, valida y guarda con copia en el histórico. Puede autocorregir valores inválidos.",
                ):
                    try:
                        imported = json.loads(up.getvalue().decode("utf-8"))
                        if not isinstance(imported, dict):
                            raise ValueError("El JSON importado no es un objeto (diccionario).")

                        # Se completa con defaults para evitar claves faltantes tras importar.
                        merged = _merge_defaults(imported, DEFAULT_SETTINGS)

                        # Se valida y autocorrige para asegurar que el esquema y tipos son consistentes.
                        merged, warns2 = validate_settings(merged, autocorrect=True)

                        # Guardado persistente y actualización de sesión.
                        save_settings(merged, create_history=True)
                        st.session_state["settings"] = merged

                        # Trazabilidad: se registra importación y número de avisos generados por autocorrección.
                        log_action(u.get("username"), "settings_import", {"role": rol, "warnings": len(warns2)})

                        if warns2:
                            st.warning("Importado con avisos de autocorrección.")
                            with st.expander("Ver avisos"):
                                for w in warns2:
                                    st.warning(w)

                        st.success("Configuración importada y guardada (con histórico).")
                        st.rerun()

                    except Exception as e:
                        st.error(f"No se pudo importar: {e}")

    # =========================
    # PESTAÑA: RESTAURAR (solo admin)
    # =========================
    if rol == "admin":
        with tabs[i]:
            i += 1

            # Restauración completa a defaults.
            # Se añaden confirmaciones para minimizar errores humanos en un entorno clínico real.
            st.subheader("Restaurar valores por defecto")
            st.warning("Esto sobrescribirá settings.json y perderás los cambios actuales (queda copia en el histórico).")

            c1 = st.checkbox(
                "Entiendo que se perderán los ajustes actuales",
                key="reset_c1",
                help="Confirmación 1: evita restauraciones accidentales.",
            )
            c2 = st.checkbox(
                "Confirmo que quiero restaurar a los valores por defecto",
                key="reset_c2",
                help="Confirmación 2: requiere doble validación para acciones destructivas.",
            )

            if st.button(
                "Restaurar por defecto",
                disabled=not (c1 and c2),
                key="btn_reset_settings",
                help="Restaura settings.json a la configuración base y guarda una copia del estado anterior en el histórico.",
            ):
                reset_settings()
                st.session_state["settings"] = load_settings()
                log_action(u.get("username"), "settings_reset_defaults", None)
                st.success("Restaurado a valores por defecto (con histórico).")
                st.rerun()

    # =========================
    # PESTAÑA: USUARIOS (solo admin)
    # =========================
    if rol == "admin":
        with tabs[i]:
            i += 1

            # Gestión de usuarios a nivel local (SQLite).
            # La idea es que el control de acceso funcione sin depender de servicios externos.
            st.subheader("Gestión de usuarios (control de acceso por roles)")
            st.caption("Usuarios en SQLite. Contraseñas guardadas como hash (no en claro).")

            # Tabla de usuarios existentes.
            try:
                users = list_users()
                st.dataframe(users, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"No se pudieron cargar usuarios: {e}")
                users = []

            st.markdown("---")
            st.markdown("### Crear usuario")

            # Formulario de alta: asegura que los campos se envían como un bloque coherente.
            with st.form("create_user_form"):
                new_username = st.text_input(
                    "Usuario (único)",
                    help="Identificador del usuario. Debe ser único en la base de datos.",
                )
                new_role = st.selectbox(
                    "Rol",
                    ["basico", "jefe", "admin"],
                    index=0,
                    help="Define permisos: Básico (uso), Jefe (lectura), Administrador (edición y gestión).",
                )
                new_pw1 = st.text_input(
                    "Contraseña inicial",
                    type="password",
                    help="Contraseña temporal. Se recomienda mínimo 6 caracteres.",
                )
                new_pw2 = st.text_input(
                    "Repetir contraseña",
                    type="password",
                    help="Repite la contraseña para evitar errores de escritura.",
                )
                must_change = st.checkbox(
                    "Forzar cambio de contraseña en el primer inicio de sesión",
                    value=True,
                    help="Obliga a cambiar la contraseña tras el primer inicio de sesión.",
                )
                submit = st.form_submit_button("Crear usuario")

            # Validaciones básicas antes de crear usuario.
            if submit:
                if not new_username.strip():
                    st.error("El usuario no puede estar vacío.")
                elif len(new_pw1) < 6:
                    st.error("La contraseña debe tener al menos 6 caracteres.")
                elif new_pw1 != new_pw2:
                    st.error("Las contraseñas no coinciden.")
                else:
                    try:
                        create_user(new_username.strip(), new_pw1, role=new_role, must_change_password=must_change)
                        log_action(
                            u.get("username"),
                            "user_create",
                            {"username": new_username.strip(), "role": new_role},
                        )
                        st.success("Usuario creado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo crear usuario: {e}")

            st.markdown("---")
            st.markdown("### Editar usuario existente")

            # Edición de usuarios ya creados: rol, estado activo y forzado de cambio de contraseña.
            if users:
                usernames = [uu["username"] for uu in users]
                sel = st.selectbox(
                    "Selecciona un usuario",
                    usernames,
                    index=0,
                    help="Selecciona el usuario a modificar (rol, activo, forzar cambio de contraseña, etc.).",
                )

                sel_data = next((uu for uu in users if uu["username"] == sel), None)
                if sel_data:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        role_new = st.selectbox(
                            "Rol",
                            ["basico", "jefe", "admin"],
                            index=["basico", "jefe", "admin"].index(sel_data["role"]),
                            key="edit_role",
                            help="Cambia los permisos del usuario seleccionado.",
                        )
                    with col2:
                        is_active = st.checkbox(
                            "Activo",
                            value=sel_data["is_active"],
                            key="edit_active",
                            help="Si se desactiva, el usuario no podrá iniciar sesión.",
                        )
                    with col3:
                        must_change_pw = st.checkbox(
                            "Forzar cambio de contraseña",
                            value=sel_data["must_change_password"],
                            key="edit_must_change",
                            help="Si está activo, obligará al usuario a cambiar la contraseña en el siguiente inicio de sesión.",
                        )

                    # Aplicación de cambios con registro de auditoría.
                    if st.button(
                        "Guardar cambios del usuario",
                        key="btn_save_user_changes",
                        help="Aplica cambios de rol/estado en la base de datos y registra la acción en auditoría.",
                    ):
                        try:
                            set_user_role(sel, role_new)
                            set_user_active(sel, is_active)
                            set_user_must_change_password(sel, must_change_pw)
                            log_action(
                                u.get("username"),
                                "user_update",
                                {
                                    "username": sel,
                                    "role": role_new,
                                    "is_active": is_active,
                                    "must_change_password": must_change_pw,
                                },
                            )
                            st.success("Cambios guardados.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"No se pudieron guardar cambios: {e}")

                    # Restablecimiento de contraseña por admin.
                    st.markdown("#### Restablecer / cambiar contraseña (admin)")
                    with st.form("admin_reset_pw_form"):
                        newp1 = st.text_input(
                            "Nueva contraseña",
                            type="password",
                            help="Nueva contraseña para el usuario seleccionado (administrador).",
                        )
                        newp2 = st.text_input(
                            "Repetir nueva contraseña",
                            type="password",
                            help="Repite para evitar errores.",
                        )
                        force = st.checkbox(
                            "Forzar cambio en el siguiente inicio de sesión",
                            value=True,
                            help="Si está activo, el usuario tendrá que cambiarla tras iniciar sesión.",
                        )
                        ok = st.form_submit_button("Actualizar contraseña")

                    if ok:
                        if len(newp1) < 6:
                            st.error("Mínimo 6 caracteres.")
                        elif newp1 != newp2:
                            st.error("No coinciden.")
                        else:
                            try:
                                update_user_password(sel, newp1, clear_must_change=not force)
                                if force:
                                    set_user_must_change_password(sel, True)
                                log_action(
                                    u.get("username"),
                                    "user_password_reset",
                                    {"username": sel, "force_change": force},
                                )
                                st.success("Contraseña actualizada.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"No se pudo actualizar: {e}")
            else:
                st.info("No hay usuarios aún (debería existir al menos el admin inicial).")

    # =========================
    # PESTAÑA: AUDITORÍA (solo admin)
    # =========================
    if rol == "admin":
        with tabs[i]:
            i += 1

            # Auditoría: registro de acciones relevantes para trazabilidad y control en entorno clínico.
            # Sirve también como soporte para anexos del TFG (demostración de trazabilidad).
            st.subheader("Auditoría / Trazabilidad")
            st.caption(
                "Registro de acciones relevantes: inicio de sesión, cambios de usuarios, importación/exportación, etc."
            )

            # Limita el número de entradas para mantener la interfaz ágil.
            limit = st.slider(
                "Número de registros a mostrar",
                min_value=50,
                max_value=1000,
                value=200,
                step=50,
                help="Controla cuántos eventos se cargan para la tabla de auditoría.",
            )

            try:
                logs = get_audit_log(limit=limit)
                st.dataframe(logs, use_container_width=True, hide_index=True)

                # Exportación a CSV para revisión externa o archivado.
                # Se usa separador ';' por compatibilidad habitual en entornos con Excel en configuración regional española.
                csv = io.StringIO()
                if logs:
                    keys = list(logs[0].keys())
                    csv.write(";".join(keys) + "\n")
                    for r in logs:
                        csv.write(";".join(str(r.get(k, "")) for k in keys) + "\n")

                st.download_button(
                    "Descargar auditoría (CSV)",
                    data=csv.getvalue().encode("utf-8"),
                    file_name="audit_log.csv",
                    mime="text/csv",
                    help="Exporta el registro de auditoría para revisión, trazabilidad o anexos del TFG.",
                )
            except Exception as e:
                st.error(f"No se pudo cargar auditoría: {e}")