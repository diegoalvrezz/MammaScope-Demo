# vista_procesamiento.py
"""
Paso 2 del flujo principal: validación, extracción, fusión y guardado en BD.

Responsabilidades de este módulo:
- Validar los archivos subidos (Excel y PDF) antes de procesar.
- Extraer registros de ambas fuentes (Patwin/Excel y MammaTyper/PDF).
- Fusionar los registros por sample_id.
- Persistir los resultados en la base de datos.
- Registrar las no correspondencias (sin_match) en su tabla auxiliar.
- Actualizar session_state con el resumen del lote para que el Paso 3 lo consuma.

Nota de diseño:
    Este módulo fue separado de app.py para mantener el orquestador principal
    por debajo de las 500 líneas. Sigue el mismo patrón que vista_historico.py:
    expone una única función pública (mostrar_paso_2) que recibe la función de
    navegación como argumento, evitando acoplamiento directo con app.py.
"""

import io

import streamlit as st

from extraccion import (
    extraer_registros_patwin,
    extraer_registros_pdf,
    fusionar_registro_patwin_pdf,
)
from db import (
    insertar_muestra_combinada,
    registrar_muestra_sin_match,
    log_action,
)
from validacion_archivos import validar_excel_patwin, validar_pdf_mmt
from discordancia import extraer_sample_ids_con_aviso
from auth import current_user


# =============================================================================
# Pipeline de procesamiento (lógica pura, sin UI)
# =============================================================================

def ejecutar_pipeline(excel_bytes: bytes, pdf_bytes: bytes) -> dict:
    """
    Ejecuta el pipeline completo de procesamiento de un lote:

      1. Extrae registros del Excel (Patwin/IHQ).
      2. Extrae registros del PDF (MammaTyper).
      3. Fusiona por sample_id.
      4. Inserta los combinados en la BD.
      5. Registra las no correspondencias (sin_match).

    Parámetros
    ----------
    excel_bytes : bytes
        Contenido del archivo Excel de Patwin.
    pdf_bytes : bytes
        Contenido del PDF de informes MammaTyper.

    Retorna
    -------
    dict con:
        - registros_excel  : list  — registros extraídos del Excel
        - regs_pdf         : list  — registros extraídos del PDF
        - procesados       : list  — muestras fusionadas e insertadas en BD
        - sin_match_pdf    : list[str] — sample_ids en PDF sin pareja en Excel
        - sin_match_excel  : list[str] — sample_ids en Excel sin pareja en PDF

    Nota:
        Esta función no depende de Streamlit: es testeable de forma aislada.
    """
    # --- Extracción Excel ---
    registros_excel = extraer_registros_patwin(io.BytesIO(excel_bytes))
    idx_excel = {
        reg.get("sample_id"): reg
        for reg in registros_excel
        if reg.get("sample_id")
    }

    # --- Extracción PDF ---
    regs_pdf = extraer_registros_pdf(io.BytesIO(pdf_bytes))

    # --- Fusión y persistencia ---
    procesados: list = []
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
        resultado = insertar_muestra_combinada(combinado)
        combinado["_db_op"] = resultado   # "insert" o "update"
        procesados.append(combinado)

    # --- Excel sin PDF ---
    sin_match_excel = sorted(set(idx_excel.keys()) - sids_pdf_usados)
    for sid in sin_match_excel:
        registrar_muestra_sin_match(
            sample_id=sid,
            origen="EXCEL",
            detalle="Sample ID presente en Excel pero sin pareja en PDF (lote).",
        )

    return {
        "registros_excel": registros_excel,
        "regs_pdf": regs_pdf,
        "procesados": procesados,
        "sin_match_pdf": sin_match_pdf,
        "sin_match_excel": sin_match_excel,
    }


# =============================================================================
# Vista: Paso 2 (UI Streamlit)
# =============================================================================

def mostrar_paso_2(ir_a_paso) -> None:
    """
    Renderiza el Paso 2 del flujo principal: procesamiento y guardado en BD.

    Parámetros
    ----------
    ir_a_paso : callable
        Función de navegación de app.py (``ir_a_paso(n: int)``).
        Se recibe como argumento para evitar acoplamiento directo con app.py.

    Flujo de UI:
    1) Comprueba que hay archivos en session_state (si no, redirige al Paso 1).
    2) Muestra un resumen de lo que se va a hacer.
    3) Botón «Procesar»: lanza validación + pipeline con barra de progreso.
    4) Muestra avisos clínicos y no correspondencias tras el proceso.
    5) Navegación a Paso 1 (volver) o Paso 3 (continuar).
    """
    st.header("Paso 2 · Procesamiento y almacenamiento en BD")

    # Guardia: sin archivos no se puede procesar.
    if not (st.session_state.get("excel_bytes") and st.session_state.get("pdf_bytes")):
        st.error("No hay archivos cargados en memoria. Vuelve al paso 1.")
        if st.button("Volver al paso 1", key="step2_error_volver_paso_1"):
            ir_a_paso(1)
        return

    st.markdown(
        "En este paso se:\n"
        "- Valida el formato del Excel y del PDF.\n"
        "- Extraen los registros de cada fuente.\n"
        "- Fusionan por `sample_id`.\n"
        "- Guardan en la base de datos solo las muestras con información combinada.\n"
        "- Registran las **no correspondencias** (EXCEL/PDF) en una tabla aparte."
    )

    if st.button("Procesar y guardar muestras en BD"):
        u = current_user() or {}
        log_action(u.get("username"), "process_click", None)

        try:
            _ejecutar_con_progreso(
                excel_bytes=st.session_state["excel_bytes"],
                pdf_bytes=st.session_state["pdf_bytes"],
                username=u.get("username"),
            )
        except Exception as e:
            st.error(f"Error procesando los archivos: {e}")

    # Navegación inferior
    st.markdown("---")
    col_prev, col_next = st.columns(2)
    with col_prev:
        if st.button("Volver al paso 1", key="step2_volver_paso_1"):
            ir_a_paso(1)
    with col_next:
        if st.button("Ir al paso 3", key="step2_ir_paso_3"):
            ir_a_paso(3)


# =============================================================================
# Helpers privados de UI
# =============================================================================

def _ejecutar_con_progreso(excel_bytes: bytes, pdf_bytes: bytes, username: Optional[str]) -> None:
    """
    Envuelve ``ejecutar_pipeline`` con barra de progreso y ``st.status``.

    Separa la lógica de presentación (progreso, mensajes) de la lógica de negocio
    (ejecutar_pipeline), facilitando el mantenimiento y los tests.

    Pasos de UI:
        1/4 — Validación Excel
        2/4 — Validación PDF
        3/4 — Extracción, fusión y guardado en BD
        4/4 — Guardado en session_state y auditoría
    """
    TOTAL_PASOS = 4
    barra = st.progress(0)
    texto = st.empty()

    with st.status("Ejecutando pipeline de procesamiento...", expanded=True) as status:

        # --- 1/4: Validación Excel ---
        texto.info("Paso 1/4 — Validando formato del Excel...")
        barra.progress(1 / TOTAL_PASOS)
        ok_xls, msg_xls = validar_excel_patwin(excel_bytes)
        if not ok_xls:
            barra.progress(0)
            texto.error("Error en la validación del Excel.")
            status.update(label="Error en la validación del Excel.", state="error")
            st.error(f"Error en el Excel:\n\n{msg_xls}")
            st.stop()
        st.write("✔ Formato del Excel validado correctamente.")

        # --- 2/4: Validación PDF ---
        texto.info("Paso 2/4 — Validando formato del PDF...")
        barra.progress(2 / TOTAL_PASOS)
        ok_pdf, msg_pdf = validar_pdf_mmt(pdf_bytes)
        if not ok_pdf:
            barra.progress(0)
            texto.error("Error en la validación del PDF.")
            status.update(label="Error en la validación del PDF.", state="error")
            st.error(f"Error en el PDF:\n\n{msg_pdf}")
            st.stop()
        st.write("✔ Formato del PDF validado correctamente.")

        # --- 3/4: Pipeline completo (extracción + fusión + BD) ---
        texto.info("Paso 3/4 — Extrayendo, fusionando y guardando en BD...")
        barra.progress(3 / TOTAL_PASOS)

        resultado = ejecutar_pipeline(excel_bytes, pdf_bytes)

        n_excel   = len(resultado["registros_excel"])
        n_pdf     = len(resultado["regs_pdf"])
        procesados      = resultado["procesados"]
        sin_match_pdf   = resultado["sin_match_pdf"]
        sin_match_excel = resultado["sin_match_excel"]

        st.write(f"✔ Registros extraídos del Excel: {n_excel}.")
        st.write(f"✔ Registros extraídos del PDF: {n_pdf}.")
        n_insert = sum(1 for p in procesados if p.get("_db_op") == "insert")
        n_update = sum(1 for p in procesados if p.get("_db_op") == "update")
        msg = f"✔ Muestras procesadas: {len(procesados)}"
        if n_update:
            msg += f" ({n_insert} nuevas, {n_update} actualizadas)"
        else:
            msg += " (todas nuevas)"
        st.write(msg)
        st.write(
            f"✔ Sin correspondencia — PDF sin Excel: {len(sin_match_pdf)}, "
            f"Excel sin PDF: {len(sin_match_excel)}."
        )

        # --- 4/4: Persistencia en session_state + auditoría ---
        texto.info("Paso 4/4 — Guardando resultados en sesión...")
        barra.progress(4 / TOTAL_PASOS)

        ids_con_aviso = extraer_sample_ids_con_aviso(procesados)
        st.session_state["ultimo_lote"] = procesados
        st.session_state["ultimo_resumen"] = {
            "n_excel": n_excel,
            "n_pdf": n_pdf,
            "n_procesados": len(procesados),
            "sin_match": sin_match_pdf,          # retrocompatibilidad
            "sin_match_pdf": sin_match_pdf,
            "sin_match_excel": sin_match_excel,
        }

        log_action(
            username,
            "process_done",
            {
                "n_excel": n_excel,
                "n_pdf": n_pdf,
                "n_procesados": len(procesados),
                "sin_match_pdf": len(sin_match_pdf),
                "sin_match_excel": len(sin_match_excel),
            },
        )

        barra.progress(100)
        texto.success("✔ Proceso completado correctamente.")
        status.update(
            label=f"Proceso completado. {len(procesados)} muestras guardadas en la base de datos.",
            state="complete",
        )

    # Avisos fuera del st.status para que sean visibles una vez cerrado el bloque.
    if ids_con_aviso:
        st.warning(
            "⚠ Avisos automáticos para las muestras: "
            + ", ".join(ids_con_aviso)
            + ".\n\nIndica discordancias potenciales. Requiere revisión por facultativo responsable."
        )

    if sin_match_pdf or sin_match_excel:
        st.warning(
            "⚠ Se han registrado muestras **sin correspondencia**:\n"
            f"- PDF sin Excel: {len(sin_match_pdf)}\n"
            f"- Excel sin PDF: {len(sin_match_excel)}\n\n"
            "Puedes consultarlas en el modo **Bases no cruzadas**."
        )