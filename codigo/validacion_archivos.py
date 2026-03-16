# validacion_archivos.py
import io
from typing import Tuple

import pandas as pd

from extraccion import extraer_registros_pdf, extraer_registros_patwin
from ajustes import load_settings




REQUIRED_COLUMNS_EXCEL = [
    "RONDA",
    "Sample ID",
    "Subtype Info MMT",
    "ERBB2_value",
    "ERBB2_status",
    "ESR1_value",
    "ESR1_status",
    "PGR_value",
    "PGR_status",
    "MKI67_value",
    "MKI67_status",
]


def validar_excel_patwin(excel_bytes: bytes):
    """
    Valida el Excel de Patwin de forma coherente con el pipeline real.
    - Modo normal: basta con que se puedan extraer registros.
    - Modo estricto: además exige que exista un % mínimo de registros con sample_id.
    """
    settings = load_settings()
    try:
        f = io.BytesIO(excel_bytes)


        registros = extraer_registros_patwin(f)

    except Exception as e:
        return False, f"El archivo Excel no se ha podido procesar: {e}"

    if not registros:
        return False, (
            "No se ha podido extraer ninguna muestra del Excel. "
            "¿Es el formato correcto (texto clínico en una columna)?"
        )


    if settings.get("app", {}).get("validacion_estricta", False):
        con_id = sum(1 for r in registros if r.get("sample_id"))
        ratio = con_id / max(1, len(registros))

        if ratio < 0.70:
            return (
                False,
                "Excel no válido (modo estricto): demasiados registros sin Sample ID "
                f"({con_id}/{len(registros)} con ID).",
            )

    return True, f"Excel válido ({len(registros)} muestras detectadas)."



def validar_pdf_mmt(pdf_bytes: bytes) -> Tuple[bool, str]:
    """
    Comprueba que el PDF contiene al menos una muestra MammaTyper válida.
    """
    try:
        f = io.BytesIO(pdf_bytes)
        regs = extraer_registros_pdf(f)
    except Exception as e:
        return False, f"El PDF no se ha podido leer como informe MammaTyper: {e}"

    if not regs:
        return False, "No se ha podido extraer ninguna muestra del PDF. ¿Es el formato correcto?"

    if not any(r.get("sample_id") for r in regs):
        return False, "El PDF no contiene Sample ID reconocibles."

    return True, f"PDF válido ({len(regs)} muestras detectadas)."
