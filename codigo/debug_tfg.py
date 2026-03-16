import pandas as pd

from extraccion import (
    extraer_registros_patwin,
    extraer_registros_pdf,
    fusionar_registro_patwin_pdf,
)

# Rutas de prueba (asegúrate de que estos archivos están en la misma carpeta)
RUTA_EXCEL = r"C:\Users\Diego\Desktop\TFG\simulacro2.xlsx"
RUTA_PDF   = r"C:\Users\Diego\Desktop\TFG\mmt_full.pdf"


def main():
    print("=== TEST 1: Patwin (Excel) ===")
    with open(RUTA_EXCEL, "rb") as f:
        registros_patwin = extraer_registros_patwin(f)

    print(f"Nº de registros extraídos de Patwin: {len(registros_patwin)}")
    for r in registros_patwin:
        print(
            "sample_id:", r.get("sample_id"),
            "| ER_IHQ:", r.get("ESR1_IHQ"),
            "| PR_IHQ:", r.get("PGR_IHQ"),
            "| P53_status:", r.get("P53_IHQ_status"),
            "| P53_pct:", r.get("P53_IHQ_pct"),
            "| CK19:", r.get("CK19_IHQ_status"),
            "| KI67_IHQ:", r.get("KI67_IHQ"),
        )

    print("\n=== TEST 2: MammaTyper (PDF) ===")
    with open(RUTA_PDF, "rb") as f:
        registros_pdf = extraer_registros_pdf(f)

    print(f"Nº de registros extraídos de MMT: {len(registros_pdf)}")
    for r in registros_pdf:
        print(
            "sample_id:", r.get("sample_id"),
            "| subtipo_mmt:", r.get("subtipo_mmt"),
            "| ERBB2_status:", r.get("ERBB2_status"),
            "| ESR1_status:", r.get("ESR1_status"),
            "| PGR_status:", r.get("PGR_status"),
            "| MKI67_status:", r.get("MKI67_status"),
        )

    print("\n=== TEST 3: Fusión Excel + PDF ===")
    combinados = []
    
    for reg_pdf in registros_pdf:
        sid = reg_pdf.get("sample_id")
        if not sid:
            print("PDF sin sample_id, se omite.")
            continue
    
        reg_excel = next((r for r in registros_patwin if r.get("sample_id") == sid), None)
    
        if reg_excel is None:
            print(f"No se encontró Patwin para sample_id {sid}, se omite en el debug.")
            continue
    
        # 👉 AQUÍ EL ORDEN CORRECTO
        combinado = fusionar_registro_patwin_pdf(reg_excel, reg_pdf)
        combinados.append(combinado)
    
        print(
            "\n[Muestra fusionada]",
            "\nsample_id:", combinado.get("sample_id"),
            "\n  ERBB2_value:", combinado.get("ERBB2_value"),
            "\n  ERBB2_status:", combinado.get("ERBB2_status"),
            "\n  ESR1_value:", combinado.get("ESR1_value"),
            "\n  ESR1_status:", combinado.get("ESR1_status"),
            "\n  PGR_value:", combinado.get("PGR_value"),
            "\n  PGR_status:", combinado.get("PGR_status"),
            "\n  MKI67_value:", combinado.get("MKI67_value"),
            "\n  MKI67_status:", combinado.get("MKI67_status"),
            "\n  ESR1_IHQ:", combinado.get("ESR1_IHQ"),
            "\n  PGR_IHQ:", combinado.get("PGR_IHQ"),
            "\n  P53_IHQ_status:", combinado.get("P53_IHQ_status"),
            "\n  P53_IHQ_pct:", combinado.get("P53_IHQ_pct"),
            "\n  CK19_IHQ_status:", combinado.get("CK19_IHQ_status"),
            "\n  KI67_IHQ:", combinado.get("KI67_IHQ"),
            "\n  aviso:", combinado.get("aviso"),
        )


    # Opcional: ver todo en tabla
    df = pd.DataFrame(combinados)
    print("\n=== DATAFRAME FINAL DE PRUEBA ===")
    print(df.head())

if __name__ == "__main__":
    main()
