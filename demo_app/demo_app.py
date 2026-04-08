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
    """Devuelve el contenido binario de un archivo para download_button."""
    return path.read_bytes()


def _ensure_demo_session() -> None:
    """
    Fuerza una sesión autenticada simulada para la demo.
    Rol admin para permitir la navegación completa sin modificar el código original.
    """
    if st.session_state.get("auth_ok") and st.session_state.get("user"):
        return
    st.session_state["user"] = {"username": "demo", "role": "admin"}
    st.session_state["auth_ok"] = True


def _inject_demo_styles() -> None:
    """Inyecta los estilos CSS necesarios para la portada y la guía del sidebar."""
    st.markdown(
        """
        <style>
        /* ── Portada ── */
        .bloque-demo {
            background-color: #f8fafc;
            border: 1px solid #e5e7eb;
            border-radius: 18px;
            padding: 1.4rem 1.4rem 1.2rem 1.4rem;
            margin-bottom: 1.5rem;
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
            min-height: 160px;
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
            background-color: #f0f9ff;
            border: 1px solid #bae6fd;
            border-radius: 14px;
            padding: 0.9rem 1rem;
            color: #0c4a6e;
            margin-bottom: 1rem;
            font-size: 0.97rem;
        }

        /* ── Separador entre portada y app ── */
        .separador-app {
            background: linear-gradient(90deg, #2563eb 0%, #7c3aed 100%);
            color: white;
            border-radius: 14px;
            padding: 0.75rem 1.2rem;
            font-size: 1.1rem;
            font-weight: 700;
            text-align: center;
            margin-top: 0.5rem;
            margin-bottom: 1.5rem;
            letter-spacing: 0.02em;
        }

        /* ── Guía sidebar ── */
        .guia-seccion {
            font-size: 1rem;
            font-weight: 700;
            color: #1e3a5f;
            margin-bottom: 0.15rem;
        }
        .guia-badge {
            display: inline-block;
            background: #dbeafe;
            color: #1d4ed8;
            border-radius: 8px;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.08rem 0.5rem;
            margin-bottom: 0.6rem;
        }
        .guia-badge-warn {
            display: inline-block;
            background: #fef9c3;
            color: #854d0e;
            border-radius: 8px;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.08rem 0.5rem;
            margin-bottom: 0.4rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# -------------------------------------------------------------------------
# Guías contextuales del sidebar — una por sección
# -------------------------------------------------------------------------

def _guia_paso1() -> None:
    st.sidebar.markdown(
        '<p class="guia-seccion">🗂️ Paso 1 · Carga de archivos</p>'
        '<span class="guia-badge">📍 Estás aquí</span>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "Sube los **dos archivos** necesarios para el análisis. "
        "Puedes descargarlos de ejemplo desde la portada de arriba."
    )
    with st.sidebar.expander("¿Qué es el Excel de PatWin?"):
        st.markdown(
            "Contiene los resultados de la **inmunohistoquímica clásica (IHQ)**: "
            "receptores de estrógeno (ER/ESR1), progesterona (PR/PGR), "
            "HER2 (ERBB2) y proliferación celular Ki-67 (MKI67). "
            "Es el informe exportado del sistema histopatológico PatWin del hospital."
        )
    with st.sidebar.expander("¿Qué es el PDF de MammaTyper®?"):
        st.markdown(
            "Contiene los resultados del kit de diagnóstico molecular **RT-qPCR de Roche**. "
            "Mide la expresión génica de los mismos cuatro biomarcadores directamente "
            "desde el ARN tumoral extraído de la biopsia, de forma cuantitativa."
        )
    st.sidebar.info(
        "💡 Ambos archivos deben compartir los mismos **números de biopsia** "
        "(sample_id) para que el cruce sea posible."
    )


def _guia_paso2() -> None:
    st.sidebar.markdown(
        '<p class="guia-seccion">⚙️ Paso 2 · Procesamiento</p>'
        '<span class="guia-badge">📍 Estás aquí</span>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "Al pulsar **Procesar**, la app ejecuta un pipeline automático de 7 pasos:"
    )
    st.sidebar.markdown(
        "1. Valida el formato del Excel\n"
        "2. Valida el formato del PDF\n"
        "3. Extrae registros IHQ del Excel\n"
        "4. Extrae registros RT-qPCR del PDF\n"
        "5. Cruza ambas fuentes por `sample_id`\n"
        "6. Registra muestras sin correspondencia\n"
        "7. Guarda las muestras fusionadas en BD"
    )
    st.sidebar.warning(
        "⚠️ Si una muestra aparece solo en el Excel o solo en el PDF, "
        "se registra como **base no cruzada** y no entra en el análisis. "
        "En la demo verás un ejemplo de esto."
    )
    st.sidebar.caption(
        "Las discordancias potenciales se detectan automáticamente "
        "y generan un aviso ⚠️ al finalizar."
    )


def _guia_paso3() -> None:
    st.sidebar.markdown(
        '<p class="guia-seccion">📊 Paso 3 · Resultados y exportación</p>'
        '<span class="guia-badge">📍 Estás aquí</span>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown("Esta pantalla tiene **5 bloques**:")
    with st.sidebar.expander("1 · Resumen del lote"):
        st.markdown(
            "Cuántas muestras se procesaron, cuántas tienen discordancia "
            "y cuáles quedaron sin correspondencia entre fuentes."
        )
    with st.sidebar.expander("2 · Tabla de muestras"):
        st.markdown(
            "Vista detallada por muestra con los valores IHQ y MMT "
            "y el resultado de concordancia para cada biomarcador."
        )
    with st.sidebar.expander("3 · Descargas Excel"):
        st.markdown(
            "**Tabla técnica**: datos planos del lote con cabeceras coloreadas "
            "por origen (azul = MMT, amarillo = IHQ).\n\n"
            "**Informe concordancia + dashboard**: Kappa, McNemar, "
            "curvas ROC y tabla de revisión prioritaria."
        )
    with st.sidebar.expander("4 · Informes PDF"):
        st.markdown(
            "Genera un informe clínico PDF por muestra, "
            "o un ZIP con todos los del lote de una vez."
        )
    with st.sidebar.expander("5 · Sincronización"):
        st.markdown(
            "Exporta el lote como paquete ZIP para transferirlo "
            "al equipo principal si se trabajó desde un equipo secundario."
        )


def _guia_historico() -> None:
    st.sidebar.markdown(
        '<p class="guia-seccion">📁 Histórico de muestras</p>'
        '<span class="guia-badge">📍 Estás aquí</span>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "Consulta y filtra **todas las muestras acumuladas** en la base de datos, "
        "no solo las del último lote."
    )
    with st.sidebar.expander("¿Qué puedo hacer aquí?"):
        st.markdown(
            "- Filtrar por fecha, sample_id, resultado o biomarcador\n"
            "- Ver el detalle de cada muestra\n"
            "- Exportar la selección a Excel\n"
            "- Construir consultas avanzadas con hasta 3 filtros combinados"
        )
    st.sidebar.caption(
        "En la demo, el histórico solo contendrá las muestras procesadas "
        "en esta sesión, ya que la BD comienza vacía."
    )


def _guia_bases_no_cruzadas() -> None:
    st.sidebar.markdown(
        '<p class="guia-seccion">🔗 Bases no cruzadas</p>'
        '<span class="guia-badge">📍 Estás aquí</span>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "Muestra los `sample_id` que aparecen en **un solo archivo** "
        "(solo Excel o solo PDF) y no pudieron cruzarse."
    )
    with st.sidebar.expander("¿Por qué ocurre esto?"):
        st.markdown(
            "Las causas más comunes son:\n"
            "- El número de biopsia no coincide exactamente entre ambos archivos\n"
            "- Una muestra se procesó en MammaTyper pero no llegó el informe IHQ\n"
            "- Error de transcripción del sample_id en alguno de los archivos"
        )
    st.sidebar.info(
        "💡 Desde aquí puedes eliminar registros ya resueltos para mantener "
        "limpia la tabla de seguimiento."
    )


def _guia_estadistico() -> None:
    st.sidebar.markdown(
        '<p class="guia-seccion">📈 Estadísticas globales</p>'
        '<span class="guia-badge">📍 Estás aquí</span>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "Evalúa el **rendimiento diagnóstico del kit MammaTyper®** "
        "frente a la IHQ estándar sobre el total de muestras acumuladas."
    )
    with st.sidebar.expander("Métricas calculadas"):
        st.markdown(
            "Para cada biomarcador (ESR1, PGR, ERBB2, MKI67):\n"
            "- **% Concordancia** global IHQ vs RT-qPCR\n"
            "- **Kappa de Cohen** con IC 95 %\n"
            "- **Test de McNemar** (sesgo sistemático)\n"
            "- **Sensibilidad, Especificidad, VPP y VPN**\n"
            "- **OR diagnóstico** y tendencia de discordancia"
        )
    with st.sidebar.expander("¿Qué es el Kappa de Cohen?"):
        st.markdown(
            "Mide el acuerdo entre dos métodos diagnósticos descontando el azar. "
            "Valores orientativos: >0.8 = excelente, 0.6–0.8 = bueno, "
            "0.4–0.6 = moderado, <0.4 = débil."
        )
    st.sidebar.caption(
        "Se recomienda un mínimo de 30 muestras para resultados estadísticamente fiables."
    )


def _guia_ajustes() -> None:
    st.sidebar.markdown(
        '<p class="guia-seccion">⚙️ Ajustes</p>'
        '<span class="guia-badge">📍 Estás aquí</span>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        "Configura la aplicación sin tocar el código. Organizado en pestañas:"
    )
    with st.sidebar.expander("Ver pestañas disponibles"):
        st.markdown(
            "**Clínico** — umbrales de positividad por biomarcador\n\n"
            "**App** — nombre del centro, validación estricta, idioma\n\n"
            "**Exportación** — plantilla de nombre para ZIPs de sincronización\n\n"
            "**Usuarios** — crear cuentas, asignar roles, activar/desactivar accesos\n\n"
            "**Importar/Exportar** — importar paquetes ZIP de equipos secundarios "
            "y exportar/restaurar la BD completa\n\n"
            "**Auditoría** — registro de todas las acciones (logins, procesados, exportaciones)"
        )
    st.sidebar.markdown(
        '<span class="guia-badge-warn">⚠️ Demo</span> '
        "Tienes rol **admin**, así que puedes explorar todas las pestañas. "
        "En producción, Usuarios y Auditoría están restringidos.",
        unsafe_allow_html=True,
    )


def _guia_general() -> None:
    """Guía genérica inicial antes de que el usuario elija sección."""
    st.sidebar.markdown(
        '<p class="guia-seccion">🧭 Guía de la demo</p>',
        unsafe_allow_html=True,
    )
    with st.sidebar.expander("¿Qué es MammaScope?", expanded=True):
        st.markdown(
            "Plataforma clínica que cruza datos del sistema histopatológico "
            "**PatWin** (IHQ) con los resultados moleculares de **MammaTyper®** (RT-qPCR), "
            "detectando automáticamente discordancias en la clasificación "
            "molecular de tumores de mama."
        )
    with st.sidebar.expander("Flujo recomendado"):
        st.markdown(
            "1. Descarga los archivos demo desde la portada\n"
            "2. Súbelos en el **Paso 1**\n"
            "3. Procesa el lote en el **Paso 2**\n"
            "4. Explora resultados en el **Paso 3**\n"
            "5. Revisa el **Histórico** y las **Estadísticas**"
        )


def _render_demo_guide() -> None:
    """
    Muestra la guía contextual correcta en el sidebar según la sección activa.

    Usa st.session_state["modo_uso"] — clave real del radio de app.py —
    y st.session_state["step"] para el flujo principal (pasos 1-2-3).
    """
    # "modo_uso" es exactamente la key= que usa app.py en su st.sidebar.radio
    modo = st.session_state.get("modo_uso", "Flujo principal")
    step = st.session_state.get("step", 1)

    st.sidebar.markdown("---")

    if modo == "Explorar base de datos histórica (SQL)":
        _guia_historico()
    elif modo == "Bases no cruzadas":
        _guia_bases_no_cruzadas()
    elif modo == "Estadístico":
        _guia_estadistico()
    elif modo == "Ajustes":
        _guia_ajustes()
    elif modo == "Flujo principal":
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

    st.sidebar.markdown("---")
    st.sidebar.caption("🟡 Demo pública · Datos ficticios · Sesión simulada (rol admin)")


def main() -> None:
    """
    Función principal de la demo pública de MammaScope.

    1. Configura la página y estilos.
    2. Añade la carpeta 'codigo' al path de Python.
    3. Configura una base de datos independiente para la demo.
    4. Muestra la portada con descargas de archivos de ejemplo.
    5. Separa visualmente la portada de la app real con un banner.
    6. Inyecta la sesión simulada y la guía contextual.
    7. Ejecuta la aplicación real.
    """
    st.set_page_config(
        page_title="MammaScope Demo",
        page_icon=str(ROOT / "codigo" / "logo.png"),
        layout="wide",
    )

    _inject_demo_styles()

    # Permite importar módulos desde la carpeta /codigo
    if str(CODIGO_DIR) not in sys.path:
        sys.path.insert(0, str(CODIGO_DIR))

    # Base de datos aislada para la demo (no modifica la BD real)
    os.environ["TFG_MAMMA_DB_PATH"] = str(ROOT / "demo_app" / "tfg_mamma_demo.db")

    # -------------------------------------------------------------------------
    # PORTADA DE LA DEMO
    # -------------------------------------------------------------------------
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
            <div class="subtitulo-demo">Plataforma clínica para el análisis de concordancia IHQ – MammaTyper®</div>
            <p class="nota-demo">
                Entorno de demostración con archivos ficticios y sesión simulada.
                Explora el flujo completo sin necesidad de iniciar sesión.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.info(
        "**Sobre esta demo:**\n\n"
        "La versión de uso real incluye inicio de sesión, control de permisos por rol "
        "y un entorno de trabajo restringido. Aquí el acceso está simplificado para facilitar la prueba.\n\n"
        "Los archivos de ejemplo contienen **datos ficticios**. El PDF de MammaTyper® ha sido "
        "simplificado para proteger información sensible, manteniendo únicamente los campos "
        "necesarios para la extracción.\n\n"
        "Se ha incluido intencionadamente **un caso de discordancia** para mostrar cómo la "
        "aplicación detecta y gestiona este tipo de situación clínica."
    )

    st.markdown('<div class="seccion-demo">📥 Archivos de demostración</div>', unsafe_allow_html=True)

    st.markdown(
        """
        <div class="pasos-demo">
            <strong>Cómo usar la demo:</strong><br>
            1) Descarga los dos archivos de ejemplo desde aquí.<br>
            2) Desplázate hacia abajo hasta el banner <em>"⬇️ Aplicación · MammaScope"</em>.<br>
            3) En el <strong>Paso 1</strong>, sube ambos archivos.<br>
            4) En el <strong>Paso 2</strong>, pulsa "Procesar" y observa el pipeline.<br>
            5) En el <strong>Paso 3</strong>, revisa resultados y descarga informes.<br>
            6) Explora el <strong>Histórico</strong> y las <strong>Estadísticas</strong> desde el menú lateral.
        </div>
        """,
        unsafe_allow_html=True,
    )

    excel_file = DEMO_FILES / "demo_patwin.xlsx"
    pdf_file = DEMO_FILES / "demo_mammatypper.pdf"

    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.markdown(
            """
            <div class="tarjeta-demo">
                <h4>📊 Excel de demostración (PatWin · IHQ)</h4>
                <p>
                    Informe de inmunohistoquímica con resultados de ER, PR, HER2 y Ki-67
                    para varias muestras ficticias. Incluye un caso con discordancia intencionada.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if excel_file.exists():
            st.download_button(
                label="⬇️ Descargar Excel de demostración",
                data=_read_bytes(excel_file),
                file_name="demo_patwin.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="demo_public_download_excel_patwin",
                use_container_width=True,
            )
        else:
            st.warning("No se encuentra el archivo demo_patwin.xlsx.")

    with col2:
        st.markdown(
            """
            <div class="tarjeta-demo">
                <h4>🧬 PDF de demostración (MammaTyper® · RT-qPCR)</h4>
                <p>
                    Informe RT-qPCR simplificado con los mismos casos del Excel.
                    Permite verificar el cruce por sample_id y la detección de discordancias.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if pdf_file.exists():
            st.download_button(
                label="⬇️ Descargar PDF de demostración",
                data=_read_bytes(pdf_file),
                file_name="demo_mammatypper.pdf",
                mime="application/pdf",
                key="demo_public_download_pdf_mammatypper",
                use_container_width=True,
            )
        else:
            st.warning("No se encuentra el archivo demo_mammatypper.pdf.")

    st.markdown('</div>', unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # SEPARADOR VISUAL entre portada y aplicación real
    # -------------------------------------------------------------------------
    st.markdown(
        '<div class="separador-app">⬇️ Aplicación · MammaScope</div>',
        unsafe_allow_html=True,
    )

    # -------------------------------------------------------------------------
    # Sesión simulada + guía contextual en sidebar
    # La guía se renderiza ANTES de app.main() para que aparezca encima del
    # contenido que app.main() escriba en el sidebar.
    # -------------------------------------------------------------------------
    _ensure_demo_session()
    _render_demo_guide()

    # -------------------------------------------------------------------------
    # Aplicación real (importación tardía tras configurar sys.path y BD)
    # -------------------------------------------------------------------------
    import app
    app.main()


if __name__ == "__main__":
    main()