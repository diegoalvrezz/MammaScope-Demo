# demo_app/demo_app.py
# -----------------------------------------------------------------------------
# Entrada específica para la DEMO pública de la aplicación.
#
# Objetivo:
#   - Permitir probar el flujo completo sin necesidad de iniciar sesión.
#   - Ofrecer dos archivos de ejemplo descargables.
#   - Ejecutar la aplicación real (ubicada en /codigo) sin modificarla.
#   - Mostrar una guía contextual en el sidebar adaptada a cada sección.
#
# Importante:
#   - La aplicación original NO contiene modo demo.
#   - Este archivo únicamente fuerza una sesión simulada y añade contexto didáctico.
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
    Inyecta estilos CSS para mejorar el aspecto visual de la portada de la demo
    y del panel de guía contextual del sidebar.
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

        /* Guía contextual del sidebar */
        .guia-titulo {
            font-size: 1rem;
            font-weight: 700;
            color: #1f2937;
            margin-bottom: 0.2rem;
        }

        .guia-tag {
            display: inline-block;
            background: #dbeafe;
            color: #1d4ed8;
            border-radius: 8px;
            font-size: 0.78rem;
            font-weight: 600;
            padding: 0.1rem 0.55rem;
            margin-bottom: 0.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# -------------------------------------------------------------------------
# Guía contextual del sidebar: una función por sección
# -------------------------------------------------------------------------

def _guia_paso1() -> None:
    """Guía contextual para el Paso 1 (carga de archivos)."""
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<div class="guia-titulo">🗂️ Paso 1 · Carga de archivos</div>'
        '<div class="guia-tag">Estás aquí</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "En este paso se cargan los dos archivos de entrada necesarios para el análisis:"
    )
    st.sidebar.markdown(
        "**Excel de PatWin** — contiene los resultados de la inmunohistoquímica clásica (IHQ): "
        "ER (ESR1), PR (PGR), HER2 (ERBB2) y Ki-67 (MKI67). "
        "Es el informe estándar del sistema histopatológico del hospital."
    )
    st.sidebar.markdown(
        "**PDF de MammaTyper®** — contiene los resultados del kit de diagnóstico molecular "
        "RT-qPCR de Roche. Mide la expresión génica de los mismos cuatro biomarcadores "
        "desde el ARN tumoral extraído de la biopsia."
    )
    st.sidebar.info(
        "💡 En la demo puedes descargar los archivos de ejemplo desde la portada "
        "y subirlos aquí para probar el flujo completo."
    )
    st.sidebar.caption("Los archivos se guardan temporalmente en memoria durante la sesión.")


def _guia_paso2() -> None:
    """Guía contextual para el Paso 2 (procesamiento)."""
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<div class="guia-titulo">⚙️ Paso 2 · Procesamiento</div>'
        '<div class="guia-tag">Estás aquí</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "Al pulsar **Procesar**, la aplicación ejecuta un pipeline de 7 pasos:"
    )
    st.sidebar.markdown(
        "1. **Valida** el formato del Excel (estructura PatWin reconocible).\n"
        "2. **Valida** el formato del PDF (informe MammaTyper® reconocible).\n"
        "3. **Extrae** los registros del Excel (IHQ por muestra).\n"
        "4. **Extrae** los registros del PDF (RT-qPCR por muestra).\n"
        "5. **Cruza** ambas fuentes por `sample_id` (número de biopsia).\n"
        "6. **Registra** las muestras sin correspondencia entre fuentes.\n"
        "7. **Guarda** las muestras fusionadas en la base de datos."
    )
    st.sidebar.warning(
        "⚠️ Si una muestra aparece solo en el Excel o solo en el PDF, "
        "se registra como **base no cruzada** y no se incluye en el análisis de concordancia. "
        "En la demo verás un ejemplo de esto."
    )
    st.sidebar.caption(
        "Las discordancias potenciales se detectan automáticamente y generan un aviso ⚠️ "
        "al finalizar el proceso."
    )


def _guia_paso3() -> None:
    """Guía contextual para el Paso 3 (resultados y exportación)."""
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<div class="guia-titulo">📊 Paso 3 · Resultados y exportación</div>'
        '<div class="guia-tag">Estás aquí</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "Esta pantalla muestra los resultados del lote procesado y permite exportarlos. "
        "Está organizada en cinco bloques:"
    )
    st.sidebar.markdown(
        "**1 · Resumen del lote** — cuántas muestras se procesaron, "
        "cuántas tienen discordancia y cuáles quedaron sin correspondencia.\n\n"
        "**2 · Tabla de muestras** — vista detallada por muestra con los valores IHQ y MMT "
        "y el resultado de concordancia para cada biomarcador.\n\n"
        "**3 · Descargas Excel** — dos opciones: tabla técnica plana o informe de concordancia "
        "con dashboard y gráficos (Kappa, McNemar, curvas ROC).\n\n"
        "**4 · Informes PDF** — genera un PDF clínico por muestra o un ZIP con todos los del lote.\n\n"
        "**5 · Sincronización** — exporta el lote como paquete ZIP para transferirlo al equipo principal "
        "si se ha trabajado desde un equipo secundario."
    )
    st.sidebar.info(
        "💡 El informe de concordancia (Excel, bloque 3) incluye métricas estadísticas: "
        "% de concordancia, Kappa de Cohen, McNemar, sensibilidad, especificidad, VPP y VPN."
    )


def _guia_historico() -> None:
    """Guía contextual para el Histórico."""
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<div class="guia-titulo">📁 Histórico de muestras</div>'
        '<div class="guia-tag">Estás aquí</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "El histórico acumula **todas las muestras procesadas** desde que se instaló la aplicación, "
        "no solo las del último lote."
    )
    st.sidebar.markdown(
        "Desde aquí puedes:\n"
        "- **Filtrar** por fecha, sample_id, resultado de biomarcador o discordancia.\n"
        "- **Consultar** el detalle de cada muestra individual.\n"
        "- **Exportar** el histórico completo a Excel.\n"
        "- Ver las **muestras sin correspondencia** (bases no cruzadas) registradas en lotes anteriores."
    )
    st.sidebar.caption(
        "En la demo, el histórico solo contendrá las muestras que hayas procesado en esta sesión, "
        "ya que la base de datos es independiente y empieza vacía."
    )


def _guia_estadistico() -> None:
    """Guía contextual para el módulo estadístico."""
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<div class="guia-titulo">📈 Estadísticas globales</div>'
        '<div class="guia-tag">Estás aquí</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "Este módulo analiza el **conjunto completo de muestras acumuladas** en la base de datos, "
        "no solo el último lote. Está orientado a evaluar el rendimiento diagnóstico del kit "
        "MammaTyper® frente a la IHQ estándar."
    )
    st.sidebar.markdown(
        "Para cada biomarcador (ESR1, PGR, ERBB2, MKI67) calcula:\n"
        "- **% de concordancia** global entre IHQ y RT-qPCR.\n"
        "- **Kappa de Cohen** con intervalo de confianza al 95 %.\n"
        "- **Test de McNemar** para detectar sesgo sistemático.\n"
        "- **Sensibilidad, Especificidad, VPP y VPN** tomando IHQ como referencia.\n"
        "- **OR diagnóstico** y tendencia de discordancia (IHQ+ → MMT- o IHQ- → MMT+)."
    )
    st.sidebar.info(
        "💡 La interpretación automática (veredicto) indica si el acuerdo es "
        "excelente, bueno, moderado o débil, y advierte si hay sesgo sistemático "
        "detectable por McNemar."
    )
    st.sidebar.caption(
        "Se recomienda tener al menos 30 muestras para que las métricas estadísticas "
        "sean fiables. Con pocos casos, los resultados se muestran con aviso de muestra reducida."
    )


def _guia_ajustes() -> None:
    """Guía contextual para Ajustes."""
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<div class="guia-titulo">⚙️ Ajustes</div>'
        '<div class="guia-tag">Estás aquí</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "El panel de ajustes permite configurar la aplicación sin tocar el código. "
        "Está organizado en pestañas:"
    )
    st.sidebar.markdown(
        "**Clínico** — umbrales de positividad para cada biomarcador (por defecto según fabricante).\n\n"
        "**App** — comportamiento general: validación estricta, nombre del centro, idioma.\n\n"
        "**Exportación** — plantilla de nombre para los ZIPs de sincronización y otras opciones.\n\n"
        "**Usuarios** — gestión de cuentas: crear usuarios, asignar roles (básico / jefe / admin), "
        "activar o desactivar accesos.\n\n"
        "**Importar / Exportar** — importar paquetes ZIP de traspaso desde equipos secundarios "
        "e importar/exportar la base de datos completa.\n\n"
        "**Auditoría** — registro de todas las acciones realizadas en la app (logins, procesados, exportaciones)."
    )
    st.sidebar.warning(
        "⚠️ En la demo tienes rol admin, así que puedes explorar todas las pestañas. "
        "En producción, solo los administradores acceden a Usuarios y Auditoría."
    )


def _guia_general() -> None:
    """Guía genérica cuando no hay sección activa identificada."""
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<div class="guia-titulo">🧭 Guía de la demo</div>',
        unsafe_allow_html=True,
    )
    with st.sidebar.expander("¿Qué es MammaScope?", expanded=True):
        st.markdown(
            "MammaScope es una plataforma clínica que cruza datos del sistema "
            "histopatológico **PatWin** (Excel IHQ) con los resultados moleculares del "
            "kit diagnóstico **MammaTyper®** (PDF RT-qPCR), detectando automáticamente "
            "discordancias en la clasificación molecular de tumores de mama."
        )
    with st.sidebar.expander("Flujo recomendado", expanded=False):
        st.markdown(
            "1. Descarga los archivos demo desde la portada.\n"
            "2. Ve a **Paso 1** y súbelos.\n"
            "3. Ve a **Paso 2** y pulsa Procesar.\n"
            "4. Explora los resultados en **Paso 3**.\n"
            "5. Revisa el **Histórico** y las **Estadísticas**."
        )
    st.sidebar.caption("Demo pública · Datos ficticios · Sesión simulada")


def _render_demo_guide() -> None:
    """
    Determina en qué sección está el usuario y muestra la guía contextual correspondiente.

    La sección activa se detecta a partir de:
      - st.session_state["step"]  para el flujo principal (pasos 1-2-3)
      - st.session_state["modo_sidebar"] para las secciones del sidebar (histórico, stats, ajustes)

    Si no se puede determinar, se muestra la guía general.
    """
    step = st.session_state.get("step", 1)
    modo = st.session_state.get("modo_sidebar", "flujo_principal")

    if modo == "historico":
        _guia_historico()
    elif modo == "estadistico":
        _guia_estadistico()
    elif modo == "ajustes":
        _guia_ajustes()
    elif modo == "flujo_principal":
        if step == 1:
            _guia_paso1()
        elif step == 2:
            _guia_paso2()
        elif step == 3:
            _guia_paso3()
        else:
            _guia_general()
    else:
        _guia_general()


def main() -> None:
    """
    Función principal de la demo pública de MammaScope.

    1. Añade la carpeta 'codigo' al path de Python.
    2. Configura una base de datos independiente para la demo.
    3. Muestra el logo, la información introductoria y las descargas.
    4. Inyecta la guía contextual en el sidebar.
    5. Ejecuta la aplicación real.
    """

    # Configuración general de la página
    st.set_page_config(
        page_title="MammaScope Demo",
        page_icon=str(ROOT / "codigo" / "logo.png"),
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
            3) Procesa el lote y revisa los resultados en el Paso 3.<br>
            4) Explora el Histórico y las Estadísticas desde el menú lateral.
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
                    Informe IHQ ficticio con resultados de ER, PR, HER2 y Ki-67
                    para cargar en el Paso 1. Incluye un caso con discordancia intencionada.
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
                <h4>PDF de demostración (MammaTyper®)</h4>
                <p>
                    Informe RT-qPCR ficticio simplificado con los mismos casos del Excel.
                    Permite comprobar el cruce por sample_id y la detección de discordancias.
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
    # Guía contextual en el sidebar (se actualiza con cada interacción)
    # ---------------------------------------------------------------------
    _render_demo_guide()

    # ---------------------------------------------------------------------
    # Pie del sidebar: badge de demo
    # ---------------------------------------------------------------------
    st.sidebar.markdown("---")
    st.sidebar.caption("🟡 Demo pública · Datos ficticios · Sesión simulada (rol admin)")

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