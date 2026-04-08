# vista_historico.py

import io
from datetime import datetime
from typing import Optional, Any, Dict, Tuple

import pandas as pd
import streamlit as st
import sqlite3
import zipfile

# Imports del proyecto 
from informes import generar_informe_pdf_bytes
from discordancia import extraer_sample_ids_con_aviso, construir_aviso_rico
from stats_biomarcadores import build_stats_table_from_df

from ajustes import load_settings

from db import DB_PATH, log_action
from sync_pack import build_transfer_zip
from auth import current_user




def _safe_filename(name: str) -> str:
    """
    Devuelve un nombre de archivo “seguro” (compatible con Windows/macOS),
    sustituyendo caracteres problemáticos por guiones bajos.

    Si el nombre queda vacío, devuelve "archivo".
    """
    bad = '<>:"/\\|?*\n\r\t'
    for c in bad:
        name = name.replace(c, "_")
    return name.strip() or "archivo"


def _build_zip_name(settings: dict, meta: dict) -> str:
    """
    Construye el nombre del ZIP de traspaso usando un template configurable.

    - settings["exportacion"]["zip_nombre_template"] permite personalizar el nombre.
    - El template puede incluir: {timestamp}, {user}, {role}, {source}.
    - Asegura extensión .zip y sanea el nombre final.
    """
    exp = settings.get("exportacion", {})
    template = exp.get("zip_nombre_template", "traspaso_{timestamp}_{user}.zip")
    ts_fmt = exp.get("timestamp_format", "%Y-%m-%d_%H%M%S")
    timestamp = datetime.now().strftime(ts_fmt)

    user = (meta or {}).get("user") or "usuario"
    role = (meta or {}).get("role") or "rol"
    source = (meta or {}).get("source") or "app"

    name = template.format(timestamp=timestamp, user=user, role=role, source=source)
    if not name.lower().endswith(".zip"):
        name += ".zip"
    return _safe_filename(name)


def _hide_tech_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Oculta columnas “técnicas” para mostrar una vista más limpia al usuario.

    Heurística:
      - Columnas que suelen ser internas: *_value, prefijos mmt_/patwin_/pdf_, etc.

    Si al aplicar la heurística quedasen muy pocas columnas, se devuelve el DF
    original (para no “romper” la visualización).
    """
    tech_patterns = (
        r"_value$",
        r"^mmt_",
        r"^patwin_",
        r"^pdf_",
    )

    cols = list(df.columns)
    keep = []
    for c in cols:
        # Se usa re de forma dinámica para no añadir import global solo para esto.
        if any(__import__("re").search(p, c, flags=__import__("re").IGNORECASE) for p in tech_patterns):
            continue
        keep.append(c)

    # Si por heurística te quedas sin columnas “útiles”, no ocultes nada
    return df[keep] if len(keep) >= 5 else df


def construir_excel_concordancia_dashboard(df_lote: pd.DataFrame) -> io.BytesIO:
    """
    Genera un Excel con:
      - Hoja 1: Lote_concordancia (tabla completa, ordenada y formateada).
      - Hoja 2: Dashboard (KPIs + gráficos + tablas resumen).

    Importante:
      - Se evita escribir la hoja Dashboard con DataFrame.to_excel directamente
        para prevenir errores del tipo "Excel reparó sheet2.xml".
      - HER2/ERBB2:
          * low/zero/ultra low se interpreta como 0 (no positivo)
          * positive se interpreta como 1
      - NUEVO: bloque de estadísticas por biomarcador (TP/TN/FP/FN, %Concord,
        Kappa, McNemar) mediante build_stats_table_from_df().

    Devuelve:
      - Un BytesIO listo para descargar/guardar como .xlsx.
    """
    buffer = io.BytesIO()

    # -------------------------------------------------------------------------
    # Helpers de normalización (para concordancia rápida)
    # -------------------------------------------------------------------------
    def _norm_txt(x):
        """Normaliza texto: None -> "", minúsculas y espacios homogéneos."""
        if x is None:
            return ""
        s = str(x).strip().lower()
        return " ".join(s.split())

    def _ihq_bin_from_text(x):
        """
        Convierte un resultado IHQ de ER/PR a binario:
          - “positivo” -> 1
          - “negativo” -> 0
          - no interpretable -> None
        """
        s = _norm_txt(x)
        if s == "":
            return None
        if "pos" in s or "positivo" in s or "+" in s:
            return 1
        if "neg" in s or "negativo" in s or "−" in s:
            return 0
        return None

    def _ihq_bin_her2_from_text(x):
        """
        HER2 (IHQ/SISH) binario:
          - HER2+ / ampl / 3+ => 1
          - HER2-low / neg / 0/1/2 => 0
        """
        s = _norm_txt(x)
        if s == "":
            return None

        # Positivo claro
        if "ampl" in s or "positivo" in s or ("pos" in s and "neg" not in s) or "3+" in s or s == "3":
            return 1

        # Low/neg -> no positivo
        if "low" in s or "neg" in s or "negativo" in s:
            return 0

        # Scores típicos: 0/1/2 suelen considerarse no positivos en esta regla rápida
        for token in ["0", "0+", "1", "1+", "2", "2+"]:
            if token in s:
                return 0

        return None

    def _mmt_bin_from_status(x):
        """
        Convierte un status de MammaTyper (genérico ESR1/PGR/MKI67) a binario:
          - positive -> 1
          - negative -> 0
          - no interpretable -> None
        """
        s = _norm_txt(x)
        if s == "":
            return None
        if "pos" in s or "positive" in s:
            return 1
        if "neg" in s or "negative" in s:
            return 0
        return None

    def _mmt_bin_erbb2_from_status(x):
        """
        ERBB2_status (MMT) binario:
          - low/zero/ultra low => 0
          - positive/pos => 1
        """
        s = _norm_txt(x)
        if s == "":
            return None

        if "positive" in s or ("pos" in s and "neg" not in s):
            return 1

        if "low" in s or "zero" in s or "ultra" in s or "negative" in s or "neg" in s:
            return 0

        return None

    def _concordancia(a, b):
        """
        Devuelve una etiqueta de concordancia:
          - "OK" si coincide
          - "DISCORDANTE" si no coincide
          - "Sin dato(s)" si falta algún valor
        """
        if a is None or b is None:
            return "Sin dato(s)"
        return "OK" if int(a) == int(b) else "DISCORDANTE"

    # -------------------------------------------------------------------------
    # Copia del lote y columnas calculadas de concordancia
    # -------------------------------------------------------------------------
    df = df_lote.copy()

    # Concordancia ER (ESR1)
    df["CONC_ESR1"] = [
        _concordancia(_ihq_bin_from_text(r.get("ESR1_IHQ")), _mmt_bin_from_status(r.get("ESR1_status")))
        for _, r in df.iterrows()
    ]

    # Concordancia PR (PGR)
    df["CONC_PGR"] = [
        _concordancia(_ihq_bin_from_text(r.get("PGR_IHQ")), _mmt_bin_from_status(r.get("PGR_status")))
        for _, r in df.iterrows()
    ]

    # Concordancia HER2 (IHQ/SISH vs ERBB2_status)
    df["CONC_HER2"] = [
        _concordancia(_ihq_bin_her2_from_text(r.get("HER2_final")), _mmt_bin_erbb2_from_status(r.get("ERBB2_status")))
        for _, r in df.iterrows()
    ]

    # Concordancia Ki-67:
    # - IHQ numérico binarizado con umbral 20%
    # - Comparado contra MKI67_status (MMT)
    def _ihq_bin_ki67_20(x):
        """Binariza Ki-67 IHQ según cutoff configurable desde ajustes (default 20%)."""
        _cutoff = float(load_settings().get("clinico", {}).get("ki67_cutoff_ihq", 20.0))
        try:
            if x is None:
                return None
            if pd.isna(x):
                return None
            v = float(x)
            return 1 if v >= _cutoff else 0
        except Exception:
            return None

    df["CONC_KI67"] = [
        _concordancia(_ihq_bin_ki67_20(r.get("KI67_IHQ")), _mmt_bin_from_status(r.get("MKI67_status")))
        for _, r in df.iterrows()
    ]

    # Revisión recomendada:
    # - Si hay aviso de calidad
    # - O si hay discordancia en cualquiera de los biomarcadores
    df["REVISION_RECOMENDADA"] = (
        df.get("aviso", "").fillna("").astype(str).str.strip().ne("")
        | df["CONC_ESR1"].eq("DISCORDANTE")
        | df["CONC_PGR"].eq("DISCORDANTE")
        | df["CONC_HER2"].eq("DISCORDANTE")
        | df["CONC_KI67"].eq("DISCORDANTE")
    ).map({True: "SI", False: "NO"})

    # -------------------------------------------------------------------------
    # Orden visual de columnas (primero las relevantes, luego el resto)
    # -------------------------------------------------------------------------
    cols_preferidas = [
        "nhc", "sample_id", "ronda", "celularidad", "fecha_excel", "fecha_informe_mmt",
        "subtipo_ihq", "subtipo_mmt", "subtipo_mmt_detalle",

        "ESR1_IHQ", "ESR1_IHQ_intensidad", "ESR1_IHQ_pct",
        "ESR1_value", "ESR1_status", "ESR1_equiv",
        "ESR1_cutoff_nearest", "ESR1_delta_cutoff", "ESR1_delta_to_positive",
        "CONC_ESR1",

        "PGR_IHQ", "PGR_IHQ_intensidad", "PGR_IHQ_pct",
        "PGR_value", "PGR_status", "PGR_equiv",
        "PGR_cutoff_nearest", "PGR_delta_cutoff", "PGR_delta_to_positive",
        "CONC_PGR",

        "HER2_final", "HER2_IHQ_score", "ERBB2_IHQ_SISH", "HER2_SISH_result",
        "ERBB2_value", "ERBB2_status", "ERBB2_equiv",
        "ERBB2_cutoff_nearest", "ERBB2_delta_cutoff", "ERBB2_delta_to_positive",
        "CONC_HER2",

        "KI67_IHQ",
        "MKI67_value", "MKI67_status", "MKI67_equiv",
        "MKI67_cutoff_nearest", "MKI67_delta_cutoff", "MKI67_delta_to_positive",
        "CONC_KI67",

        "P53_IHQ_status", "P53_IHQ_pct", "CK19_IHQ_status",
        "aviso", "REVISION_RECOMENDADA",
    ]

    cols_existentes = [c for c in cols_preferidas if c in df.columns]
    cols_extra = [c for c in df.columns if c not in cols_existentes]
    df = df[cols_existentes + cols_extra]

    # -------------------------------------------------------------------------
    # Estadísticas por biomarcador (para el lote completo)
    # - Se define SIEMPRE, para evitar errores si falla el cálculo
    # -------------------------------------------------------------------------
    try:
        ki67_cutoff_lote = float(
            load_settings().get("clinico", {}).get("ki67_cutoff_ihq", 20.0)
        )
        stats_lote = build_stats_table_from_df(df, ki67_cutoff_ihq=ki67_cutoff_lote)
    except Exception as e:
        stats_lote = pd.DataFrame([{
            "Biomarcador": "ERROR",
            "N": 0,
            "TP": 0, "TN": 0, "FP": 0, "FN": 0,
            "%Concord": None,
            "Kappa": None,
            "McNemar_p": None,
            "b(IHQ+→MMT-)": 0,
            "c(IHQ-→MMT+)": 0,
            "Tendencia": f"{type(e).__name__}"
        }])

    # -------------------------------------------------------------------------
    # Escritura Excel con XlsxWriter
    # -------------------------------------------------------------------------
    with pd.ExcelWriter(
        buffer,
        engine="xlsxwriter",
        engine_kwargs={"options": {"nan_inf_to_errors": True}},
    ) as writer:

        # -----------------------------
        # Hoja 1: tabla del lote
        # -----------------------------
        sheet_lote = "Lote_concordancia"
        df.to_excel(writer, index=False, sheet_name=sheet_lote)

        wb = writer.book
        ws = writer.sheets[sheet_lote]

        # Recomendación de solo lectura al abrir en Excel (reduce ediciones accidentales)
        wb.read_only_recommended()

        # Formatos de cabecera por bloques:
        # - IHQ (verde)
        # - MMT (rojo)
        # - Concordancia (granate)
        # - Miscelánea (gris)
        fmt_head_ihq  = wb.add_format({"bold": True, "font_color": "#0B3D2E", "bg_color": "#A9D08E", "border": 1})
        fmt_head_mmt  = wb.add_format({"bold": True, "font_color": "#7A0C0C", "bg_color": "#F4B6B6", "border": 1})
        fmt_head_conc = wb.add_format({"bold": True, "font_color": "white",   "bg_color": "#9C0006", "border": 1})
        fmt_head_misc = wb.add_format({"bold": True, "font_color": "#111827", "bg_color": "#F3F4F6", "border": 1})

        # Formatos para celdas (condicionales)
        fmt_wrap = wb.add_format({"text_wrap": True, "valign": "top"})
        fmt_ok   = wb.add_format({"bg_color": "#D1FAE5"})
        fmt_bad  = wb.add_format({"bg_color": "#FECACA"})
        fmt_nc   = wb.add_format({"bg_color": "#E5E7EB"})
        fmt_si   = wb.add_format({"bg_color": "#FEF3C7"})

        # Clasificadores de columnas según origen
        def _is_ihq(c: str) -> bool:
            c_low = str(c).lower()
            return (
                "_ihq" in c_low
                or c.startswith("HER2_")
                or c.startswith("P53_")
                or c.startswith("CK19_")
                or c == "KI67_IHQ"
                or c == "subtipo_ihq"
                or c in {"nhc", "sample_id", "ronda", "celularidad", "fecha_excel", "firmantes_diag"}
            )

        def _is_mmt(c: str) -> bool:
            c_low = str(c).lower()

            if "_ihq" in c_low:
                return False
            return (
                c in {"subtipo_mmt", "subtipo_mmt_detalle", "fecha_informe_mmt"}
                or c_low.endswith("_value")
                or c_low.endswith("_status")
                or c_low.endswith("_equiv")
                or c_low.endswith("_cutoff_nearest")
                or c_low.endswith("_delta_cutoff")
                or c_low.endswith("_delta_to_positive")
            )

        def _is_concord(c: str) -> bool:
            return str(c).startswith("CONC_") or c in {"REVISION_RECOMENDADA"}

        # Pintar cabecera según tipo de columna
        for j, col in enumerate(df.columns):
            if _is_concord(col):
                ws.write(0, j, col, fmt_head_conc)
            elif _is_ihq(col) and not _is_mmt(col):
                ws.write(0, j, col, fmt_head_ihq)
            elif _is_mmt(col) and not _is_ihq(col):
                ws.write(0, j, col, fmt_head_mmt)
            else:
                ws.write(0, j, col, fmt_head_misc)

        # Ajuste general de anchos
        ws.set_column(0, len(df.columns) - 1, 14)

        def set_w(col_name, w):
            """Helper para ajustar ancho solo si la columna existe."""
            if col_name in df.columns:
                i = df.columns.get_loc(col_name)
                ws.set_column(i, i, w)

        # Ajustes puntuales para columnas “clave”
        set_w("nhc", 10)
        set_w("sample_id", 12)
        set_w("subtipo_ihq", 16)
        set_w("subtipo_mmt", 16)
        set_w("subtipo_mmt_detalle", 22)
        set_w("aviso", 55)
        set_w("REVISION_RECOMENDADA", 18)

        # Congelar fila de cabecera y primeras columnas (más cómodo para revisar)
        ws.freeze_panes(1, 2)

        # Envolver texto en la columna aviso, porque suele ser larga
        if "aviso" in df.columns:
            aviso_idx = df.columns.get_loc("aviso")
            ws.set_column(aviso_idx, aviso_idx, 55, fmt_wrap)

        # Filtro automático en toda la tabla
        ws.autofilter(0, 0, len(df), len(df.columns) - 1)

        # Formato condicional para columnas de concordancia
        for c in ["CONC_ESR1", "CONC_PGR", "CONC_HER2", "CONC_KI67"]:
            if c in df.columns:
                idx = df.columns.get_loc(c)
                ws.conditional_format(1, idx, len(df), idx,
                                      {"type": "text", "criteria": "containing", "value": "OK", "format": fmt_ok})
                ws.conditional_format(1, idx, len(df), idx,
                                      {"type": "text", "criteria": "containing", "value": "DISCORDANTE", "format": fmt_bad})
                ws.conditional_format(1, idx, len(df), idx,
                                      {"type": "text", "criteria": "containing", "value": "Sin dato(s)", "format": fmt_nc})

        # Resaltar revisión recomendada
        if "REVISION_RECOMENDADA" in df.columns:
            idx = df.columns.get_loc("REVISION_RECOMENDADA")
            ws.conditional_format(1, idx, len(df), idx,
                                  {"type": "text", "criteria": "containing", "value": "SI", "format": fmt_si})

        # -----------------------------
        # Hoja 2: dashboard
        # -----------------------------
        dash = "Dashboard"
        ws2 = wb.add_worksheet(dash)
        writer.sheets[dash] = ws2

        # Formatos específicos del dashboard
        fmt_title = wb.add_format({"bold": True, "font_size": 12})
        fmt_sub = wb.add_format({"bold": True, "font_size": 10})
        fmt_muted = wb.add_format({"font_color": "#6B7280"})
        fmt_kpi = wb.add_format({"bold": True, "font_size": 16})
        fmt_head = wb.add_format({"bold": True, "bg_color": "#F3F4F6", "border": 1})
        fmt_header = fmt_head  # alias (para el bloque de estadísticas)

        # KPIs principales del lote
        n = len(df)
        n_rev = int((df["REVISION_RECOMENDADA"] == "SI").sum()) if "REVISION_RECOMENDADA" in df.columns else 0

        # Conteo total de discordancias (suma por biomarcador)
        n_disc = 0
        for c in ["CONC_ESR1", "CONC_PGR", "CONC_HER2", "CONC_KI67"]:
            if c in df.columns:
                n_disc += int((df[c] == "DISCORDANTE").sum())

        ws2.write(0, 0, "Dashboard concordancia IHQ vs MammaTyper", fmt_title)
        ws2.write(1, 0, "Resumen del lote", fmt_muted)

        ws2.write(3, 0, "Muestras", fmt_sub); ws2.write(3, 1, n, fmt_kpi)
        ws2.write(4, 0, "Revisión recomendada", fmt_sub); ws2.write(4, 1, n_rev, fmt_kpi)
        ws2.write(5, 0, "Discordancias (ER/PR/HER2/Ki-67)", fmt_sub); ws2.write(5, 1, n_disc, fmt_kpi)

        # ---------------------------------------------------------
        # Tabla de concordancia por gen + gráfico
        # ---------------------------------------------------------
        base_r = 7
        ws2.write(base_r, 0, "Concordancia por gen", fmt_sub)

        stats = []
        for g, colc in [
            ("ER (ESR1)", "CONC_ESR1"),
            ("PR (PGR)", "CONC_PGR"),
            ("HER2 (ERBB2)", "CONC_HER2"),
            ("Ki-67 (MKI67)", "CONC_KI67"),
        ]:
            if colc in df.columns:
                ok = int((df[colc] == "OK").sum())
                bad = int((df[colc] == "DISCORDANTE").sum())
                nc = int((df[colc] == "Sin dato(s)").sum())
            else:
                ok = bad = nc = 0
            stats.append((g, ok, bad, nc))

        # Cabecera de la tabla
        ws2.write(base_r + 2, 0, "Gen", fmt_head)
        ws2.write(base_r + 2, 1, "OK", fmt_head)
        ws2.write(base_r + 2, 2, "DISCORDANTE", fmt_head)
        ws2.write(base_r + 2, 3, "Sin dato(s)", fmt_head)

        # Filas
        for i, (g, ok, bad, nc) in enumerate(stats, start=base_r + 3):
            ws2.write(i, 0, g)
            ws2.write(i, 1, ok)
            ws2.write(i, 2, bad)
            ws2.write(i, 3, nc)

        # Rango dinámico del gráfico en función del nº de genes
        last_row = base_r + 3 + (len(stats) - 1)

        chart = wb.add_chart({"type": "column"})
        chart.add_series({
            "name": "Discordante",
            "categories": [dash, base_r + 3, 0, last_row, 0],
            "values":     [dash, base_r + 3, 2, last_row, 2],
        })
        chart.set_title({"name": "Discordancias por gen"})
        chart.set_legend({"none": True})
        ws2.insert_chart(base_r - 3, 5, chart, {"x_scale": 1.1, "y_scale": 1.0})

        # ---------------------------------------------------------
        # Proximidad a cutoffs (Δabs) + gráfico apilado
        # ---------------------------------------------------------
        cutoff_rows = []
        for gene in ["ERBB2", "ESR1", "PGR", "MKI67"]:
            col = f"{gene}_delta_cutoff"
            if col in df.columns:
                s = pd.to_numeric(df[col], errors="coerce")
                crit = int((s <= 0.20).sum())
                near = int(((s > 0.20) & (s <= 0.50)).sum())
                far = int((s > 0.50).sum())
            else:
                crit = near = far = 0
            cutoff_rows.append((gene, crit, near, far))

        r2 = base_r + 10
        ws2.write(r2, 0, "Proximidad a cutoffs (Δabs)", fmt_sub)
        ws2.write(r2 + 1, 0, "Criterios: crítico ≤0.20 Ct | cercano ≤0.50 Ct", fmt_muted)

        ws2.write(r2 + 3, 0, "Gen", fmt_head)
        ws2.write(r2 + 3, 1, "Crítico (≤0.20)", fmt_head)
        ws2.write(r2 + 3, 2, "Cercano (0.20–0.50)", fmt_head)
        ws2.write(r2 + 3, 3, "Lejos (>0.50)", fmt_head)

        for i, (gene, crit, near, far) in enumerate(cutoff_rows, start=r2 + 4):
            ws2.write(i, 0, gene)
            ws2.write(i, 1, crit)
            ws2.write(i, 2, near)
            ws2.write(i, 3, far)

        chart2 = wb.add_chart({"type": "column", "subtype": "stacked"})
        chart2.add_series({"name": "Crítico", "categories": [dash, r2 + 4, 0, r2 + 7, 0], "values": [dash, r2 + 4, 1, r2 + 7, 1]})
        chart2.add_series({"name": "Cercano", "categories": [dash, r2 + 4, 0, r2 + 7, 0], "values": [dash, r2 + 4, 2, r2 + 7, 2]})
        chart2.add_series({"name": "Lejos",   "categories": [dash, r2 + 4, 0, r2 + 7, 0], "values": [dash, r2 + 4, 3, r2 + 7, 3]})
        chart2.set_title({"name": "Cercanía a cutoffs por gen"})
        chart2.set_legend({"position": "bottom"})
        ws2.insert_chart(r2 + 3, 5, chart2, {"x_scale": 1.1, "y_scale": 1.0})

        # ---------------------------------------------------------
        # Top revisión (muestras con revisión recomendada)
        # ---------------------------------------------------------
        top_r = r2 + 20
        ws2.write(top_r, 0, "Top revisión (primeras 15)", fmt_sub)

        if "REVISION_RECOMENDADA" in df.columns:
            top_rev = df[df["REVISION_RECOMENDADA"] == "SI"].copy()
        else:
            top_rev = df.iloc[0:0].copy()

        # Ordena por “más cerca de algún cutoff” (mínimo delta_cutoff por fila)
        delta_cols = [c for c in df.columns if c.endswith("_delta_cutoff")]
        if not top_rev.empty and delta_cols:
            m = top_rev[delta_cols].apply(pd.to_numeric, errors="coerce").min(axis=1)
            top_rev["_min_delta"] = m
            top_rev = top_rev.sort_values("_min_delta", ascending=True).drop(columns=["_min_delta"])

        top_rev = top_rev.head(15)

        cols_top = [c for c in [
            "sample_id", "nhc",
            "CONC_ESR1", "CONC_PGR", "CONC_HER2", "CONC_KI67",
            "ESR1_IHQ", "ESR1_status", "ESR1_delta_cutoff",
            "PGR_IHQ", "PGR_status", "PGR_delta_cutoff",
            "HER2_final", "ERBB2_status", "ERBB2_delta_cutoff",
            "KI67_IHQ", "MKI67_status", "MKI67_delta_cutoff",
            "aviso"
        ] if c in df.columns]

        if top_rev.empty:
            ws2.write(top_r + 1, 0, "No hay muestras con revisión recomendada (SI).", fmt_muted)
        else:
            # Cabecera
            for j, col in enumerate(cols_top):
                ws2.write(top_r + 1, j, col, fmt_head)

            # Filas
            for i, (_, row) in enumerate(top_rev[cols_top].iterrows(), start=top_r + 2):
                for j, col in enumerate(cols_top):
                    ws2.write(i, j, row.get(col, ""))

        # Ajustes de anchos del dashboard
        ws2.set_column(0, 0, 18)
        ws2.set_column(1, 3, 16)
        ws2.set_column(4, 8, 18)
        ws2.set_column(9, 14, 20)
        if "aviso" in cols_top:
            ws2.set_column(cols_top.index("aviso"), cols_top.index("aviso"), 55)

        # ---------------------------------------------------------
        # Estadísticas por biomarcador (lote)
        # ---------------------------------------------------------
        row0 = top_r + 20
        ws2.write(row0, 0, "Estadisticas por biomarcador (lote)", fmt_title)

        # Nota metodológica
        fmt_nota = wb.add_format({"italic": True, "font_color": "#555555", "font_size": 9})
        ws2.write(
            row0 + 1, 0,
            "Calculos equivalentes a psych::cohen.kappa(), epiR::epi.tests() y mcnemar.test() en R. "
            "Cutoff Ki-67 IHQ: 20%. IHQ como referencia, MammaTyper como test.",
            fmt_nota,
        )
        ws2.merge_range(row0 + 1, 0, row0 + 1, 10, 
            "Calculos equivalentes a psych::cohen.kappa(), epiR::epi.tests() y mcnemar.test() en R. "
            "Cutoff Ki-67 IHQ: 20%. IHQ como referencia, MammaTyper como test.",
            fmt_nota,
        )

        # Cabecera
        for j, col in enumerate(stats_lote.columns):
            ws2.write(row0 + 2, j, col, fmt_header)

        # Filas con color condicional en Aviso_N
        fmt_aviso = wb.add_format({"bg_color": "#FFF3CD", "font_size": 9})
        fmt_normal = wb.add_format({"font_size": 10})

        for i, (_, r) in enumerate(stats_lote.iterrows(), start=0):
            for j, col in enumerate(stats_lote.columns):
                val = r[col]
                # Convertir NaN a cadena vacía para evitar errores de escritura
                if isinstance(val, float) and pd.isna(val):
                    val = ""
                fmt_celda = fmt_aviso if (col == "Aviso_N" and val != "") else fmt_normal
                ws2.write(row0 + 3 + i, j, val, fmt_celda)

        # Anchos de columna adaptados a los nuevos campos
        ws2.set_column(0, 0, 16)   # Biomarcador
        ws2.set_column(1, 5, 8)    # N, TP, TN, FP, FN
        ws2.set_column(6, 6, 12)   # %Concord
        ws2.set_column(7, 9, 12)   # Kappa, IC_inf, IC_sup
        ws2.set_column(10, 10, 12) # McNemar_p
        ws2.set_column(11, 14, 12) # Sens, Espec, VPP, VPN
        ws2.set_column(15, 15, 14) # OR_diagnostico
        ws2.set_column(16, 17, 8)  # b, c
        ws2.set_column(18, 18, 16) # Tendencia
        ws2.set_column(19, 19, 45) # Aviso_N

    buffer.seek(0)
    return buffer


def render_lote_coloreado(df_lote: pd.DataFrame) -> None:
    """
    Renderiza el lote en Streamlit con un estilo simple:
      - Columnas IHQ en verde
      - Columnas MMT en rojo
      - Resto sin color

    Además, fuerza columnas de texto a dtype "string" para que Streamlit aplique
    estilos también en celdas de texto (no solo numéricas).
    """
    if df_lote is None or df_lote.empty:
        st.info("El lote reciente no contiene muestras combinadas.")
        return

    df = df_lote.copy()

    # Forzar columnas de texto a dtype "string" para que Streamlit aplique estilos también a texto
    for c in df.columns:
        if df[c].dtype == "object":
            df[c] = df[c].astype("string")

    BG_IHQ = "#E2F0D9"
    BG_MMT = "#F8D7DA"
    BG_NEU = ""  # sin color

    def _is_ihq(c: str) -> bool:
        """Heurística para identificar columnas que vienen de IHQ."""
        c_low = c.lower()
        return (
            "_ihq" in c_low
            or c.startswith("HER2_")
            or c.startswith("P53_")
            or c.startswith("CK19_")
            or c == "KI67_IHQ"
            or c == "subtipo_ihq"
            or c in {"nhc", "sample_id", "ronda", "celularidad", "fecha_excel", "firmantes_diag"}
        )

    def _is_mmt(c: str) -> bool:
        """Heurística para identificar columnas que vienen de MammaTyper/MMT."""
        c_low = c.lower()


        if "_ihq" in c_low:
            return False

        return (
            c in {"subtipo_mmt", "subtipo_mmt_detalle", "fecha_informe_mmt"}
            or c_low.endswith("_value")
            or c_low.endswith("_status")
            or c_low.endswith("_equiv")
            or c_low.endswith("_cutoff_nearest")
            or c_low.endswith("_delta_cutoff")
            or c_low.endswith("_delta_to_positive")
        )

    cols = list(df.columns)
    cols_ihq = [c for c in cols if _is_ihq(c) and not _is_mmt(c)]
    cols_mmt = [c for c in cols if _is_mmt(c) and not _is_ihq(c)]
    cols_neu = [c for c in cols if c not in set(cols_ihq + cols_mmt)]

    def _style_by_origin(_df: pd.DataFrame) -> pd.DataFrame:
        """
        Devuelve una matriz de estilos (mismo shape que el DF) con el color de fondo
        según el origen de cada columna.
        """
        styles = pd.DataFrame("", index=_df.index, columns=_df.columns)
        for c in cols_ihq:
            styles[c] = f"background-color: {BG_IHQ};"
        for c in cols_mmt:
            styles[c] = f"background-color: {BG_MMT};"
        for c in cols_neu:
            styles[c] = BG_NEU
        return styles

    styler = (
        df.style
        .apply(_style_by_origin, axis=None)
        .set_table_styles([{"selector": "th", "props": [("font-weight", "700")]}], overwrite=False)
    )

    st.dataframe(styler, use_container_width=True)
def mostrar_paso_3(ir_a_paso_callback):
    """
    Paso 3:
      - Mostrar un resumen del último lote procesado.
      - Mostrar el lote cruzado (muestras combinadas Excel + PDF).
      - Permitir descargas en Excel:
          * lote actual (técnico)
          * excel de concordancia + dashboard
      - Permitir descargas en PDF:
          * ZIP con un PDF por muestra
          * PDF individual por muestra
      - Exportar un paquete ZIP para sincronizar con el equipo principal.
    """
    st.header("Paso 3 · Resultados del cruce y exportación")
    st.caption(
        "Aquí se muestran y descargan las muestras cruzadas. Las muestras **no cruzadas** se guardan en "
        "**Bases no cruzadas**; las que se muestran aquí se guardan en **Bases cruzadas**. "
        "La consulta y descarga de bases de datos está en los apartados correspondientes."
    )

    # ---------------------------------------------------------------------
    # Recuperar datos del paso 2 (último lote y su resumen) desde session_state
    # ---------------------------------------------------------------------
    resumen = st.session_state.get("ultimo_resumen")
    ultimo_lote = st.session_state.get("ultimo_lote")

    # Si no hay datos en memoria, guiamos al usuario para volver al Paso 2
    if resumen is None or ultimo_lote is None:
        st.warning(
            "No hay información de un lote reciente en memoria. "
            "Vuelve al Paso 2 y ejecuta el procesamiento."
        )
        st.markdown("---")
        if st.button("Volver al paso 2"):
            ir_a_paso_callback(2)
        return

    # Preparamos el DataFrame del lote, que se reutiliza en varios bloques
    df_lote = pd.DataFrame(ultimo_lote)

    # Cargamos settings (se usa para ocultar columnas y configurar avisos/exportación)
    settings = load_settings()

    # ---------------------------------------------------------------------
    # Ocultar columnas técnicas si la app lo indica en ajustes
    # ---------------------------------------------------------------------
    if not settings.get("app", {}).get("mostrar_columnas_tecnicas", True):
        try:
            df_lote = _hide_tech_columns(df_lote)
        except Exception:
            # Si falla la heurística, no bloqueamos el paso 3
            pass

    # Listados de columnas por origen (PDF/MMT vs Excel/IHQ).
    # Se usan principalmente para colorear cabeceras en el Excel del lote.
    columnas_pdf = [
        "subtipo_mmt",
        "subtipo_mmt_detalle",
        "fecha_informe_mmt",
        "ERBB2_value",
        "ERBB2_status",
        "ESR1_value",
        "ESR1_status",
        "PGR_value",
        "PGR_status",
        "MKI67_value",
        "MKI67_status",
    ]

    columnas_excel = [
        "nhc",
        "sample_id",
        "ronda",
        "celularidad",
        "subtipo_ihq",
        "ERBB2_IHQ_SISH",
        "HER2_SISH_result",
        "HER2_final",
        "HER2_IHQ_score",
        "ESR1_IHQ",
        "ESR1_IHQ_intensidad",
        "PGR_IHQ",
        "PGR_IHQ_intensidad",
        "KI67_IHQ",
        "P53_IHQ_status",
        "P53_IHQ_pct",
        "CK19_IHQ_status",
        "aviso",
        "aviso_nivel",
        "aviso_tipos",
    ]

    # =========================================================
    # NUEVO: generar columnas extra de avisos PARA EXCEL
    #   - No se modifica "aviso" para no romper dependencias
    #   - Se añaden: aviso_nivel y aviso_tipos
    # =========================================================
    def _aviso_meta_from_text(aviso_txt: Any) -> tuple[str, str]:
        """
        Devuelve (nivel, tipos) a partir del texto de aviso.

        Reglas:
          - nivel: "WARNING" si hay aviso (requisito actual)
          - tipos: etiquetas separadas por ';' para filtrar en Excel
        """
        if aviso_txt is None:
            return "", ""
        t = str(aviso_txt).strip()
        if t == "":
            return "", ""

        low = t.lower()
        tipos = set()

        # Discordancias
        if "discordancia er" in low:
            tipos.add("DISC_ER")
        if "discordancia pr" in low:
            tipos.add("DISC_PR")
        if "discordancia her2" in low:
            tipos.add("DISC_HER2")
        if "posible discordancia proliferación" in low or "posible discordancia proliferacion" in low:
            tipos.add("DISC_KI67")

        # Low-positive IHQ
        if "er bajo por ihq" in low:
            tipos.add("ER_LOW")
        if "pr bajo por ihq" in low:
            tipos.add("PR_LOW")

        # HER2 completitud / HER2-low
        if "her2-low" in low:
            tipos.add("HER2_LOW")
        if "her2 ihq 2+" in low and "sin sish" in low:
            tipos.add("HER2_2P_SIN_SISH")
        if "her2 ihq 3+" in low and "sin sish" in low:
            tipos.add("HER2_3P_SIN_SISH")

        # Cutoffs
        if "mmt muy cercano a cutoff" in low:
            tipos.add("CUTOFF_CRITICO")
        if "mmt cercano a cutoff" in low:
            tipos.add("CUTOFF_CERCANO")

        # Incompletos
        if "datos incompletos" in low:
            tipos.add("INCOMPLETO")

        nivel = "WARNING"
        tipos_str = ";".join(sorted(tipos))
        return nivel, tipos_str

    # Relleno de columnas derivadas a partir de "aviso"
    if not df_lote.empty:
        if "aviso" in df_lote.columns:
            metas = df_lote["aviso"].apply(_aviso_meta_from_text)
            df_lote["aviso_nivel"] = metas.apply(lambda x: x[0])
            df_lote["aviso_tipos"] = metas.apply(lambda x: x[1])
        else:
            df_lote["aviso_nivel"] = ""
            df_lote["aviso_tipos"] = ""

    # ==================================================
    # BLOQUE 1 · RESUMEN Y AVISOS (de un vistazo)
    # ==================================================
    st.subheader("1) Resumen del último procesamiento")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.metric("Registros en Excel (lote)", int(resumen.get("n_excel", 0)))
    with col_b:
        st.metric("Registros en PDF (lote)", int(resumen.get("n_pdf", 0)))
    with col_c:
        st.metric("Muestras combinadas guardadas", int(resumen.get("n_procesados", 0)))

    # ==================================================
    # Avisos clínicos (configurables desde ajustes)
    # ==================================================
    settings = load_settings()
    cfg_avisos = (settings.get("clinico", {}).get("avisos", {}) or {})

    activar = bool(cfg_avisos.get("activar", True))
    incluir_en_app = bool(cfg_avisos.get("incluir_en_app", True))
    nivel_default = str(cfg_avisos.get("nivel_por_defecto", "WARNING")).upper()
    texto_disclaimer = str(cfg_avisos.get("texto_disclaimer", "")).strip()

    # Título opcional para el bloque de avisos
    texto_cabecera_app = str(cfg_avisos.get("texto_cabecera_app", "Avisos automáticos del lote")).strip()

    # ---------------------------------------------------------------------
    # Helpers locales para ordenar y presentar los avisos de forma consistente
    # ---------------------------------------------------------------------
    def _norm_line(s: str) -> str:
        """Normaliza una línea de aviso (quita viñetas y espacios)."""
        s = (s or "").strip()
        if s.startswith("•"):
            s = s[1:].strip()
        return s

    def _is_discordancia(line: str) -> bool:
        return line.lower().startswith("discordancia")

    def _is_posible_discordancia(line: str) -> bool:
        return line.lower().startswith("posible discordancia")

    def _is_her2_completitud(line: str) -> bool:
        t = line.lower()
        return t.startswith("her2 ihq 2+") or t.startswith("her2 ihq 3+") or t.startswith("her2-low")

    def _is_cutoff_critico(line: str) -> bool:
        t = line.lower()
        return "muy cercano a cutoff" in t and "crítico" in t

    def _is_cutoff_cercano(line: str) -> bool:
        t = line.lower()
        return ("mmt cercano a cutoff" in t) and ("crítico" not in t)

    def _is_incompleto(line: str) -> bool:
        return line.lower().startswith("datos incompletos")

    def _chips_from_lines(lines: list[str]) -> list[str]:
        """
        Genera “chips” de resumen para cada muestra a partir del texto del aviso.
        Sirven para ver rápidamente el tipo de problema sin leer todo el detalle.
        """
        chips = []
        t = " ".join(lines).lower()

        if "discordancia er" in t:
            chips.append("ER discordante")
        if "discordancia pr" in t:
            chips.append("PR discordante")
        if "discordancia her2" in t:
            chips.append("HER2 discordante")
        if "posible discordancia proliferación" in t:
            chips.append("Ki-67 discordante")

        if "er bajo por ihq" in t:
            chips.append("ER low")
        if "pr bajo por ihq" in t:
            chips.append("PR low")

        if "her2 ihq 2+ (equívoco)" in t and "sin sish" in t:
            chips.append("HER2 2+ sin SISH")
        if "her2 ihq 3+ sin sish" in t:
            chips.append("HER2 3+ sin SISH")
        if "her2-low" in t:
            chips.append("HER2-low")

        if any(_is_cutoff_critico(x) for x in lines):
            chips.append("Cutoff CRÍTICO")
        elif any(_is_cutoff_cercano(x) for x in lines):
            chips.append("Cutoff cercano")

        if any(_is_incompleto(x) for x in lines):
            chips.append("Datos incompletos")

        # Evitar duplicados preservando orden
        out = []
        for c in chips:
            if c not in out:
                out.append(c)
        return out

    def _truncate_ids(ids: list[str], max_show: int = 10) -> str:
        """Recorta la lista de IDs para que el encabezado no sea interminable."""
        if len(ids) <= max_show:
            return ", ".join(ids)
        head = ", ".join(ids[:max_show])
        return f"{head} … (+{len(ids)-max_show} más)"

    # ---------------------------------------------------------------------
    # Construcción del listado de avisos (por muestra) y renderizado en la app
    # ---------------------------------------------------------------------
    if activar and incluir_en_app:
        avisos_items = []
        for m in (ultimo_lote or []):
            # construir_aviso_rico() genera el texto final a mostrar por muestra
            aviso_txt = construir_aviso_rico(m)
            if aviso_txt:
                avisos_items.append((str(m.get("sample_id", "—")), aviso_txt))

        if avisos_items:
            st.markdown(f"#### {texto_cabecera_app}")

            n = len(avisos_items)
            ids = [sid for sid, _ in avisos_items]
            ids_str = _truncate_ids(ids, max_show=12)
            header = f"Revisión recomendada: {n} muestra(s) · {ids_str}"

            # Nivel general del aviso (según settings)
            if nivel_default == "INFO":
                st.info(header)
            elif nivel_default in {"CRITICO", "CRÍTICO", "ERROR"}:
                st.error(header)
            else:
                st.warning(header)

            if texto_disclaimer:
                st.caption(texto_disclaimer)

            # -------------------------------------------------------------
            # Detalle por muestra (expander con criterios + avisos ordenados)
            # -------------------------------------------------------------
            with st.expander("Ver motivos de avisos por muestra", expanded=False):
                # Bloque informativo con “criterios de clasificación” (tooltip HTML/CSS).
                # Se muestra como ayuda rápida para interpretar los avisos.
                st.markdown(
                    """
                    <style>
                    .tooltip-container {
                        position: relative;
                        display: inline-block;
                        cursor: help;
                    }

                    .tooltip-icon {
                        display: inline-flex;
                        align-items: center;
                        justify-content: center;
                        width: 22px;
                        height: 22px;
                        border: 1px solid #c9c9c9;
                        border-radius: 999px;
                        font-weight: 600;
                        font-size: 13px;
                        color: #444;
                        background: #ffffff;
                    }

                    .tooltip-text {
                        visibility: hidden;
                        width: 420px;
                        background-color: #ffffff;
                        color: #333;
                        text-align: left;
                        border-radius: 8px;
                        padding: 14px;
                        border: 1px solid #e0e0e0;
                        box-shadow: 0px 4px 12px rgba(0,0,0,0.15);
                        position: absolute;
                        z-index: 999;
                        top: 30px;
                        left: -200px;
                        font-size: 14px;
                        line-height: 1.5;
                    }

                    .tooltip-container:hover .tooltip-text {
                        visibility: visible;
                    }
                    </style>

                    <div style="display:flex; align-items:center; gap:10px;">
                        <h4 style="margin:0;">Criterios de clasificación</h4>
                        <div class="tooltip-container">
                            <div class="tooltip-icon">i</div>
                            <div class="tooltip-text">
                                <strong>Interpretación de avisos automáticos</strong><br><br>
                                • Discordancias: diferencias entre IHQ y MammaTyper.<br>
                                • ER/PR low (IHQ): expresión por debajo del umbral configurado en Ajustes.<br>
                                • HER2-low: IHQ 1+ o 2+ sin amplificación.<br>
                                • HER2 2+/3+ sin SISH: pendiente de confirmación.<br>
                                • MMT cercano a cutoff: ΔCt ≤ 0.50.<br>
                                • MMT muy cercano (crítico): zona limítrofe estrecha.<br>
                                • Datos incompletos: falta información necesaria.<br><br>
                                Avisos automáticos. No sustituyen valoración clínica.
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                st.markdown("---")

                # Detalle por muestra, ordenando los motivos por “prioridad clínica”
                for sid, aviso_txt in avisos_items:
                    raw_lines = [ln for ln in (aviso_txt or "").split("\n") if (ln or "").strip()]
                    lines = [_norm_line(ln) for ln in raw_lines if _norm_line(ln)]

                    # Chips resumen (etiquetas rápidas)
                    chips = _chips_from_lines(lines)
                    chips_md = " ".join([f"`{c}`" for c in chips])

                    st.markdown(f"**Nº Biopsia {sid}** {chips_md}".strip())

                    # Agrupar por categorías, para que lo importante quede arriba
                    grp_discord = [l for l in lines if _is_discordancia(l)]
                    grp_posible = [l for l in lines if _is_posible_discordancia(l)]
                    grp_her2comp = [l for l in lines if _is_her2_completitud(l)]
                    grp_cut_crit = [l for l in lines if _is_cutoff_critico(l)]
                    grp_cut_near = [l for l in lines if _is_cutoff_cercano(l)]
                    grp_incomp = [l for l in lines if _is_incompleto(l)]

                    usados = set(grp_discord + grp_posible + grp_her2comp + grp_cut_crit + grp_cut_near + grp_incomp)
                    grp_otros = [l for l in lines if l not in usados]

                    # Render por grupos
                    for l in grp_discord:
                        st.write("• " + l)

                    for l in grp_posible:
                        st.write("• " + l)

                    for l in grp_her2comp:
                        st.write("• " + l)

                    for l in grp_otros:
                        st.write("• " + l)

                    # Cutoffs: se resaltan con componentes visuales (sin mezclar con viñetas)
                    for l in grp_cut_crit:
                        st.warning(l)

                    for l in grp_cut_near:
                        st.info(l)

                    for l in grp_incomp:
                        st.write("• " + l)

                    st.markdown("---")

    # ---------------------------------------------------------------------
    # Muestras no cruzadas: lo que está en un archivo pero no en el otro
    # ---------------------------------------------------------------------
    sin_match_pdf = resumen.get("sin_match_pdf") or resumen.get("sin_match") or []
    sin_match_excel = resumen.get("sin_match_excel") or []

    hay_no_cruzadas = bool(sin_match_pdf or sin_match_excel)

    titulo_expander = "Ver detalles de muestras no cruzadas"
    st.caption('Se actualiza automáticamente: si indica "NINGUNA EN ESTE LOTE" no es necesario comprobar.')
    if not hay_no_cruzadas:
        titulo_expander += " - NINGUNA EN ESTE LOTE"

    with st.expander(titulo_expander, expanded=False):
        st.markdown(
            "Aquí aparecen muestras que están en un archivo pero **no** en el otro.\n\n"
            "- **PDF sin Excel**: aparece en el PDF pero no en el Excel.\n"
            "- **Excel sin PDF**: aparece en el Excel pero no en el PDF."
        )

        if sin_match_pdf:
            st.write(" **PDF sin pareja en Excel**: " + ", ".join(str(x) for x in sin_match_pdf))
        else:
            st.info("No hay casos de PDF sin pareja en Excel en este lote.")

        if sin_match_excel:
            st.write(" **Excel sin pareja en PDF**: " + ", ".join(str(x) for x in sin_match_excel))
        else:
            st.info("No hay casos de Excel sin pareja en PDF en este lote.")

    st.markdown("---")

    # ==================================================
    # BLOQUE 2 · TABLA DEL LOTE
    # ==================================================
    st.subheader("2) Lote procesado (Excel + PDF combinados)")
    st.write("Las celdas rojas corresponden a información extraída de MMT (PDF) y las verdes a IHQ (Excel).")

    if df_lote.empty:
        st.info("El lote reciente no contiene muestras combinadas.")
    else:
        render_lote_coloreado(df_lote)

    st.markdown("---")

    # ==================================================
    # BLOQUE 3 · DESCARGAS EXCEL
    # ==================================================
    st.subheader("3) Descargas en Excel")
    st.caption("Las descargas en Excel están enfocadas en este lote procesado.")

    col_left, col_right = st.columns(2)

    # ---------------------------------------------------------------------
    # Columna izquierda: Excel técnico del lote (tabla plana + cabeceras por origen)
    # ---------------------------------------------------------------------
    with col_left:
        st.markdown("#### Archivo técnico (datos estructurados del lote)")

        if df_lote.empty:
            st.info("No hay lote reciente para descargar.")
        else:
            buffer_lote = io.BytesIO()
            with pd.ExcelWriter(buffer_lote, engine="xlsxwriter") as writer:
                sheet_name = "Lote"
                df_lote.to_excel(writer, index=False, sheet_name=sheet_name)

                workbook = writer.book
                worksheet = writer.sheets[sheet_name]

                # Recomendación de solo lectura al abrir
                workbook.read_only_recommended()

                # Formatos de cabecera (azul para PDF/MMT, amarillo para Excel/IHQ)
                formato_pdf = workbook.add_format({"bold": True, "bg_color": "#9DC3E6"})
                formato_excel = workbook.add_format({"bold": True, "bg_color": "#FFF2CC"})

                col_indices = {col: i for i, col in enumerate(df_lote.columns)}
                row_header = 0

                # Pintar cabeceras por origen (si la columna existe)
                for col in columnas_pdf:
                    idx = col_indices.get(col)
                    if idx is not None:
                        worksheet.write(row_header, idx, col, formato_pdf)

                for col in columnas_excel:
                    idx = col_indices.get(col)
                    if idx is not None:
                        worksheet.write(row_header, idx, col, formato_excel)

            buffer_lote.seek(0)

            st.download_button(
                label="Descargar lote actual en Excel",
                data=buffer_lote,
                file_name="lote_mammatypper_ultimo.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            st.caption("Incluye únicamente las muestras combinadas de este lote.")

    # ---------------------------------------------------------------------
    # Columna derecha: Excel de concordancia + dashboard (más “clínico”)
    # ---------------------------------------------------------------------
    with col_right:
        st.markdown("#### Informe de concordancia y análisis clínico")

        # Se calcula una sola vez y se guarda en session_state para reutilizarlo
        # en el bloque ZIP (si incluir_excel_resumen_en_zip está activo).
        # Así se evita generarlo dos veces en el mismo render.
        if "buf_concordancia" not in st.session_state or \
                st.session_state.get("buf_concordancia_lote_id") != id(ultimo_lote):
            st.session_state["buf_concordancia"] = construir_excel_concordancia_dashboard(df_lote)
            st.session_state["buf_concordancia_lote_id"] = id(ultimo_lote)
        buf = st.session_state["buf_concordancia"]

        st.download_button(
            label="Descargar Excel concordancia + dashboard",
            data=buf,
            file_name="lote_concordancia_IHQ_MMT_dashboard.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        st.caption("Hoja 1: tabla IHQ/MMT + concordancias. Hoja 2: dashboard con gráficos y top revisión.")

    st.markdown("---")

    # ==================================================
    # BLOQUE 4 · INFORMES PDF (solo si hay lote)
    # ==================================================
    if not df_lote.empty:
        st.subheader("4) Informes PDF")
        st.caption("Las descargas en PDF están enfocadas en este lote procesado.")

        sample_ids = (
            df_lote["sample_id"]
            .astype(str)
            .dropna()
            .unique()
            .tolist()
        )

        if sample_ids:
            col_zip, col_one = st.columns(2)

            # ZIP con todos los PDFs del lote
            with col_zip:
                st.markdown("#### Descargar todos los PDFs del lote (ZIP)")
                st.caption("Genera un ZIP con un PDF por muestra del lote procesado.")

                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for m in ultimo_lote:
                        sid = str(m.get("sample_id", "sin_sample_id"))
                        pdf_b = generar_informe_pdf_bytes(m)
                        zf.writestr(f"informe_{sid}.pdf", pdf_b)

                zip_buffer.seek(0)
                timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")

                # Nota: este nombre incluye una barra (/) y puede crear carpetas dentro del ZIP
                # si la plataforma lo interpreta. Si no lo quieres, cámbialo por "_" o similar.
                zip_name = f"informes_MMT_IHQ_{timestamp}.zip"

                st.download_button(
                    "Descargar informes del lote (ZIP)",
                    data=zip_buffer,
                    file_name=zip_name,
                    mime="application/zip",
                    key="dl_zip_informes_lote",
                )

            # PDF individual
            with col_one:
                st.markdown("#### Descargar un PDF individual")
                st.caption("Selecciona una muestra del lote y genera su informe PDF.")

                sample_sel = st.selectbox(
                    "Selecciona una muestra",
                    options=sample_ids,
                    key="informe_sample_id",
                )

                if st.button("Generar informe PDF de esta muestra"):
                    fila_sel = (
                        df_lote[df_lote["sample_id"].astype(str) == str(sample_sel)]
                        .iloc[0]
                        .to_dict()
                    )

                    pdf_bytes = generar_informe_pdf_bytes(fila_sel)

                    if not isinstance(pdf_bytes, (bytes, bytearray)) or len(pdf_bytes) == 0:
                        st.error("No se pudo generar el PDF.")
                    else:
                        st.download_button(
                            "Descargar informe PDF de esta muestra",
                            data=pdf_bytes,
                            file_name=f"informe_{fila_sel.get('sample_id', 'muestra')}.pdf",
                            mime="application/pdf",
                        )

    st.markdown("---")

    # ==================================================
    # BLOQUE 5 · SINCRONIZACIÓN (paquete ZIP para equipo principal)
    # ==================================================
    # Se construye un ZIP de traspaso con el lote y metadatos de usuario/rol.
    u = current_user() or {}
    meta = {"user": u.get("username"), "role": u.get("role"), "source": "step3"}

    settings = load_settings()

    extra = {}

    # Si se activa en settings, se incluye dentro del ZIP un Excel resumen del lote
    if settings.get("exportacion", {}).get("incluir_excel_resumen_en_zip", False):
        try:
            # Reutilizar el buffer ya calculado en el bloque de descarga, si existe.
            # Evita regenerar el Excel completo una segunda vez en el mismo render.
            buf_cached = st.session_state.get("buf_concordancia")
            if buf_cached is not None:
                buf_cached.seek(0)
                extra["lote_resultados.xlsx"] = buf_cached.read()
            else:
                excel_buf = construir_excel_concordancia_dashboard(
                    pd.DataFrame(st.session_state["ultimo_lote"])
                )
                extra["lote_resultados.xlsx"] = excel_buf.getvalue()
        except Exception:
            # Si falla, se exporta igualmente el ZIP sin el Excel extra
            pass

    zip_bytes = build_transfer_zip(st.session_state["ultimo_lote"], meta=meta, extra_files=extra)
    zip_name = _build_zip_name(settings, meta)

    st.markdown("#### 5) Mover pacientes al equipo principal")
    st.caption(
        "Si se ha trabajado desde un equipo distinto al principal, exporta los cambios desde el botón de abajo.\n"
        "Para importarlos, ve a Ajustes → pestaña **Importar/Exportar**.\n\n"
        "Está pensado para que, si se trabaja desde un equipo secundario, "
        "se puedan incorporar al final del día los pacientes procesados en ese equipo."
    )


    st.download_button(
        "Descargar paquete para equipo principal (ZIP)",
        data=zip_bytes,
        file_name=zip_name,
        mime="application/zip",
    )

    # Registrar acción de exportación (auditoría)
    log_action(
        u.get("username"),
        "sync_export_package",
        {"count": len(st.session_state["ultimo_lote"]), "zip": zip_name}
    )




    st.markdown("---")
    if st.button("Volver al paso 2"):
        ir_a_paso_callback(2)