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


def _inject_demo_styles() -> None:
    """
    Inyecta estilos CSS para mejorar el aspecto visual de la portada de la demo.
    """
    st.markdown(
        """
        <style>
        .bloque-demo {
            background-color: #f8fafc;
            border: 1px solid #e5e7eb;
            border-radius: 18px;
            padding: 1.4rem 1.4rem 1.2rem 1.4rem;
            margin-bottom: 1.2rem;
        }

        .cabecera-demo {
            text-align: center;
            margin-top: 0.2rem;
            margin-bottom: 1.2rem;
        }

        .titulo-demo {
            font-size: 2.6rem;
            font-weight: 800;
            line-height: 1.1;
            color: #1f2937;
            margin-bottom: 0.2rem;
        }

        .subtitulo-demo {
            font-size: 1.05rem;
            color: #6b7280;
            margin-bottom: 0.4rem;
        }

        .nota-demo {
            font-size: 0.95rem;
            color: #4b5563;
            text-align: center;
            margin-top: 0.2rem;
            margin-bottom: 0;
        }

        .tarjeta-demo {
            background-color: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 16px;
            padding: 1rem 1rem 0.8rem 1rem;
            min-height: 170px;
        }

        .tarjeta-demo h4 {
            margin-top: 0;
            margin-bottom: 0.4rem;
            color: #1f2937;
            font-size: 1.05rem;
        }

        .tarjeta-demo p {
            color: #6b7280;
            font-size: 0.95rem;
            margin-bottom: 0.9rem;
        }

        .seccion-demo {
            margin-top: 1.2rem;
            margin-bottom: 0.6rem;
            font-size: 1.25rem;
            font-weight: 700;
            color: #1f2937;
        }

        .pasos-demo {
            background-color: #f9fafb;
            border: 1px dashed #d1d5db;
            border-radius: 14px;
            padding: 0.9rem 1rem;
            color: #374151;
            margin-bottom: 1rem;
        }

        .divider-demo {
            margin-top: 1.2rem;
            margin-bottom: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    """
    Función principal de la demo pública de MammaScope.

    1. Añade la carpeta 'codigo' al path de Python.
    2. Configura una base de datos independiente para la demo.
    3. Muestra el logo, la información introductoria y las descargas.
    4. Ejecuta la aplicación real.
    """

    # Configuración general de la página
    st.set_page_config(
        page_title="MammaScope Demo",
        page_icon=str(ROOT / "docs" / "logo.png"),
        layout="wide"
    )

    _inject_demo_styles()

    # Permite importar módulos desde la carpeta /codigo
    if str(CODIGO_DIR) not in sys.path:
        sys.path.insert(0, str(CODIGO_DIR))

    # Base de datos aislada para la demo (no modifica la BD real)
    os.environ["TFG_MAMMA_DB_PATH"] = str(ROOT / "demo_app" / "tfg_mamma_demo.db")

    # ---------------------------------------------------------------------
    # Cabecera visual de la demo
    # ---------------------------------------------------------------------
    logo_path = ROOT / "docs" / "logo.png"

    st.markdown('<div class="bloque-demo">', unsafe_allow_html=True)

    if logo_path.exists():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(str(logo_path), width=500)

    st.markdown(
        """
        <div class="cabecera-demo">
            <div class="titulo-demo">Demo pública · MammaScope</div>
            <div class="subtitulo-demo">Plataforma clínica para el análisis de cáncer de mama</div>
            <p class="nota-demo">
                Entorno de demostración preparado para mostrar el flujo general de la aplicación
                con archivos ficticios y una sesión simulada.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

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

    st.markdown('<div class="seccion-demo">Archivos de demostración</div>', unsafe_allow_html=True)

    st.markdown(
        """
        <div class="pasos-demo">
            <strong>Pasos recomendados:</strong><br>
            1) Descarga los dos archivos de ejemplo.<br>
            2) Ve al Paso 1 y súbelos manualmente.<br>
            3) Procesa el lote y revisa los resultados en el Paso 3.
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2, gap="large")
    excel_file = DEMO_FILES / "demo_patwin.xlsx"
    pdf_file = DEMO_FILES / "demo_mammatypper.pdf"

    with col1:
        st.markdown(
            """
            <div class="tarjeta-demo">
                <h4>Excel de demostración (PatWin)</h4>
                <p>
                    Archivo de ejemplo con datos ficticios para cargar en el flujo principal de la demo.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if excel_file.exists():
            st.download_button(
                label="Descargar Excel de demostración",
                data=_read_bytes(excel_file),
                file_name="demo_patwin.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="demo_public_download_excel_patwin"
            )
        else:
            st.warning("No se encuentra el archivo demo_patwin.xlsx.")

    with col2:
        st.markdown(
            """
            <div class="tarjeta-demo">
                <h4>PDF de demostración (MammaTyper)</h4>
                <p>
                    Archivo de ejemplo simplificado con la información necesaria para probar la extracción.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if pdf_file.exists():
            st.download_button(
                label="Descargar PDF de demostración",
                data=_read_bytes(pdf_file),
                file_name="demo_mammatypper.pdf",
                mime="application/pdf",
                key="demo_public_download_pdf_mammatypper"
            )
        else:
            st.warning("No se encuentra el archivo demo_mammatypper.pdf.")

    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("<hr class='divider-demo'>", unsafe_allow_html=True)

    # ---------------------------------------------------------------------
    # Inicio de la aplicación real
    # ---------------------------------------------------------------------
    st.subheader("Inicio de la aplicación")
    _ensure_demo_session()

    # Importación tardía tras configurar sys.path y la BD de demo
    import app
    app.main()


if __name__ == "__main__":
    main()
