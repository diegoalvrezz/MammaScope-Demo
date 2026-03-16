# demo_app/demo_app.py
# -----------------------------------------------------------------------------
# Entrada específica para la DEMO pública de la aplicación.
#
# Objetivo:
#   - Permitir probar el flujo completo sin necesidad de iniciar sesión.
#   - Ofrecer dos archivos de ejemplo descargables.
#   - Ejecutar la aplicación real (ubicada en /codigo) sin modificarla.
#
# Importante:
#   - La aplicación original NO contiene modo demo.
#   - Este archivo únicamente fuerza una sesión simulada para entorno público.
# -----------------------------------------------------------------------------

import os
import sys
from pathlib import Path

import streamlit as st


# -------------------------------------------------------------------------
# Definición de rutas
# -------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
CODIGO_DIR = ROOT / "codigo"
DEMO_FILES = Path(__file__).resolve().parent / "demo_files"


def _read_bytes(path: Path) -> bytes:
    """
    Devuelve el contenido binario de un archivo.
    Se utiliza para servir los ficheros demo mediante download_button.
    """
    return path.read_bytes()


def _ensure_demo_session() -> None:
    """
    Fuerza una sesión autenticada simulada para la demo.

    La aplicación real exige inicio de sesión. En este entorno
    público se crea una sesión ficticia con rol 'admin' para
    permitir la navegación completa sin modificar el código original.
    """
    if st.session_state.get("auth_ok") and st.session_state.get("user"):
        return

    st.session_state["user"] = {"username": "demo", "role": "admin"}
    st.session_state["auth_ok"] = True


def main() -> None:
    """
    Función principal de la demo pública de MammaScope.

    1. Añade la carpeta 'codigo' al path de Python.
    2. Configura una base de datos independiente para la demo.
    3. Muestra el logo, la información introductoria y las descargas.
    4. Ejecuta la aplicación real.
    """

    # Permite importar módulos desde la carpeta /codigo
    if str(CODIGO_DIR) not in sys.path:
        sys.path.insert(0, str(CODIGO_DIR))

    # Base de datos aislada para la demo (no modifica la BD real)
    os.environ["TFG_MAMMA_DB_PATH"] = str(ROOT / "demo_app" / "tfg_mamma_demo.db")

    # Configuración general de la página
    st.set_page_config(
        page_title="MammaScope Demo",
        page_icon=str(ROOT / "demo_app" / "logo_mammascope.png"),
        layout="wide"
    )

    # Mostrar logo si existe
    logo_path = ROOT / "demo_app" / "logo_mammascope.png"
    if logo_path.exists():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(str(logo_path), use_container_width=True)

    st.title("Demo pública · MammaScope")
    st.caption("Plataforma clínica para el análisis de cáncer de mama")

    st.markdown("**IMPORTANTE**")
    st.info(
        "Esta es una demostración pública del funcionamiento general de la aplicación.\n\n"
        "La versión de uso real incluye inicio de sesión, control de permisos por rol "
        "y un entorno de trabajo restringido. En esta demo, el acceso se simplifica "
        "únicamente para facilitar la prueba.\n\n"
        "Los archivos disponibles contienen **datos ficticios**. "
        "El archivo PDF de MammaTyper ha sido **simplificado** y adaptado con la información mínima necesaria "
        "para realizar la extracción de datos, con el fin de proteger información sensible. "
        "Los datos incluidos en el PDF también son simulados y ficticios; únicamente se ha ajustado "
        "el número de biopsia para que resulte coherente dentro de la demostración.\n\n"
        "Además, se incluye **un caso de discordancia** para mostrar cómo la aplicación gestiona este tipo de situaciones, "
        "aunque los números de biopsia sean muy similares."
    )

    st.markdown("### Archivos de demostración")
    st.write(
        "1) Descarga los dos archivos de ejemplo.\n"
        "2) Ve al Paso 1 y súbelos manualmente.\n"
        "3) Procesa el lote y revisa los resultados en el Paso 3."
    )

    col1, col2 = st.columns(2)
    excel_file = DEMO_FILES / "demo_patwin.xlsx"
    pdf_file = DEMO_FILES / "demo_mammatypper.pdf"

    with col1:
        if excel_file.exists():
            st.download_button(
                label="Descargar Excel de demostración (PatWin)",
                data=_read_bytes(excel_file),
                file_name="demo_patwin.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_excel_demo"
            )
        else:
            st.warning("No se encuentra el archivo demo_patwin.xlsx.")

    with col2:
        if pdf_file.exists():
            st.download_button(
                label="Descargar PDF de demostración (MammaTyper)",
                data=_read_bytes(pdf_file),
                file_name="demo_mammatypper.pdf",
                mime="application/pdf",
                key="download_pdf_demo"
            )
        else:
            st.warning("No se encuentra el archivo demo_mammatypper.pdf.")

    st.markdown("---")

    st.subheader("Inicio de la aplicación")
    _ensure_demo_session()

    # Importación tardía tras configurar sys.path y la BD de demo
    import app
    app.main()


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
