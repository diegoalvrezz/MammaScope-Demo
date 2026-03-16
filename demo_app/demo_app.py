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
    Función principal de la demo.

    1. Añade la carpeta 'codigo' al path de Python.
    2. Configura una base de datos independiente para la demo.
    3. Muestra información introductoria y descargas.
    4. Ejecuta la aplicación real.
    """

    # Permite importar módulos desde la carpeta /codigo
    if str(CODIGO_DIR) not in sys.path:
        sys.path.insert(0, str(CODIGO_DIR))

    # Base de datos aislada para la demo (no toca la BD real)
    os.environ["TFG_MAMMA_DB_PATH"] = str(ROOT / "demo_app" / "tfg_mamma_demo.db")

    st.title("Demo pública · TFG MammaTyper")
    st.markdown("**IMPORTANTE:**")
    st.info(
        "Esta es una demostración pública del funcionamiento completo de la aplicación.\n\n"
        "La versión de uso real incluye inicio de sesión y control de permisos por rol. "
        "En esta demo el acceso se simula únicamente para facilitar la prueba.\n\n"
        
        
        "Los archivos contienen **datos ficticios**. El archivo PDF (proveniente de mammatyper) esta **simplificado** con la información necesaria para la extracción de la información, para proteger informacion sensible. Los datos del PDF tambien están simulados y son ficticios, unicamente están modificados para que concuerde el número de biopsia.\n\n"
        
        
        "Se añade en los datos **un caso de discordancia** (pese a que los nº de biopsia sean muy similares) para que se contemple el manejo de casos discordantes en la demo."
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
                label="Descargar Excel demo (Patwin)",
                data=_read_bytes(excel_file),
                file_name="demo_patwin.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            st.warning("No se encuentra el archivo demo_patwin.xlsx.")

    with col2:
        if pdf_file.exists():
            st.download_button(
                label="Descargar PDF demo (MammaTyper)",
                data=_read_bytes(pdf_file),
                file_name="demo_mammatypper.pdf",
                mime="application/pdf",
            )
        else:
            st.warning("No se encuentra el archivo demo_mammatypper.pdf.")

    st.markdown("---")

    st.title("Comienzo de la aplicación:")
    _ensure_demo_session()

    # Import tardío tras configurar sys.path y la BD de demo
    import app
    app.main()


if __name__ == "__main__":
    main()