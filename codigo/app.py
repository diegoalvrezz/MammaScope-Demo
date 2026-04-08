# app.py
import io
import sqlite3
from pathlib import Path

import streamlit as st
import pandas as pd
import numpy as np

from extraccion import (
    extraer_registros_patwin,
    extraer_registros_pdf,
    fusionar_registro_patwin_pdf,
)
from db import (
    init_db,
    bd_existe,
    DB_PATH,
    insertar_muestra_combinada,
    registrar_muestra_sin_match,
    eliminar_muestras_sin_match_por_ids,
    eliminar_muestras_sin_match_por_sample_ids,
    log_action
)
from validacion_archivos import validar_excel_patwin, validar_pdf_mmt
from vista_historico import mostrar_paso_3
from vista_estadistico import mostrar_estadistico
from discordancia import extraer_sample_ids_con_aviso
from ajustes import mostrar_ajustes
from stats_biomarcadores import build_stats_table_from_df
from auth import render_login_gate, render_account_panel, require_role, current_user


# =========================
# Estado de sesión y navegación
# =========================
def init_session_state():
    """
    Inicializa las claves necesarias en `st.session_state`.

    Objetivo:
    - Definir un estado base estable para la navegación por pasos (1-2-3).
    - Guardar en memoria los archivos subidos (bytes) para no depender del uploader
      en cada interacción.
    - Persistir resultados del último procesamiento para visualizarlos en el Paso 3
      sin recalcular.

    Nota:
    - Streamlit re-ejecuta el script con cada interacción; por eso este bloque es esencial
      para que la app no “olvide” el flujo.
    """
    if "step" not in st.session_state:
        st.session_state["step"] = 1
    if "excel_bytes" not in st.session_state:
        st.session_state["excel_bytes"] = None
    if "pdf_bytes" not in st.session_state:
        st.session_state["pdf_bytes"] = None
    if "ultimo_resumen" not in st.session_state:
        st.session_state["ultimo_resumen"] = None
    if "ultimo_lote" not in st.session_state:
        st.session_state["ultimo_lote"] = None
    if "hist_excel_bytes" not in st.session_state:
        st.session_state["hist_excel_bytes"] = None
    if "hist_excel_name" not in st.session_state:
        st.session_state["hist_excel_name"] = "historico_mammatypper_completo.xlsx"


def ir_a_paso(n: int):
    """
    Actualiza el paso del flujo principal.

    Se usa desde botones del sidebar y desde el propio flujo (Paso 1 → Paso 2 → Paso 3).
    """
    st.session_state["step"] = n


# =========================
# Utilidades BD (estado real)
# =========================
def _db_status() -> dict:
    """
    Comprueba el estado real de la base de datos SQLite.

    Devuelve un diccionario con:
    - file_exists: si el archivo existe en disco.
    - can_connect: si es posible abrir una conexión.
    - integrity_ok: resultado del PRAGMA integrity_check (OK o no).
    - tables_ok: si existen tablas esperadas para la app.
    - error: texto de error si algo falla.

    Esto se usa para informar en el sidebar y detectar casos típicos:
    - BD inexistente o movida.
    - Archivo corrupto.
    - BD válida pero sin tablas necesarias.
    """
    status = {
        "file_exists": False,
        "can_connect": False,
        "integrity_ok": False,
        "tables_ok": False,
        "error": None,
    }

    try:
        status["file_exists"] = Path(DB_PATH).exists()

        conn = sqlite3.connect(DB_PATH)
        status["can_connect"] = True

        # Comprobación de integridad interna de SQLite.
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            res = cur.fetchone()
            status["integrity_ok"] = (res is not None and str(res[0]).lower() == "ok")
        except Exception:
            status["integrity_ok"] = False

        # Verificación de tablas que usa el sistema.
        # - muestras: tabla principal con casos emparejados (Excel+PDF).
        # - muestras_sin_match: tabla auxiliar con casos sin correspondencia en un lote.
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {r[0] for r in cur.fetchall()}
            status["tables_ok"] = ("muestras" in tables and "muestras_sin_match" in tables)
        except Exception:
            status["tables_ok"] = False

        conn.close()
        return status

    except Exception as e:
        status["error"] = str(e)
        return status


def _preparar_historico_excel() -> None:
    """
    Carga el histórico completo desde la tabla `muestras` y lo prepara como Excel en memoria.

    Qué hace:
    - Lee la tabla completa `muestras` desde SQLite.
    - Genera un Excel en un buffer (BytesIO).
    - Guarda esos bytes en session_state para ofrecer una descarga inmediata en el sidebar.

    Por qué se hace así:
    - Evita recalcular el Excel en cada re-ejecución.
    - Permite que el botón del sidebar dispare el “preparado” una sola vez.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT * FROM muestras ORDER BY id DESC;", conn)
        conn.close()

        if df.empty:
            st.session_state["hist_excel_bytes"] = None
            st.warning("La tabla `muestras` está vacía. No hay histórico para descargar.")
            return

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="historico_muestras")
        buffer.seek(0)

        st.session_state["hist_excel_bytes"] = buffer.getvalue()
        st.success("Histórico preparado para descarga en el sidebar.")

    except Exception as e:
        st.session_state["hist_excel_bytes"] = None
        st.error(f"No se pudo preparar el histórico: {e}")


def _human_filters_app(filtros_config: list[dict]) -> list[str]:
    """
    Traduce filtros internos (configurados por el usuario) a frases legibles.

    Se usa únicamente para mostrar en la UI “qué filtros están activos” sin enseñar SQL.
    """
    out = []
    for f in filtros_config:
        col = f.get("col")
        tipo = f.get("tipo")
        if tipo == "contiene":
            v = f.get("valor", "")
            if v:
                out.append(f"{col} contiene '{v}'")
        elif tipo == "igual":
            v = f.get("valor", "")
            if v != "":
                out.append(f"{col} = '{v}'")
        else:
            vmin = f.get("vmin", None)
            vmax = f.get("vmax", None)
            if vmin is not None and vmax is not None:
                out.append(f"{col} entre {vmin} y {vmax}")
    return out


# =========================
# EXPLORACIÓN AVANZADA SQL (TABLA MUESTRAS)
# =========================
def mostrar_exploracion_sql():
    """
    Pantalla de exploración de la base de datos histórica (tabla `muestras`).

    Incluye:
    - Estadísticas globales acumuladas (concordancia IHQ vs MammaTyper).
    - Vista general de la tabla (últimos registros).
    - Constructor de filtros (máximo 3) y ejecución de consulta parametrizada.
    - Descarga de resultados a Excel.

    Esta funcionalidad está orientada a roles con perfil supervisor (jefe/admin),
    para análisis y auditoría interna.
    """
    st.header(
        "Explorar base de datos histórica (SQL)",
        help="Permite visualizar la base de datos histórica y ejecutar consultas con filtros sobre la tabla `muestras`."
    )



    # --------------------------------------------------
    # Vista general de la tabla `muestras`
    # --------------------------------------------------
    st.markdown("---")
    st.markdown("### Vista general de la tabla `muestras`")
    st.caption("Muestra las filas más recientes de la tabla `muestras` (ordenadas por `id` descendente).")

    max_general = st.number_input(
        "Número máximo de registros a mostrar (vista general)",
        min_value=1,
        value=100,
        step=10,
        key="sql_muestras_max_general",
        help="Límite de filas para la vista general. Útil para no cargar demasiados registros."
    )

    # La carga se hace bajo demanda (botón) para evitar leer BD en cada re-ejecución.
    if st.button(
        "Cargar histórico (vista general)",
        key="sql_muestras_btn_general",
        help="Carga las últimas filas de `muestras` y las muestra en pantalla."
    ):
        try:
            conn = sqlite3.connect(DB_PATH)
            df = pd.read_sql_query(
                "SELECT * FROM muestras ORDER BY id DESC LIMIT ?;",
                conn,
                params=(int(max_general),),
            )
            conn.close()

            if df.empty:
                st.info("La tabla `muestras` está vacía.")
            else:
                st.write(f"Mostrando {len(df)} filas (más recientes arriba).")
                st.dataframe(df, use_container_width=True)

                # Descarga “tal cual” de lo que el usuario está viendo.
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                    df.to_excel(writer, index=False, sheet_name="muestras")
                buffer.seek(0)

                st.download_button(
                    label="Descargar esta vista general en Excel",
                    data=buffer,
                    file_name="historico_muestras_vista_general.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="sql_muestras_dl_general",
                    help="Descarga en Excel exactamente la tabla que estás viendo en pantalla."
                )
        except Exception as e:
            st.error(f"Error leyendo la base de datos: {e}")

    # --------------------------------------------------
    # Constructor de filtros (SQL parametrizado)
    # --------------------------------------------------
    st.markdown("---")
    st.markdown("### Filtros avanzados (SQL) sobre `muestras`")
    st.caption("Permite construir consultas con hasta 3 filtros combinados con AND.")

    st.info(
        "Los filtros se combinan con **AND**. "
        "`id` es el identificador interno; `sample_id` identifica la muestra."
    )

    # Lista explícita de columnas para:
    # - controlar qué campos se permiten filtrar
    # - evitar que el usuario escriba SQL libremente
    columnas_disponibles = [
        "id",
        "nhc",
        "sample_id",
        "fecha_excel",
        "ronda",
        "celularidad",
        "subtipo_ihq",
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
        "ERBB2_IHQ_SISH",
        "HER2_SISH_result",
        "HER2_final",
        "HER2_IHQ_score",
        "ESR1_IHQ",
        "ESR1_IHQ_intensidad",
        "ESR1_IHQ_pct",
        "PGR_IHQ",
        "PGR_IHQ_intensidad",
        "PGR_IHQ_pct",
        "KI67_IHQ",
        "P53_IHQ_status",
        "P53_IHQ_pct",
        "CK19_IHQ_status",
        "firmantes_diag",
        "aviso",
        # Métricas MMT
        "ERBB2_cutoff_nearest",
        "ERBB2_delta_cutoff",
        "ERBB2_delta_to_positive",
        "ERBB2_equiv",
        "ESR1_cutoff_nearest",
        "ESR1_delta_cutoff",
        "ESR1_delta_to_positive",
        "ESR1_equiv",
        "PGR_cutoff_nearest",
        "PGR_delta_cutoff",
        "PGR_delta_to_positive",
        "PGR_equiv",
        "MKI67_cutoff_nearest",
        "MKI67_delta_cutoff",
        "MKI67_delta_to_positive",
        "MKI67_equiv",
    ]

    # Tipos de filtros disponibles.
    # Se implementan de forma parametrizada (evita inyección SQL).
    tipos_filtro = ["contiene", "igual", "rango numérico"]
    filtros_config = []

    # Se limita a 3 filtros para mantener interfaz simple y consultas razonables.
    with st.expander("Configurar filtros", expanded=True):
        st.caption("Activa un filtro, elige la columna y el tipo, y define el valor a buscar.")
        for i in range(1, 4):
            st.markdown(f"#### Filtro {i}")
            activar = st.checkbox(
                "Activar filtro",
                key=f"sql_muestras_f{i}_on",
                help="Activa este filtro para incluirlo en la consulta."
            )

            if not activar:
                continue

            col = st.selectbox(
                "Columna",
                columnas_disponibles,
                index=0,
                key=f"sql_muestras_f{i}_col",
                help="Columna de la tabla `muestras` sobre la que se aplicará el filtro."
            )
            tipo = st.selectbox(
                "Tipo de filtro",
                tipos_filtro,
                index=0,
                key=f"sql_muestras_f{i}_tipo",
                help="Define cómo se compara: contiene (LIKE), igual (=) o rango numérico (BETWEEN)."
            )

            if tipo == "contiene":
                valor = st.text_input(
                    "Texto a buscar (contiene)",
                    key=f"sql_muestras_f{i}_val_cont",
                    help="Busca coincidencias parciales (equivalente a SQL LIKE '%texto%')."
                )
                filtros_config.append({"col": col, "tipo": tipo, "valor": valor})

            elif tipo == "igual":
                valor = st.text_input(
                    "Valor exacto",
                    key=f"sql_muestras_f{i}_val_eq",
                    help="Busca coincidencia exacta (equivalente a SQL '= valor')."
                )
                filtros_config.append({"col": col, "tipo": tipo, "valor": valor})

            else:
                vmin = st.number_input(
                    "Mínimo (incluido)",
                    key=f"sql_muestras_f{i}_vmin",
                    value=0.0,
                    help="Límite inferior del rango numérico."
                )
                vmax = st.number_input(
                    "Máximo (incluido)",
                    key=f"sql_muestras_f{i}_vmax",
                    value=100.0,
                    help="Límite superior del rango numérico."
                )
                filtros_config.append({"col": col, "tipo": tipo, "vmin": vmin, "vmax": vmax})

    max_filtrados = st.number_input(
        "Número máximo de registros a mostrar (consulta filtrada)",
        min_value=1,
        value=100,
        step=10,
        key="sql_muestras_max_filtrados",
        help="Límite de filas para la consulta filtrada."
    )

    # Construcción del WHERE de forma segura (parametrizada).
    where_clauses = []
    params: list = []

    for f in filtros_config:
        col = f["col"]
        if f["tipo"] == "contiene":
            valor = f.get("valor", "")
            if valor:
                where_clauses.append(f"{col} LIKE ?")
                params.append(f"%{valor}%")

        elif f["tipo"] == "igual":
            valor = f.get("valor", "")
            if valor != "":
                where_clauses.append(f"{col} = ?")
                params.append(valor)

        else:
            vmin = f.get("vmin", None)
            vmax = f.get("vmax", None)
            if vmin is not None and vmax is not None:
                where_clauses.append(f"CAST({col} AS REAL) BETWEEN ? AND ?")
                params.extend([float(vmin), float(vmax)])

    sql = "SELECT * FROM muestras"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY id DESC"
    if max_filtrados:
        sql += " LIMIT ?"
        params.append(int(max_filtrados))

    # Resumen en lenguaje natural de qué filtros se aplican.
    st.markdown("#### Filtros activos")
    human = _human_filters_app(filtros_config)
    if not human:
        st.write("Sin filtros.")
    else:
        for h in human:
            st.write(f"- {h}")

    # Se muestra el SQL solo como herramienta de transparencia/depuración.
    with st.expander("Ver SQL y parámetros", expanded=False):
        st.code(sql, language="sql")
        st.write("Parámetros:")
        st.json(params)

    # Ejecución bajo demanda para no lanzar consultas al re-ejecutar la app.
    if st.button(
        "Ejecutar consulta filtrada",
        key="sql_muestras_btn_filtrado",
        help="Ejecuta la consulta construida con los filtros activos y muestra el resultado."
    ):
        try:
            conn = sqlite3.connect(DB_PATH)
            df_f = pd.read_sql_query(sql, conn, params=params)
            conn.close()

            if df_f.empty:
                st.info("La consulta no ha devuelto registros.")
            else:
                st.write(f"Se han encontrado {len(df_f)} registros.")
                st.dataframe(df_f, use_container_width=True)

                buffer_f = io.BytesIO()
                with pd.ExcelWriter(buffer_f, engine="xlsxwriter") as writer:
                    df_f.to_excel(writer, index=False, sheet_name="consulta_filtrada")
                buffer_f.seek(0)

                st.download_button(
                    label="Descargar resultado filtrado en Excel",
                    data=buffer_f,
                    file_name="historico_muestras_filtrado_sql.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="sql_muestras_dl_filtrado",
                    help="Descarga en Excel el resultado de la consulta filtrada."
                )
        except Exception as e:
            st.error(f"Error ejecutando la consulta SQL: {e}")


# =========================
# EXPLORACIÓN AVANZADA SQL (TABLA MUESTRAS_SIN_MATCH)
# =========================
def mostrar_bases_no_cruzadas():
    """
    Pantalla de exploración de la tabla `muestras_sin_match`.

    Esta tabla contiene identificadores de muestra que aparecen en un archivo (Excel o PDF)
    pero no tienen correspondencia en el otro dentro del lote procesado.

    Incluye:
    - Vista general (últimos registros).
    - Consulta filtrada con hasta 3 filtros.
    - Descarga a Excel.
    - Eliminación controlada por `id` o por `sample_id` (acción irreversible).
    """
    st.header(
        "Bases no cruzadas (SQL sobre `muestras_sin_match`)",
        help="Permite explorar y filtrar registros que existen en un archivo pero no tienen correspondencia en el otro."
    )

    # Se recuperan resultados previos para permitir eliminación sin recalcular.
    df_general = st.session_state.get("nm_df_general")
    df_filtrado = st.session_state.get("nm_df_filtrado")

    st.markdown("### Vista general de la tabla `muestras_sin_match`")
    st.caption("Muestra las filas más recientes de la tabla de no cruzadas (ordenadas por `id` descendente).")

    max_general = st.number_input(
        "Número máximo de registros a mostrar (vista general)",
        min_value=1,
        value=100,
        step=10,
        key="nm_max_general",
        help="Límite de filas para la vista general."
    )

    # Lectura bajo demanda.
    if st.button(
        "Cargar no cruzadas (vista general)",
        key="nm_btn_general",
        help="Carga las últimas filas de `muestras_sin_match` y las muestra en pantalla."
    ):
        try:
            conn = sqlite3.connect(DB_PATH)
            df_general = pd.read_sql_query(
                "SELECT * FROM muestras_sin_match ORDER BY id DESC LIMIT ?;",
                conn,
                params=(int(max_general),),
            )
            conn.close()

            # Guardado en sesión:
            # - nm_df_actual se usa como “tabla sobre la que se puede borrar” sin importar si venía de general o filtrada.
            st.session_state["nm_df_general"] = df_general
            st.session_state["nm_df_actual"] = df_general
            st.session_state["nm_df_filtrado"] = None

            if df_general.empty:
                st.info("La tabla `muestras_sin_match` está vacía.")
            else:
                st.write(f"Mostrando {len(df_general)} filas (más recientes arriba).")
                st.dataframe(df_general, use_container_width=True)

                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                    df_general.to_excel(writer, index=False, sheet_name="muestras_sin_match")
                buffer.seek(0)

                st.download_button(
                    label="Descargar esta vista general en Excel",
                    data=buffer,
                    file_name="muestras_sin_correspondencia_vista_general.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="nm_dl_general",
                    help="Descarga en Excel la vista general mostrada."
                )
        except Exception as e:
            st.error(f"Error leyendo la base de datos: {e}")

    # --------------------------------------------------
    # Filtros avanzados para `muestras_sin_match`
    # --------------------------------------------------
    st.markdown("---")
    st.markdown("### Filtros avanzados (SQL) sobre `muestras_sin_match`")
    st.caption("Construye una consulta con hasta 3 filtros combinados con AND.")

    st.info("Los filtros se combinan con AND. `origen` indica si viene de EXCEL o PDF.")

    columnas_disponibles = ["id", "sample_id", "origen", "fecha_proceso", "detalle"]
    tipos_filtro = ["contiene", "igual", "rango numérico"]
    filtros_config = []

    with st.expander("Configurar filtros", expanded=True):
        st.caption("Activa un filtro, elige columna y tipo, y define el valor.")
        for i in range(1, 4):
            st.markdown(f"#### Filtro {i}")
            activar = st.checkbox(
                "Activar filtro",
                key=f"nm_f{i}_on",
                help="Activa este filtro para incluirlo en la consulta."
            )
            if not activar:
                continue

            col = st.selectbox(
                "Columna",
                columnas_disponibles,
                index=0,
                key=f"nm_f{i}_col",
                help="Columna de la tabla `muestras_sin_match` sobre la que se aplicará el filtro."
            )
            tipo = st.selectbox(
                "Tipo de filtro",
                tipos_filtro,
                index=0,
                key=f"nm_f{i}_tipo",
                help="Define cómo se compara: contiene (LIKE), igual (=) o rango numérico (BETWEEN)."
            )

            if tipo == "contiene":
                valor = st.text_input(
                    "Texto a buscar (contiene)",
                    key=f"nm_f{i}_val_cont",
                    help="Busca coincidencias parciales (equivalente a SQL LIKE '%texto%')."
                )
                filtros_config.append({"col": col, "tipo": tipo, "valor": valor})

            elif tipo == "igual":
                valor = st.text_input(
                    "Valor exacto",
                    key=f"nm_f{i}_val_eq",
                    help="Busca coincidencia exacta (equivalente a SQL '= valor')."
                )
                filtros_config.append({"col": col, "tipo": tipo, "valor": valor})

            else:
                vmin = st.number_input(
                    "Mínimo (incluido)",
                    key=f"nm_f{i}_vmin",
                    value=0.0,
                    help="Límite inferior del rango numérico."
                )
                vmax = st.number_input(
                    "Máximo (incluido)",
                    key=f"nm_f{i}_vmax",
                    value=100.0,
                    help="Límite superior del rango numérico."
                )
                filtros_config.append({"col": col, "tipo": tipo, "vmin": vmin, "vmax": vmax})

    max_filtrados = st.number_input(
        "Número máximo de registros a mostrar (consulta filtrada)",
        min_value=1,
        value=100,
        step=10,
        key="nm_max_filtrados",
        help="Límite de filas para la consulta filtrada."
    )

    where_clauses = []
    params: list = []

    for f in filtros_config:
        col = f["col"]
        if f["tipo"] == "contiene":
            valor = f.get("valor", "")
            if valor:
                where_clauses.append(f"{col} LIKE ?")
                params.append(f"%{valor}%")
        elif f["tipo"] == "igual":
            valor = f.get("valor", "")
            if valor != "":
                where_clauses.append(f"{col} = ?")
                params.append(valor)
        else:
            vmin = f.get("vmin", None)
            vmax = f.get("vmax", None)
            if vmin is not None and vmax is not None:
                where_clauses.append(f"CAST({col} AS REAL) BETWEEN ? AND ?")
                params.extend([float(vmin), float(vmax)])

    sql = "SELECT * FROM muestras_sin_match"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY id DESC"
    if max_filtrados:
        sql += " LIMIT ?"
        params.append(int(max_filtrados))

    st.markdown("#### Filtros activos")
    human = _human_filters_app(filtros_config)
    if not human:
        st.write("Sin filtros.")
    else:
        for h in human:
            st.write(f"- {h}")

    with st.expander("Ver SQL y parámetros", expanded=False):
        st.code(sql, language="sql")
        st.write("Parámetros:")
        st.json(params)

    if st.button(
        "Ejecutar consulta filtrada",
        key="nm_btn_filtrado",
        help="Ejecuta la consulta construida con los filtros activos y muestra el resultado."
    ):
        try:
            conn = sqlite3.connect(DB_PATH)
            df_filtrado = pd.read_sql_query(sql, conn, params=params)
            conn.close()

            st.session_state["nm_df_filtrado"] = df_filtrado
            st.session_state["nm_df_actual"] = df_filtrado

            if df_filtrado.empty:
                st.info("La consulta no ha devuelto registros.")
            else:
                st.write(f"Se han encontrado {len(df_filtrado)} registros.")
                st.dataframe(df_filtrado, use_container_width=True)

                buffer_f = io.BytesIO()
                with pd.ExcelWriter(buffer_f, engine="xlsxwriter") as writer:
                    df_filtrado.to_excel(writer, index=False, sheet_name="consulta_sin_correspondencia")
                buffer_f.seek(0)

                st.download_button(
                    label="Descargar resultado filtrado en Excel",
                    data=buffer_f,
                    file_name="muestras_sin_correspondencia_filtrado_sql.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="nm_dl_filtrado",
                    help="Descarga en Excel el resultado de la consulta filtrada."
                )
        except Exception as e:
            st.error(f"Error ejecutando la consulta SQL: {e}")

    # --------------------------------------------------
    # Eliminación controlada de registros no cruzados
    # --------------------------------------------------
    st.markdown("---")
    st.markdown("### Eliminación de registros no cruzados")
    st.caption("Permite borrar registros erróneos de `muestras_sin_match` (acción irreversible).")

    st.info(
        "Puedes eliminar registros erróneos o introducidos por accidente.\n\n"
        "Opciones:\n"
        "1. Eliminar por `id`.\n"
        "2. Eliminar por `sample_id`.\n\n"
        "Los cambios se aplican sobre la tabla `muestras_sin_match`."
    )

    # La eliminación se apoya en la tabla “actual” (general o filtrada), para que el usuario
    # borre exactamente lo que tiene en pantalla.
    df_para_borrado = st.session_state.get("nm_df_actual")
    if df_para_borrado is None or df_para_borrado.empty:
        st.warning("No hay resultados cargados para eliminar. Primero ejecuta una consulta.")
        return

    st.subheader("Eliminación por ID")
    ids_disponibles = df_para_borrado["id"].tolist()
    ids_a_borrar = st.multiselect(
        "Selecciona uno o varios `id` a eliminar",
        options=ids_disponibles,
        format_func=lambda x: f"id={x}",
        key="nm_ids_borrar",
        help="Selecciona los identificadores internos (`id`) que deseas eliminar de la tabla."
    )

    if st.button(
        "Eliminar por ID",
        key="nm_btn_borrar_id",
        help="Elimina definitivamente los registros seleccionados (por `id`)."
    ):
        if not ids_a_borrar:
            st.warning("No has seleccionado ningún `id`.")
        else:
            try:
                eliminar_muestras_sin_match_por_ids(list(ids_a_borrar))
                st.success(f"Se han eliminado {len(ids_a_borrar)} registros por ID.")
                st.info("Ejecuta nuevamente la consulta para ver los cambios.")
            except Exception as e:
                st.error(f"Error al eliminar por ID: {e}")

    st.markdown("---")

    st.subheader("Eliminación por identificador de muestra (sample_id)")
    sample_ids_disponibles = df_para_borrado["sample_id"].tolist()
    sample_ids_a_borrar = st.multiselect(
        "Selecciona uno o varios `sample_id` a eliminar",
        options=sample_ids_disponibles,
        format_func=lambda x: f"sample_id={x}",
        key="nm_sample_ids_borrar",
        help="Selecciona los identificadores de muestra (`sample_id`) que deseas eliminar."
    )

    if st.button(
        "Eliminar por sample_id",
        key="nm_btn_borrar_sample_id",
        help="Elimina definitivamente los registros seleccionados (por `sample_id`)."
    ):
        if not sample_ids_a_borrar:
            st.warning("No has seleccionado ningún `sample_id`.")
        else:
            try:
                eliminar_muestras_sin_match_por_sample_ids(list(sample_ids_a_borrar))
                st.success(f"Se han eliminado {len(sample_ids_a_borrar)} registros por sample_id.")
                st.info("Vuelve a ejecutar la consulta para actualizar la tabla.")
            except Exception as e:
                st.error(f"Error al eliminar por sample_id: {e}")

def main():
    """
    Punto de entrada principal de la aplicación Streamlit.

    Estructura:
    1) Inicializa el estado de sesión y la base de datos.
    2) Bloquea el acceso si no hay autenticación (login gate).
    3) Define el modo de uso desde el sidebar (flujo principal, exploración SQL, ajustes).
    4) Si se elige “flujo principal”, guía al usuario por los pasos 1-2-3:
       - Paso 1: subida de archivos
       - Paso 2: validación, extracción, fusión y guardado en BD
       - Paso 3: visualización y exportación de resultados
    """
    init_session_state()
    init_db()

    # =========================
    # LOGIN (bloquea app si no autenticado)
    # =========================
    # Esta llamada debe ejecutarse antes de mostrar cualquier funcionalidad sensible.
    render_login_gate("MammaScope · Análisis de Concordancia IHQ – MammaTyper®")
    # Logo de la aplicación (siempre visible)
    logo_path = Path("media/logo.png")

    if logo_path.exists():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(str(logo_path), width=500)
                
    st.title("MammaScope · Análisis de Concordancia IHQ – MammaTyper®")

    # =========================
    # SIDEBAR · MODO SEGÚN ROL
    # =========================
    st.sidebar.subheader("Modo de uso")

    # Modo base: flujo principal (subida → procesamiento → resultados).
    opciones = ["Flujo principal"]

    # Modos avanzados disponibles solo si el rol alcanza “jefe”.
    # require_role() se usa como comprobación rápida de permiso.
    if require_role("jefe"):
        opciones += ["Explorar base de datos histórica (SQL)", "Bases no cruzadas", "Estadístico"]

    # Ajustes accesibles para todos, pero dentro se filtran acciones por rol.
    opciones += ["Ajustes"]

    modo = st.sidebar.radio(
        "Selecciona el modo",
        opciones,
        key="modo_uso"
    )

    st.sidebar.subheader("Base de datos")
    st.sidebar.write(f"Archivo: `{DB_PATH}`")

    # Panel de sesión: informa usuario activo y permite gestión de cuenta (cambio de contraseña, etc.).
    render_account_panel()

    # =========================
    # ESTADO BD
    # =========================
    # Se muestra un resumen rápido del estado para detectar incidencias en entorno local.
    st_bd = _db_status()
    if st_bd["can_connect"] and st_bd["tables_ok"] and st_bd["integrity_ok"]:
        st.sidebar.success("Estado: OK (BD operativa)")
    else:
        st.sidebar.warning("Estado: revisar BD")
        st.sidebar.write(f"- Archivo existe: {st_bd['file_exists']}")
        st.sidebar.write(f"- Conexión: {st_bd['can_connect']}")
        st.sidebar.write(f"- Tablas OK: {st_bd['tables_ok']}")
        st.sidebar.write(f"- Integridad OK: {st_bd['integrity_ok']}")
        if st_bd["error"]:
            st.sidebar.write(f"Error: {st_bd['error']}")

    # =========================
    # DESCARGA HISTÓRICO
    # =========================
    # Se prepara bajo demanda para no generar un Excel grande continuamente.
    st.sidebar.markdown("#### Descarga rápida")
    if st.sidebar.button("Preparar histórico completo (Excel)"):
        _preparar_historico_excel()

        u = current_user() or {}
        log_action(u.get("username"), "prepare_historico_excel", None)

    # Si ya se preparó, se ofrece la descarga.
    if st.session_state.get("hist_excel_bytes"):
        st.sidebar.download_button(
            label="Descargar histórico completo",
            data=st.session_state["hist_excel_bytes"],
            file_name=st.session_state.get(
                "hist_excel_name", "historico_mammatypper_completo.xlsx"
            ),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # =========================
    # MODOS DIRECTOS (NO FLUJO)
    # =========================
    # Cada modo es una “pantalla” independiente.
    if modo == "Explorar base de datos histórica (SQL)":
        mostrar_exploracion_sql()
        return

    elif modo == "Bases no cruzadas":
        mostrar_bases_no_cruzadas()
        return

    elif modo == "Estadístico":
        mostrar_estadistico()
        return

    elif modo == "Ajustes":
        mostrar_ajustes()
        return

    # =========================
    # FLUJO PRINCIPAL
    # =========================
    st.sidebar.markdown("---")
    st.sidebar.subheader("Navegación (flujo principal)")

    # Navegación manual por pasos (útil para repetir resultados o volver atrás).
    if st.sidebar.button("Ir al paso 1", key="sidebar_paso_1"):
        ir_a_paso(1)
    if st.sidebar.button("Ir al paso 2", key="sidebar_paso_2"):
        ir_a_paso(2)
    if st.sidebar.button("Ir al paso 3", key="sidebar_paso_3"):
        ir_a_paso(3)

    step = st.session_state["step"]

    # =========================
    # PASO 1: Subida de archivos
    # =========================
    if step == 1:
        st.header("Paso 1 · Subida de archivos")

        st.markdown(
            "Sube el **Excel** procedente de Patwin/MammaTyper y el **PDF** "
            "con los informes MammaTyper® que quieras procesar."
        )

        col1, col2 = st.columns(2)

        # Subida del Excel (Patwin/MMT).
        # Se guardan bytes en sesión para que el archivo se mantenga aunque Streamlit re-ejecute el script.
        with col1:
            archivo_excel = st.file_uploader(
                "Excel (.xlsx)",
                type=["xlsx"],
                key="uploader_excel"
            )

        # Subida del PDF de informes (MMT).
        with col2:
            archivo_pdf = st.file_uploader(
                "PDF MammaTyper",
                type=["pdf"],
                key="uploader_pdf"
            )

        if archivo_excel is not None:
            st.session_state["excel_bytes"] = archivo_excel.getvalue()
            st.success(f"Excel cargado: {archivo_excel.name}")

        if archivo_pdf is not None:
            st.session_state["pdf_bytes"] = archivo_pdf.getvalue()
            st.success(f"PDF cargado: {archivo_pdf.name}")

        st.markdown("---")

        # Se habilita el salto al Paso 2 únicamente si ambos archivos están presentes.
        if st.session_state["excel_bytes"] and st.session_state["pdf_bytes"]:
            st.info("Excel y PDF listos para procesar.")
            if st.button("Ir al paso 2", key="main_paso_1_a_paso_2"):
                ir_a_paso(2)
        else:
            st.warning("Sube ambos archivos para continuar.")

    # =========================
    # PASO 2: Procesamiento
    # =========================
    elif step == 2:
        st.header("Paso 2 · Procesamiento y almacenamiento en BD")

        if not (st.session_state["excel_bytes"] and st.session_state["pdf_bytes"]):
            st.error("No hay archivos cargados en memoria. Vuelve al paso 1.")
            if st.button("Volver al paso 1", key="step2_error_volver_paso_1"):
                ir_a_paso(1)
            return

        st.markdown(
            "En este paso se:\n"
            "- Valida el formato del Excel y del PDF.\n"
            "- Extraen los registros.\n"
            "- Fusionan por `sample_id`.\n"
            "- Guardan en la base de datos solo las muestras con información combinada.\n"
            "- Registran las **no correspondencias** (EXCEL/PDF) en una tabla aparte."
        )

        if st.button("Procesar y guardar muestras en BD"):
            u = current_user() or {}
            log_action(u.get("username"), "process_click", None)

            try:
                TOTAL_PASOS = 7
                barra = st.progress(0)
                texto = st.empty()

                with st.status("Ejecutando pipeline de procesamiento...", expanded=True) as status:

                    # --- Paso 1: Validación Excel ---
                    texto.info("Paso 1/7 — Validando formato del Excel...")
                    barra.progress(1 / TOTAL_PASOS)
                    ok_xls, msg_xls = validar_excel_patwin(st.session_state["excel_bytes"])
                    if not ok_xls:
                        barra.progress(0)
                        texto.error("Error en la validacion del Excel.")
                        status.update(label="Error en la validacion del Excel.", state="error")
                        st.error(f"Error en el Excel:\n\n{msg_xls}")
                        st.stop()
                    st.write("Formato del Excel validado correctamente.")

                    # --- Paso 2: Validación PDF ---
                    texto.info("Paso 2/7 — Validando formato del PDF...")
                    barra.progress(2 / TOTAL_PASOS)
                    ok_pdf, msg_pdf = validar_pdf_mmt(st.session_state["pdf_bytes"])
                    if not ok_pdf:
                        barra.progress(0)
                        texto.error("Error en la validacion del PDF.")
                        status.update(label="Error en la validacion del PDF.", state="error")
                        st.error(f"Error en el PDF:\n\n{msg_pdf}")
                        st.stop()
                    st.write("Formato del PDF validado correctamente.")

                    # --- Paso 3: Extracción Excel ---
                    texto.info("Paso 3/7 — Extrayendo registros del Excel (Patwin)...")
                    barra.progress(3 / TOTAL_PASOS)
                    excel_file = io.BytesIO(st.session_state["excel_bytes"])
                    registros_excel = extraer_registros_patwin(excel_file)
                    idx_excel = {
                        reg.get("sample_id"): reg
                        for reg in registros_excel
                        if reg.get("sample_id")
                    }
                    st.write(f"Registros extraidos del Excel: {len(registros_excel)}.")

                    # --- Paso 4: Extracción PDF ---
                    texto.info("Paso 4/7 — Extrayendo registros del PDF (MammaTyper)...")
                    barra.progress(4 / TOTAL_PASOS)
                    pdf_file = io.BytesIO(st.session_state["pdf_bytes"])
                    regs_pdf = extraer_registros_pdf(pdf_file)
                    st.write(f"Registros extraidos del PDF: {len(regs_pdf)}.")

                    # --- Paso 5: Fusión ---
                    texto.info("Paso 5/7 — Fusionando registros por sample_id...")
                    barra.progress(5 / TOTAL_PASOS)
                    procesados = []
                    sin_match_pdf: list[str] = []
                    sids_pdf_usados: set[str] = set()

                    for reg_pdf in regs_pdf:
                        sid = reg_pdf.get("sample_id")
                        if not sid:
                            continue
                        reg_excel = idx_excel.get(sid)
                        if reg_excel is None:
                            sin_match_pdf.append(sid)
                            registrar_muestra_sin_match(
                                sample_id=sid,
                                origen="PDF",
                                detalle="Sample ID presente en PDF pero sin pareja en Excel (lote).",
                            )
                            continue
                        sids_pdf_usados.add(sid)
                        combinado = fusionar_registro_patwin_pdf(reg_excel, reg_pdf)
                        insertar_muestra_combinada(combinado)
                        procesados.append(combinado)
                    st.write(f"Muestras fusionadas correctamente: {len(procesados)}.")

                    # --- Paso 6: Excel sin PDF ---
                    texto.info("Paso 6/7 — Registrando muestras sin correspondencia...")
                    barra.progress(6 / TOTAL_PASOS)
                    sids_excel = set(idx_excel.keys())
                    sin_match_excel = sorted(sids_excel - sids_pdf_usados)
                    for sid in sin_match_excel:
                        registrar_muestra_sin_match(
                            sample_id=sid,
                            origen="EXCEL",
                            detalle="Sample ID presente en Excel pero sin pareja en PDF (lote).",
                        )
                    st.write(f"Sin correspondencia — PDF sin Excel: {len(sin_match_pdf)}, Excel sin PDF: {len(sin_match_excel)}.")

                    # --- Paso 7: Guardado en sesión ---
                    texto.info("Paso 7/7 — Guardando resultados en sesion...")
                    barra.progress(7 / TOTAL_PASOS)
                    st.session_state["ultimo_lote"] = procesados
                    ids_con_aviso = extraer_sample_ids_con_aviso(procesados)
                    resumen = {
                        "n_excel": len(registros_excel),
                        "n_pdf": len(regs_pdf),
                        "n_procesados": len(procesados),
                        "sin_match": sin_match_pdf,
                        "sin_match_pdf": sin_match_pdf,
                        "sin_match_excel": sin_match_excel,
                    }
                    st.session_state["ultimo_resumen"] = resumen

                    log_action(
                        u.get("username"),
                        "process_done",
                        {
                            "n_excel": len(registros_excel),
                            "n_pdf": len(regs_pdf),
                            "n_procesados": len(procesados),
                            "sin_match_pdf": len(sin_match_pdf),
                            "sin_match_excel": len(sin_match_excel),
                        },
                    )

                    # Barra completada
                    barra.progress(100)
                    texto.success("Proceso completado correctamente.")

                    status.update(
                        label=f"Proceso completado. {len(procesados)} muestras guardadas en la base de datos.",
                        state="complete",
                    )

                # Avisos fuera del status para que sean visibles
                if ids_con_aviso:
                    st.warning(
                        "Aviso para muestras: "
                        + ", ".join(ids_con_aviso)
                        + ". IMPORTANTE: Aviso automatico: indica discordancias potenciales y requiere revision."
                    )

                if sin_match_pdf or sin_match_excel:
                    st.warning(
                        "Se han registrado muestras **sin correspondencia**:\n"
                        f"- PDF sin Excel: {len(sin_match_pdf)}\n"
                        f"- Excel sin PDF: {len(sin_match_excel)}\n\n"
                        "Puedes consultar estos casos en el modo `Bases no cruzadas`."
                    )

            except Exception as e:
                st.error(f"Error procesando los archivos: {e}")

        st.markdown("---")
        col_prev, col_next = st.columns(2)
        with col_prev:
            if st.button("Volver al paso 1", key="step2_volver_paso_1"):
                ir_a_paso(1)
        with col_next:
            if st.button("Ir al paso 3", key="step2_ir_paso_3"):
                ir_a_paso(3)

    # =========================
    # PASO 3: Resultados y exportación
    # =========================
    elif step == 3:
        # Paso 3 se delega a `vista_historico.py` para mantener este archivo más limpio.
        mostrar_paso_3(ir_a_paso)


if __name__ == "__main__":
    # Entrada estándar del script. En Streamlit se ejecuta como script,
    # pero este bloque permite también ejecución directa con `python app.py` en depuración local.
    main()