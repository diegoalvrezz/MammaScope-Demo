# vista_estadistico.py
"""
Módulo estadístico de MammaScope.

Contiene la lógica de visualización y el motor interpretativo del módulo
estadístico global de la aplicación. Fue extraído de app.py para mantener
el orquestador principal limpio, siguiendo el mismo patrón que
vista_historico.py y vista_procesamiento.py.

Expone:
    mostrar_estadistico() — función principal, llamada desde app.py.
"""

import io
import math
import sqlite3

import pandas as pd
import streamlit as st

from db import DB_PATH
from ajustes import load_settings
from stats_biomarcadores import build_stats_table_from_df


def _generar_veredicto(row: dict) -> tuple[str, str]:
    """
    Genera un veredicto legible y un detalle técnico para un biomarcador
    a partir de sus métricas estadísticas.

    Parámetros
    ----------
    row : dict
        Fila del DataFrame stats con todas las métricas de un biomarcador.

    Retorna
    -------
    tuple (veredicto: str, detalle: str)
        veredicto — texto claro para personal especializado.
        detalle   — texto técnico con los valores usados para la interpretación.
    """
    import math

    bm         = row.get("Biomarcador", "")
    n          = row.get("N", 0)
    kappa      = row.get("Kappa")
    ic_inf     = row.get("Kappa_IC95_inf")
    ic_sup     = row.get("Kappa_IC95_sup")
    concord    = row.get("%Concord")
    mcnemar_p  = row.get("McNemar_p")
    sens       = row.get("Sensibilidad")
    espec      = row.get("Especificidad")
    vpp        = row.get("VPP")
    vpn        = row.get("VPN")
    or_diag    = row.get("OR_diagnostico")
    b          = row.get("b(IHQ+->MMT-)", 0)
    c          = row.get("c(IHQ-->MMT+)", 0)
    tendencia  = row.get("Tendencia", "")
    aviso_n    = row.get("Aviso_N", "")

    def _isnan(v):
        try:
            return v is None or math.isnan(float(v))
        except Exception:
            return True

    def _fmt(v, dec=2):
        return f"{round(float(v), dec)}" if not _isnan(v) else "NC"

    def _pct(v):
        return f"{round(float(v) * 100, 1)}%" if not _isnan(v) else "NC"

    n_reducido = int(n) < 30

    # -----------------------------------------------------------------------
    # Clasificación del Kappa
    # -----------------------------------------------------------------------
    if _isnan(kappa):
        kappa_nivel = "no calculable"
        kappa_texto = "El Kappa no pudo calcularse, probablemente por ausencia de variabilidad en alguna categoría."
    else:
        k = float(kappa)
        if k < 0:
            kappa_nivel = "negativo"
            kappa_texto = (
                f"El Kappa es negativo ({_fmt(k)}), lo que indica que MammaTyper y la IHQ "
                "coinciden menos de lo que lo harían por puro azar para este marcador. "
                "Esto puede deberse al tamaño reducido de la muestra o a una discordancia sistemática real."
            )
        elif k < 0.20:
            kappa_nivel = "pobre"
            kappa_texto = (
                f"El Kappa es muy bajo ({_fmt(k)}), indicando acuerdo pobre entre MammaTyper e IHQ. "
                "La coincidencia entre métodos apenas supera el nivel del azar."
            )
        elif k < 0.40:
            kappa_nivel = "débil"
            kappa_texto = (
                f"El Kappa de {_fmt(k)} refleja un acuerdo débil entre métodos. "
                "Existe cierta coincidencia, pero las discrepancias son frecuentes y no pueden ignorarse."
            )
        elif k < 0.60:
            kappa_nivel = "moderado"
            kappa_texto = (
                f"El Kappa de {_fmt(k)} indica un acuerdo moderado. "
                "Los métodos coinciden con una frecuencia razonable, aunque se registran discordancias notables "
                "que requieren atención clínica."
            )
        elif k < 0.80:
            kappa_nivel = "bueno"
            kappa_texto = (
                f"El Kappa de {_fmt(k)} refleja un buen acuerdo entre MammaTyper e IHQ. "
                "Ambos métodos coinciden de forma consistente para este marcador."
            )
        else:
            kappa_nivel = "muy bueno"
            kappa_texto = (
                f"El Kappa de {_fmt(k)} indica un acuerdo muy bueno, próximo al ideal. "
                "MammaTyper y la IHQ son altamente concordantes para este marcador."
            )

    # -----------------------------------------------------------------------
    # IC del Kappa
    # -----------------------------------------------------------------------
    if not _isnan(ic_inf) and not _isnan(ic_sup):
        ic_texto = f"IC 95%: [{_fmt(ic_inf)} – {_fmt(ic_sup)}]."
        ic_ancho = float(ic_sup) - float(ic_inf)
        if ic_ancho > 1.0:
            ic_comentario = " El intervalo es muy amplio, lo que refleja alta incertidumbre en la estimación."
        elif ic_ancho > 0.5:
            ic_comentario = " El intervalo es moderadamente amplio; los resultados deben interpretarse con precaución."
        else:
            ic_comentario = " El intervalo es estrecho, lo que indica una estimación relativamente precisa."
        ic_texto += ic_comentario
    else:
        ic_texto = "El intervalo de confianza del Kappa no pudo calcularse."

    # -----------------------------------------------------------------------
    # Sensibilidad
    # -----------------------------------------------------------------------
    if _isnan(sens):
        sens_texto = "La sensibilidad no pudo calcularse."
    else:
        s = float(sens)
        if s >= 0.90:
            sens_texto = f"La sensibilidad es muy alta ({_pct(s)}): MammaTyper detecta correctamente la gran mayoría de los casos positivos por IHQ."
        elif s >= 0.80:
            sens_texto = f"La sensibilidad es alta ({_pct(s)}): MammaTyper identifica bien los casos positivos, con una tasa de falsos negativos baja."
        elif s >= 0.60:
            sens_texto = f"La sensibilidad es moderada ({_pct(s)}): MammaTyper pierde una proporción no despreciable de casos positivos por IHQ."
        else:
            sens_texto = f"La sensibilidad es baja ({_pct(s)}): MammaTyper deja sin detectar una parte importante de los casos que la IHQ considera positivos."

    # -----------------------------------------------------------------------
    # Especificidad
    # -----------------------------------------------------------------------
    if _isnan(espec):
        espec_texto = "La especificidad no pudo calcularse."
    else:
        e = float(espec)
        if e >= 0.90:
            espec_texto = f"La especificidad es muy alta ({_pct(e)}): MammaTyper clasifica correctamente casi todos los casos negativos."
        elif e >= 0.80:
            espec_texto = f"La especificidad es alta ({_pct(e)}): la tasa de falsos positivos es baja."
        elif e >= 0.60:
            espec_texto = f"La especificidad es moderada ({_pct(e)}): se registran falsos positivos en una proporción relevante."
        else:
            espec_texto = f"La especificidad es baja ({_pct(e)}): MammaTyper genera un número elevado de falsos positivos para este marcador."

    # -----------------------------------------------------------------------
    # VPP y VPN
    # -----------------------------------------------------------------------
    if not _isnan(vpp) and not _isnan(vpn):
        vpp_vpn_texto = (
            f"El VPP ({_pct(vpp)}) indica que cuando MammaTyper da positivo para este marcador, "
            f"{'la probabilidad de que IHQ coincida es muy alta' if float(vpp) >= 0.85 else 'existe un margen de discrepancia con IHQ que conviene considerar'}. "
            f"El VPN ({_pct(vpn)}) "
            f"{'es igualmente sólido, respaldando los negativos de MammaTyper' if float(vpn) >= 0.85 else 'muestra que los negativos de MammaTyper deben verificarse en algunos casos'}."
        )
    else:
        vpp_vpn_texto = "Los valores predictivos no pudieron calcularse."

    # -----------------------------------------------------------------------
    # OR diagnóstico
    # -----------------------------------------------------------------------
    if _isnan(or_diag):
        or_texto = (
            "El Odds Ratio diagnóstico no es calculable, lo que habitualmente indica que "
            "alguna celda de la matriz de confusión (FP o FN) es cero, reflejo de una concordancia casi perfecta en esa categoría."
        )
    else:
        orv = float(or_diag)
        if orv >= 20:
            or_texto = f"El OR diagnóstico es muy elevado ({_fmt(or_diag)}), indicando una excelente capacidad discriminativa de MammaTyper para este marcador."
        elif orv >= 9:
            or_texto = f"El OR diagnóstico ({_fmt(or_diag)}) refleja una buena capacidad discriminativa."
        elif orv >= 4:
            or_texto = f"El OR diagnóstico ({_fmt(or_diag)}) es moderado: MammaTyper discrimina mejor que el azar, aunque con margen de mejora."
        elif orv > 1:
            or_texto = f"El OR diagnóstico ({_fmt(or_diag)}) es bajo pero positivo: MammaTyper discrimina ligeramente mejor que el azar."
        else:
            or_texto = f"El OR diagnóstico ({_fmt(or_diag)}) es igual o inferior a 1, lo que indica que MammaTyper no mejora la clasificación respecto al azar para este marcador."

    # -----------------------------------------------------------------------
    # McNemar y tendencia
    # -----------------------------------------------------------------------
    if _isnan(mcnemar_p):
        mcnemar_texto = "El test de McNemar no pudo calcularse."
        sesgo = False
    else:
        mp = float(mcnemar_p)
        sesgo = mp < 0.05
        if sesgo:
            if "+" in tendencia:
                mcnemar_texto = (
                    f"El test de McNemar resulta significativo (p={_fmt(mp, 4)}), detectando un sesgo sistemático: "
                    "MammaTyper tiende a clasificar como positivo casos que la IHQ considera negativos. "
                    "Esto implica una sobredetección relativa que debería tenerse en cuenta clínicamente."
                )
            elif "-" in tendencia:
                mcnemar_texto = (
                    f"El test de McNemar resulta significativo (p={_fmt(mp, 4)}), detectando un sesgo sistemático: "
                    "MammaTyper tiende a clasificar como negativo casos que la IHQ considera positivos. "
                    "Esto implica una infradetección relativa que podría tener repercusión clínica."
                )
            else:
                mcnemar_texto = (
                    f"El test de McNemar resulta significativo (p={_fmt(mp, 4)}), indicando asimetría "
                    "en las discordancias. Se recomienda revisar la dirección del sesgo."
                )
        else:
            mcnemar_texto = (
                f"El test de McNemar no detecta sesgo sistemático (p={_fmt(mp, 4)}): "
                "las discordancias entre MammaTyper e IHQ son simétricas, sin un patrón "
                "consistente en ninguna dirección."
            )

    # -----------------------------------------------------------------------
    # Nota N reducido
    # -----------------------------------------------------------------------
    nota_n = (
        f" IMPORTANTE: El análisis se basa en {int(n)} casos, por debajo del umbral recomendado (n=30). "
        "Todos los estadísticos tienen valor exploratorio y deben interpretarse con cautela hasta disponer de una muestra mayor."
        if n_reducido else ""
    )

    # -----------------------------------------------------------------------
    # Veredicto global
    # -----------------------------------------------------------------------
    if _isnan(kappa) or int(n) == 0:
        veredicto = (
            f"No es posible emitir un veredicto para {bm} por ausencia de datos suficientes "
            "o imposibilidad de calcular las métricas principales."
        )
    else:
        k = float(kappa)

        if kappa_nivel in ("muy bueno", "bueno") and not sesgo:
            veredicto = (
                f"MammaTyper muestra una concordancia {kappa_nivel} con la IHQ para {bm} "
                f"(Kappa={_fmt(k)}, concordancia del {_fmt(concord)}%). "
                "No se detecta ningún sesgo sistemático en las discordancias. "
                f"El rendimiento diagnóstico es satisfactorio para este marcador.{nota_n}"
            )
        elif kappa_nivel in ("muy bueno", "bueno") and sesgo:
            veredicto = (
                f"La concordancia global entre MammaTyper e IHQ para {bm} es {kappa_nivel} "
                f"(Kappa={_fmt(k)}), pero se detecta un sesgo sistemático significativo "
                f"(McNemar p={_fmt(float(mcnemar_p), 4)}). "
                "Aunque el acuerdo global es elevado, la dirección de las discordancias "
                f"({tendencia.lower()}) requiere atención clínica.{nota_n}"
            )
        elif kappa_nivel == "moderado" and not sesgo:
            veredicto = (
                f"MammaTyper presenta una concordancia moderada con la IHQ para {bm} "
                f"(Kappa={_fmt(k)}, concordancia del {_fmt(concord)}%). "
                "Las discordancias no siguen un patrón sistemático, pero su frecuencia "
                "aconseja complementar los resultados de MammaTyper con la valoración clínica "
                f"para este marcador.{nota_n}"
            )
        elif kappa_nivel == "moderado" and sesgo:
            veredicto = (
                f"La concordancia entre MammaTyper e IHQ para {bm} es moderada "
                f"(Kappa={_fmt(k)}) y además se detecta un sesgo sistemático "
                f"(McNemar p={_fmt(float(mcnemar_p), 4)}, {tendencia.lower()}). "
                "Se recomienda revisar los resultados de MammaTyper para este marcador "
                f"con especial atención a la dirección de las discordancias.{nota_n}"
            )
        elif kappa_nivel in ("débil", "pobre", "negativo") and not sesgo:
            veredicto = (
                f"La concordancia entre MammaTyper e IHQ para {bm} es {kappa_nivel} "
                f"(Kappa={_fmt(k)}, concordancia del {_fmt(concord)}%). "
                "Aunque no se detecta sesgo sistemático, la elevada frecuencia de discordancias "
                "limita la fiabilidad de MammaTyper como sustituto de la IHQ para este marcador "
                f"con los datos disponibles.{nota_n}"
            )
        else:
            veredicto = (
                f"La concordancia entre MammaTyper e IHQ para {bm} es {kappa_nivel} "
                f"(Kappa={_fmt(k)}) y se detecta un sesgo sistemático significativo "
                f"(McNemar p={_fmt(float(mcnemar_p), 4)}, {tendencia.lower()}). "
                "Los resultados de MammaTyper para este marcador deben interpretarse con "
                f"precaución y siempre en el contexto clínico completo.{nota_n}"
            )

    # -----------------------------------------------------------------------
    # Detalle técnico
    # -----------------------------------------------------------------------
    detalle = (
        f"**Concordancia observada:** {_fmt(concord)}% sobre {int(n)} casos válidos.\n\n"
        f"**Kappa de Cohen:** {_fmt(kappa)} ({kappa_nivel}). {ic_texto}\n\n"
        f"**Sensibilidad:** {_pct(sens)} | **Especificidad:** {_pct(espec)}\n\n"
        f"**VPP:** {_pct(vpp)} | **VPN:** {_pct(vpn)}\n\n"
        f"**OR diagnóstico:** {_fmt(or_diag)}\n\n"
        f"**McNemar p-valor:** {_fmt(mcnemar_p, 4)} | **Tendencia:** {tendencia}\n\n"
        f"**Discordancias:** b={int(b)} (IHQ+/MMT–) | c={int(c)} (IHQ–/MMT+)\n\n"
        f"{kappa_texto}\n\n"
        f"{sens_texto}\n\n"
        f"{espec_texto}\n\n"
        f"{vpp_vpn_texto}\n\n"
        f"{or_texto}\n\n"
        f"{mcnemar_texto}"
        + (f"\n\n**Nota sobre N reducido:** {nota_n.strip()}" if n_reducido else "")
    )

    return veredicto, detalle


def mostrar_resumen_interpretativo(stats: "pd.DataFrame"):
    """
    Sección de resumen interpretativo automático por biomarcador.
    Se añade al final de mostrar_estadistico(), justo antes del cierre.

    Para cada biomarcador genera:
    - Un veredicto claro en lenguaje especializado pero accesible.
    - Un desplegable con el detalle técnico de los estadísticos usados.
    """
    import streamlit as st

    st.markdown("---")
    st.subheader("Resumen interpretativo por biomarcador")
    st.caption(
        "Veredicto automático generado a partir de los estadísticos calculados. "
        "Cada marcador incluye un juicio clínico directo y un desplegable con el detalle técnico que lo sustenta."
    )

    colores_bm = {
        "ER (ESR1)":    "#2196F3",
        "PR (PGR)":     "#4CAF50",
        "HER2 (ERBB2)": "#FF9800",
        "Ki-67 (MKI67)":"#9C27B0",
    }

    for _, row in stats.iterrows():
        bm = row.get("Biomarcador", "")
        color = colores_bm.get(bm, "#607D8B")
        veredicto, detalle = _generar_veredicto(row.to_dict())

        # Cabecera del biomarcador con color
        st.markdown(
            f"<div style='border-left: 5px solid {color}; padding-left: 12px; margin-bottom: 4px;'>"
            f"<span style='font-size: 1.05em; font-weight: bold; color: {color};'>{bm}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Veredicto principal
        st.info(veredicto)

        # Detalle técnico desplegable
        with st.expander("Ver detalle estadístico", expanded=False):
            st.markdown(detalle)

        st.markdown("")


def mostrar_estadistico():
    """
    Módulo estadístico global de la aplicación.

    Muestra métricas de concordancia acumuladas sobre toda la base de datos,
    con explicaciones detalladas de cada estadístico, su equivalencia en R
    y visualizaciones interactivas.
    Orientado a roles jefe/admin para análisis y defensa metodológica.
    """
    import plotly.graph_objects as go
    import plotly.express as px

    st.header(
        "Módulo estadístico",
        help="Métricas de concordancia IHQ vs MammaTyper® sobre la base de datos completa."
    )

    st.markdown(
        "Este módulo calcula métricas de concordancia diagnóstica entre la "
        "inmunohistoquímica (IHQ) y el test molecular MammaTyper® sobre el total "
        "de casos emparejados almacenados en la base de datos. "
        "Todos los estadísticos son metodológicamente equivalentes a los paquetes "
        "de R `psych`, `epiR` e `irr`, implementados en Python por razones de "
        "despliegue en entorno hospitalario."
    )

    st.info(
        "Cada sección incluye una explicación desplegable con dos niveles: "
        "uno técnico para personal con formación estadística y uno clínico "
        "para quien prefiera una lectura más directa y sin tecnicismos."
    )

    # --------------------------------------------------
    # Carga de datos
    # --------------------------------------------------
    try:
        conn = sqlite3.connect(DB_PATH)
        df_all = pd.read_sql_query(
            """
            SELECT
                sample_id,
                ESR1_IHQ, ESR1_status,
                PGR_IHQ,  PGR_status,
                HER2_final, ERBB2_status,
                KI67_IHQ, MKI67_status
            FROM muestras;
            """,
            conn,
        )
        conn.close()
    except Exception as e:
        st.error(f"Error al conectar con la base de datos: {e}")
        return

    if df_all.empty:
        st.info("La tabla de muestras está vacía. Procesa al menos un lote para ver estadísticas.")
        return

    n_total = df_all["sample_id"].nunique()
    st.metric("Casos emparejados en la base de datos", n_total)

    if n_total < 30:
        st.warning(
            f"La base de datos contiene {n_total} casos, por debajo del umbral recomendado (n=30). "
            "Los estadísticos mostrados tienen valor exploratorio y deben interpretarse con cautela."
        )

    ki67_cutoff = float(
        load_settings().get("clinico", {}).get("ki67_cutoff_ihq", 20.0)
    )
    stats = build_stats_table_from_df(df_all, ki67_cutoff_ihq=ki67_cutoff)

    # Helper para mostrar los dos niveles dentro de cada expander
    def _doble_nivel(tecnico: str, clinico: str):
        tab_tec, tab_cli = st.tabs(["Explicacion tecnica", "Explicacion para personal clinico"])
        with tab_tec:
            st.markdown(tecnico)
        with tab_cli:
            st.markdown(clinico)

    st.markdown("---")

    # --------------------------------------------------
    # Tabla completa
    # --------------------------------------------------
    st.subheader("Tabla de métricas por biomarcador")
    st.caption(
        "Cutoff Ki-67 IHQ: 20% (criterio St. Gallen). "
        "IHQ se toma como referencia; MammaTyper® como test a evaluar."
    )

    with st.expander("Leyenda de columnas de la tabla", expanded=False):
        st.markdown(
            "| Columna | Significado |\n"
            "|---|---|\n"
            "| **N** | Número de casos con ambos valores disponibles (IHQ y MMT) |\n"
            "| **TP** | Verdadero Positivo: IHQ positivo y MMT positivo |\n"
            "| **TN** | Verdadero Negativo: IHQ negativo y MMT negativo |\n"
            "| **FP** | Falso Positivo: IHQ negativo pero MMT positivo |\n"
            "| **FN** | Falso Negativo: IHQ positivo pero MMT negativo |\n"
            "| **%Concord** | Porcentaje de casos en que IHQ y MMT coinciden |\n"
            "| **Kappa** | Acuerdo entre métodos ajustado por azar (0=azar, 1=acuerdo perfecto) |\n"
            "| **Kappa_IC95_inf / sup** | Límites inferior y superior del IC 95% del Kappa |\n"
            "| **McNemar_p** | p-valor del test de McNemar (p<0.05 indica sesgo sistemático) |\n"
            "| **Sensibilidad** | Proporción de positivos IHQ detectados correctamente por MMT |\n"
            "| **Especificidad** | Proporción de negativos IHQ clasificados correctamente por MMT |\n"
            "| **VPP** | Valor Predictivo Positivo: probabilidad de que un positivo MMT sea positivo por IHQ |\n"
            "| **VPN** | Valor Predictivo Negativo: probabilidad de que un negativo MMT sea negativo por IHQ |\n"
            "| **OR_diagnostico** | Odds Ratio diagnóstico: capacidad discriminativa global de MMT respecto a IHQ |\n"
            "| **b** | Casos IHQ positivo y MMT negativo (infradetección de MMT) |\n"
            "| **c** | Casos IHQ negativo y MMT positivo (sobredetección de MMT) |\n"
            "| **Tendencia** | Dirección predominante de las discordancias |\n"
        )

    with st.expander("Interpretacion de la tabla", expanded=False):
        _doble_nivel(
            tecnico=(
                "La tabla resume los conteos de la matriz de confusion (TP, TN, FP, FN) "
                "y todas las métricas derivadas por biomarcador. "
                "IHQ actua como referencia y MammaTyper® como test a evaluar.\n\n"
                "- Los valores de Kappa, Sensibilidad, Especificidad, VPP y VPN se expresan en escala 0-1.\n"
                "- El IC 95% del Kappa se calcula con la formula de Fleiss (1981).\n"
                "- McNemar_p indica si las discordancias son simetricas o existe sesgo sistematico.\n\n"
                "*Equivalentes en R: psych::cohen.kappa(), epiR::epi.tests(), mcnemar.test()*"
            ),
            clinico=(
                "Esta tabla reune en un solo lugar todos los resultados del analisis. "
                "Cada fila corresponde a un marcador tumoral (ER, PR, HER2, Ki-67) y "
                "cada columna muestra una medida diferente de cuan bien coinciden "
                "MammaTyper® y el análisis de laboratorio.\n\n"
                "No es necesario entender todas las columnas a la vez. "
                "Las secciones siguientes explican cada medida de forma independiente."
            ),
        )

    stats_display = stats.drop(columns=["Aviso_N"], errors="ignore")
    st.dataframe(stats_display, use_container_width=True)

    buf_stats = io.BytesIO()
    with pd.ExcelWriter(
        buf_stats,
        engine="xlsxwriter",
        engine_kwargs={"options": {"nan_inf_to_errors": True}},
    ) as writer:
        stats.to_excel(writer, index=False, sheet_name="estadisticas_globales")
    buf_stats.seek(0)
    st.download_button(
        label="Descargar estadísticas globales (Excel)",
        data=buf_stats,
        file_name="estadisticas_globales_acumuladas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="estadistico_dl_global",
    )

    st.markdown("---")

    # --------------------------------------------------
    # VISUALIZACIÓN 1: Heatmaps de matriz de confusión
    # --------------------------------------------------
    st.subheader("Matrices de confusion por biomarcador")
    st.caption(
        "Cada celda muestra el número de casos. "
        "Filas: resultado IHQ (referencia). Columnas: resultado MammaTyper®."
    )

    biomarcadores_list = list(stats.iterrows())
    for fila in range(0, len(biomarcadores_list), 2):
        cols_hm = st.columns(2)
        for col_idx, (i, row) in enumerate(biomarcadores_list[fila:fila + 2]):
            bm = row["Biomarcador"]
            tp = int(row["TP"])
            tn = int(row["TN"])
            fp = int(row["FP"])
            fn = int(row["FN"])

            z = [[tp, fn], [fp, tn]]
            text = [[str(tp), str(fn)], [str(fp), str(tn)]]
            x_labels = ["MMT Positivo", "MMT Negativo"]
            y_labels = ["IHQ Positivo", "IHQ Negativo"]

            fig = go.Figure(data=go.Heatmap(
                z=z,
                x=x_labels,
                y=y_labels,
                text=text,
                texttemplate="%{text}",
                textfont={"size": 20},
                colorscale="Blues",
                showscale=False,
            ))
            fig.update_layout(
                title=dict(text=bm, font=dict(size=14)),
                margin=dict(l=20, r=20, t=50, b=20),
                height=280,
                xaxis=dict(side="bottom", tickfont=dict(size=12)),
                yaxis=dict(tickfont=dict(size=12)),
            )

            with cols_hm[col_idx]:
                st.plotly_chart(fig, use_container_width=True)

    with st.expander("Interpretacion de las matrices de confusion", expanded=False):
        _doble_nivel(
            tecnico=(
                "La matriz de confusion clasifica cada muestra segun el acuerdo o discrepancia "
                "entre IHQ (referencia) y MammaTyper® (test):\n\n"
                "- **TP (Verdadero Positivo):** ambos metodos detectan el marcador como positivo.\n"
                "- **TN (Verdadero Negativo):** ambos metodos detectan el marcador como negativo.\n"
                "- **FP (Falso Positivo):** MammaTyper® positivo, IHQ negativo.\n"
                "- **FN (Falso Negativo):** MammaTyper® negativo, IHQ positivo.\n\n"
                "Una matriz con valores altos en la diagonal principal (TP y TN) "
                "indica alta concordancia entre métodos."
            ),
            clinico=(
                "Estos cuadros muestran cuántas veces los dos análisis coinciden o no "
                "para cada marcador tumoral.\n\n"
                "- Las celdas más oscuras indican mayor número de casos.\n"
                "- Los valores en la diagonal (arriba-izquierda y abajo-derecha) son los casos "
                "en que ambos métodos coinciden. Cuanto mayores, mejor.\n"
                "- Los valores fuera de la diagonal son las discrepancias entre métodos."
            ),
        )

    st.markdown("---")

    # --------------------------------------------------
    # VISUALIZACIÓN 2: Kappa con IC 95%
    # --------------------------------------------------
    st.subheader("Kappa de Cohen con intervalo de confianza al 95%")
    st.caption(
        "Las barras de error representan el IC 95% calculado con la formula de Fleiss. "
        "Un IC amplio indica alta incertidumbre, habitual con muestras pequeñas. "
        "Equivalente a psych::cohen.kappa() en R."
    )

    df_kappa = stats[["Biomarcador", "Kappa", "Kappa_IC95_inf", "Kappa_IC95_sup"]].dropna()

    if not df_kappa.empty:
        fig_kappa = go.Figure()

        fig_kappa.add_trace(go.Bar(
            x=df_kappa["Biomarcador"],
            y=df_kappa["Kappa"],
            error_y=dict(
                type="data",
                symmetric=False,
                array=(df_kappa["Kappa_IC95_sup"] - df_kappa["Kappa"]).tolist(),
                arrayminus=(df_kappa["Kappa"] - df_kappa["Kappa_IC95_inf"]).tolist(),
                color="#333333",
                thickness=2,
                width=6,
            ),
            marker_color=["#2196F3", "#4CAF50", "#FF9800", "#9C27B0"],
            text=df_kappa["Kappa"].round(3).astype(str),
            textposition="outside",
        ))

        for y_val, label in [
            (0.20, "Pobre/Debil"),
            (0.40, "Debil/Moderado"),
            (0.60, "Moderado/Bueno"),
            (0.80, "Bueno/Muy bueno"),
        ]:
            fig_kappa.add_hline(
                y=y_val,
                line_dash="dot",
                line_color="gray",
                annotation_text=label,
                annotation_position="right",
                annotation_font_size=10,
            )

        fig_kappa.update_layout(
            yaxis=dict(title="Kappa", range=[-0.1, 1.1]),
            xaxis=dict(title="Biomarcador"),
            height=420,
            margin=dict(l=20, r=120, t=20, b=20),
            showlegend=False,
        )
        st.plotly_chart(fig_kappa, use_container_width=True)
    else:
        st.info("No hay datos suficientes para mostrar el gráfico de Kappa.")

    with st.expander("Interpretacion del Kappa de Cohen", expanded=False):
        _doble_nivel(
            tecnico=(
                "Mide el acuerdo entre IHQ y MammaTyper® descontando el acuerdo esperado por azar:\n\n"
                "> k = (po - pe) / (1 - pe)\n\n"
                "**Interpretacion orientativa:**\n"
                "- < 0.20: acuerdo pobre\n"
                "- 0.21 - 0.40: acuerdo debil\n"
                "- 0.41 - 0.60: acuerdo moderado\n"
                "- 0.61 - 0.80: acuerdo bueno\n"
                "- > 0.80: acuerdo muy bueno\n\n"
                "El IC 95% se calcula con la formula de Fleiss (1981). "
                "Un IC amplio refleja incertidumbre, especialmente con muestras pequeñas.\n\n"
                "*Equivalente en R: psych::cohen.kappa()*"
            ),
            clinico=(
                "El Kappa mide si los dos métodos coinciden más de lo que lo harían por pura casualidad.\n\n"
                "- Un Kappa de 0 significa que el acuerdo es puro azar.\n"
                "- Un Kappa de 1 significa acuerdo perfecto en todos los casos.\n\n"
                "**Como leer el gráfico:**\n"
                "- Las barras más altas indican mejor acuerdo para ese marcador.\n"
                "- Las líneas de error muestran el margen de incertidumbre: "
                "si son muy largas, se necesitan más casos para confirmar el resultado.\n"
                "- Las líneas horizontales punteadas indican los umbrales de interpretación."
            ),
        )

    st.markdown("---")

    # --------------------------------------------------
    # VISUALIZACIÓN 3: Radar Sensibilidad/Especificidad/VPP/VPN
    # --------------------------------------------------
    st.subheader("Perfil diagnostico por biomarcador (grafico radar)")
    st.caption(
        "Comparacion de Sensibilidad, Especificidad, VPP y VPN para cada biomarcador. "
        "Los valores se expresan en tanto por uno (0-1). "
        "Equivalente a epiR::epi.tests() en R."
    )

    metricas_radar = ["Sensibilidad", "Especificidad", "VPP", "VPN"]
    df_radar = stats[["Biomarcador"] + metricas_radar].dropna()

    if not df_radar.empty:
        colores_radar = ["#2196F3", "#4CAF50", "#FF9800", "#9C27B0"]
        fig_radar = go.Figure()

        for i, (_, row) in enumerate(df_radar.iterrows()):
            valores = [row[m] for m in metricas_radar]
            valores_cierre = valores + [valores[0]]
            categorias = metricas_radar + [metricas_radar[0]]

            fig_radar.add_trace(go.Scatterpolar(
                r=valores_cierre,
                theta=categorias,
                fill="toself",
                name=row["Biomarcador"],
                line_color=colores_radar[i % len(colores_radar)],
                opacity=0.6,
            ))

        fig_radar.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 1],
                    tickformat=".0%",
                )
            ),
            legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
            height=450,
            margin=dict(l=40, r=40, t=20, b=60),
        )
        st.plotly_chart(fig_radar, use_container_width=True)
    else:
        st.info("No hay datos suficientes para mostrar el gráfico radar.")

    with st.expander("Interpretacion del perfil diagnostico", expanded=False):
        _doble_nivel(
            tecnico=(
                "El gráfico radar representa simultaneamente cuatro metricas de rendimiento "
                "diagnostico para cada biomarcador:\n\n"
                "- **Sensibilidad** = TP / (TP + FN): proporcion de positivos IHQ detectados por MMT.\n"
                "- **Especificidad** = TN / (TN + FP): proporcion de negativos IHQ clasificados por MMT.\n"
                "- **VPP** = TP / (TP + FP): probabilidad de positivo real dado positivo MMT.\n"
                "- **VPN** = TN / (TN + FN): probabilidad de negativo real dado negativo MMT.\n\n"
                "Un poligono mas grande y mas regular indica mejor rendimiento diagnostico global.\n\n"
                "*Equivalente en R: epiR::epi.tests()*"
            ),
            clinico=(
                "Este gráfico de tela de araña muestra de un vistazo si MammaTyper® "
                "funciona bien para cada marcador en cuatro aspectos distintos:\n\n"
                "- **Sensibilidad:** no pierde casos positivos.\n"
                "- **Especificidad:** no confunde negativos con positivos.\n"
                "- **VPP:** cuando da positivo, suele acertar.\n"
                "- **VPN:** cuando da negativo, suele acertar.\n\n"
                "Cuanto más grande y equilibrado sea el polígono de un marcador, "
                "mejor funciona MammaTyper® para ese marcador en conjunto."
            ),
        )

    st.markdown("---")

    # --------------------------------------------------
    # VISUALIZACIÓN 4: Discordancias b y c
    # --------------------------------------------------
    st.subheader("Direccion de las discordancias (b y c)")
    st.caption(
        "b = IHQ positivo, MammaTyper negativo (infradeteccion por MMT). "
        "c = IHQ negativo, MammaTyper positivo (sobredeteccion por MMT). "
        "Un desequilibrio entre b y c indica sesgo sistematico."
    )

    df_disc = stats[["Biomarcador", "b(IHQ+->MMT-)", "c(IHQ-->MMT+)"]].copy()
    df_disc = df_disc.rename(columns={
        "b(IHQ+->MMT-)": "b (IHQ+ / MMT-)",
        "c(IHQ-->MMT+)": "c (IHQ- / MMT+)",
    })

    fig_disc = go.Figure()
    fig_disc.add_trace(go.Bar(
        name="b: IHQ+ / MMT-",
        x=df_disc["Biomarcador"],
        y=df_disc["b (IHQ+ / MMT-)"],
        marker_color="#EF5350",
        text=df_disc["b (IHQ+ / MMT-)"],
        textposition="outside",
    ))
    fig_disc.add_trace(go.Bar(
        name="c: IHQ- / MMT+",
        x=df_disc["Biomarcador"],
        y=df_disc["c (IHQ- / MMT+)"],
        marker_color="#42A5F5",
        text=df_disc["c (IHQ- / MMT+)"],
        textposition="outside",
    ))

    fig_disc.update_layout(
        barmode="group",
        yaxis=dict(title="Número de casos"),
        xaxis=dict(title="Biomarcador"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
        height=380,
        margin=dict(l=20, r=20, t=20, b=60),
    )
    st.plotly_chart(fig_disc, use_container_width=True)

    with st.expander("Interpretacion de las discordancias", expanded=False):
        _doble_nivel(
            tecnico=(
                "Las barras b y c representan las discordancias asimétricas entre métodos:\n\n"
                "- **b** (rojo): IHQ positivo, MMT negativo. MammaTyper® infradetecta.\n"
                "- **c** (azul): IHQ negativo, MMT positivo. MammaTyper® sobredetecta.\n\n"
                "Si b > c: MMT tiende a clasificar como negativo respecto a IHQ.\n"
                "Si c > b: MMT tiende a clasificar como positivo respecto a IHQ.\n"
                "Si b = c: discordancias simetricas, sin sesgo sistematico.\n\n"
                "El test de McNemar evalua formalmente si esta asimetria es estadisticamente significativa."
            ),
            clinico=(
                "Este gráfico muestra en qué dirección se producen las diferencias "
                "entre MammaTyper® y el análisis de laboratorio:\n\n"
                "- Las **barras rojas** (b) son los casos en que el laboratorio dice positivo "
                "pero MammaTyper® dice negativo.\n"
                "- Las **barras azules** (c) son los casos en que MammaTyper® dice positivo "
                "pero el laboratorio dice negativo.\n\n"
                "Si un color domina claramente sobre el otro en un marcador, "
                "significa que MammaTyper® tiende a equivocarse siempre en la misma dirección "
                "para ese marcador, lo que merece atención clínica."
            ),
        )

    st.markdown("---")

    # --------------------------------------------------
    # VISUALIZACIÓN 5: McNemar coloreado
    # --------------------------------------------------
    st.subheader("Significacion estadistica del test de McNemar")
    st.caption(
        "p < 0.05 indica asimetria significativa en las discordancias: "
        "MammaTyper® tiende sistematicamente a clasificar de forma diferente a IHQ. "
        "Equivalente a mcnemar.test(correct=TRUE) en R."
    )

    df_mc = stats[["Biomarcador", "McNemar_p", "Tendencia"]].copy()
    df_mc["Significacion"] = df_mc["McNemar_p"].apply(
        lambda p: "p < 0.05 (significativo)" if (not pd.isna(p) and p < 0.05)
        else ("p >= 0.05 (no significativo)" if not pd.isna(p) else "Sin datos")
    )
    df_mc["Color"] = df_mc["McNemar_p"].apply(
        lambda p: "#EF9A9A" if (not pd.isna(p) and p < 0.05)
        else ("#A5D6A7" if not pd.isna(p) else "#E0E0E0")
    )

    fig_mc = go.Figure(data=[go.Table(
        header=dict(
            values=["Biomarcador", "McNemar p-valor", "Significacion", "Tendencia"],
            fill_color="#1565C0",
            font=dict(color="white", size=12),
            align="center",
            height=32,
        ),
        cells=dict(
            values=[
                df_mc["Biomarcador"].tolist(),
                df_mc["McNemar_p"].round(6).astype(str).tolist(),
                df_mc["Significacion"].tolist(),
                df_mc["Tendencia"].tolist(),
            ],
            fill_color=[
                ["#F5F5F5"] * len(df_mc),
                ["#F5F5F5"] * len(df_mc),
                df_mc["Color"].tolist(),
                ["#F5F5F5"] * len(df_mc),
            ],
            align="center",
            font=dict(size=12),
            height=28,
        ),
    )])

    fig_mc.update_layout(
        height=220,
        margin=dict(l=0, r=0, t=10, b=10),
    )
    st.plotly_chart(fig_mc, use_container_width=True)

    with st.expander("Interpretacion del test de McNemar", expanded=False):
        _doble_nivel(
            tecnico=(
                "Evalua si las discordancias entre IHQ y MammaTyper® son simetricas "
                "o si existe una tendencia sistematica:\n\n"
                "- **p < 0.05** (rojo): asimetria significativa. Un metodo tiende a clasificar "
                "de forma diferente al otro de manera sistematica.\n"
                "- **p >= 0.05** (verde): discordancias simetricas, sin tendencia sistematica.\n\n"
                "Test exacto binomial si n=b+c < 25; chi-cuadrado con correccion de "
                "continuidad si n >= 25.\n\n"
                "*Equivalente en R: mcnemar.test(correct=TRUE)*"
            ),
            clinico=(
                "Esta tabla resume si las diferencias entre MammaTyper® y el laboratorio "
                "siguen un patrón o son aleatorias:\n\n"
                "- **Celda en rojo (p < 0.05):** hay un patrón claro. MammaTyper® tiende "
                "sistemáticamente a dar un resultado diferente al laboratorio para ese marcador. "
                "Conviene revisar por qué ocurre.\n\n"
                "- **Celda en verde (p >= 0.05):** no hay un patrón definido. "
                "Cuando los métodos difieren, es de forma aleatoria, sin tendencia fija.\n\n"
                "La columna Tendencia indica si MammaTyper® tiende a dar más positivos o "
                "más negativos que el laboratorio cuando discrepan."
            ),
        )

    st.markdown("---")

    # --------------------------------------------------
    # Nota sobre N reducido
    # --------------------------------------------------
    with st.expander("Nota sobre N reducido y fiabilidad de los resultados", expanded=False):
        _doble_nivel(
            tecnico=(
                "Cuando el numero de casos es inferior a 30, los estadisticos presentan "
                "alta variabilidad muestral:\n\n"
                "- El **Kappa** puede fluctuar considerablemente con un solo caso diferente "
                "y su IC sera muy amplio.\n"
                "- El **test de McNemar** con pocas discordancias produce p-valores poco informativos.\n"
                "- **Sensibilidad, Especificidad, VPP y VPN** pueden ser inestables si alguna "
                "celda de la matriz de confusion tiene valores muy bajos.\n\n"
                "En estos casos los resultados deben considerarse exploratorios y no concluyentes."
            ),
            clinico=(
                "Cuando hay pocos pacientes en la base de datos (menos de 30), "
                "los resultados estadísticos son menos fiables.\n\n"
                "Es como intentar sacar conclusiones de un estudio con muy poca gente: "
                "los números pueden cambiar mucho si se añaden o quitan unos pocos casos.\n\n"
                "A medida que se procesen más pacientes, los resultados serán más robustos "
                "y podrán interpretarse con mayor confianza."
            ),
            
        )
    mostrar_resumen_interpretativo(stats)