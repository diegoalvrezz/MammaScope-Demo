import re
import io
import random
from pathlib import Path

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ======================
# CONFIG
# ======================
SEED = 123
N_TOTAL = 300
N_OK = 100
N_VAR = 100
N_BAD = 100

BASE_DIR = Path(__file__).resolve().parent
IN_IHQ = BASE_DIR / "ENVIO_IHQ.xlsx"     # tu excel real de entrada IHQ
OUT_IHQ = BASE_DIR / "IHQ_mock_300_realista.xlsx"
OUT_PDF = BASE_DIR / "MMT_mock_300_parser.pdf"

random.seed(SEED)

# ======================
# Utils
# ======================
SAMPLE_ID_RE = re.compile(r"\b\d{2}[A-Z]\d{5}\b")  # 25B77777
BIOPSIA_RE = re.compile(r"(BIOPSIA\s*:\s*)(\d{2}[A-Z]\d{5})", re.IGNORECASE)

KI67_RE = re.compile(r"(Ki\s*-\s*67\s*:\s*)(\d{1,3})\s*%?", re.IGNORECASE)

# ER / PR (muy conservador: solo sustituye "POSITIVOS/NEGATIVOS" en frases que contengan esos términos)
ER_LINE_RE = re.compile(r"(ESTROGENOS\s*:\s*)(POSITIVOS?|NEGATIVOS?)", re.IGNORECASE)
PR_LINE_RE = re.compile(r"(PROGESTERONA\s*:\s*)(POSITIVOS?|NEGATIVOS?)", re.IGNORECASE)

# HER2 (en tu texto aparece como "HER-2" o "HER2", con variantes low/ultralow/equivoco/++)
HER2_LINE_RE = re.compile(r"(HER[\-\s]*2\s*:\s*)(.*?)(?=(Ki\s*-\s*67|CK[\-\s]*19|Burgos|Fdo|$))", re.IGNORECASE | re.DOTALL)

def make_sample_id(i: int) -> str:
    dd = 10 + (i % 90)       # 10..99
    tail = 10000 + (i % 90000)  # 10000..99999
    return f"{dd:02d}B{tail:05d}"

def pick_ki67_ok() -> int:
    return random.choice([4, 10, 15, 20, 25, 30, 40, 50, 60])

def pick_ki67_var() -> str:
    v = pick_ki67_ok()
    # Variaciones que siguen siendo parseables por tu regex
    return random.choice([f"{v}%", f"{v} %", f" {v}% ", f"{v}"])

def pick_ki67_bad() -> str:
    # Rompe patrón
    return random.choice(["veinte%", "??", "", "2000%", "NaN", "x%"])

def flip_pos_neg(word: str) -> str:
    w = word.strip().lower()
    if "neg" in w:
        return "POSITIVOS"
    return "NEGATIVOS"

def her2_ok_chunk() -> str:
    # Mantiene expresiones realistas en castellano como en tus ejemplos
    return random.choice([
        "NEGATIVO (HER-2 LOW/+).",
        "NEGATIVO (ULTRA LOW).",
        "equívoco (++).",
        "POSITIVO (3+).",
        "amplificado.",
    ])

def her2_var_chunk() -> str:
    return random.choice([
        "Negativo (HER2 LOW/+).",
        "NEGATIVO (+; HER2 LOW).",
        "Equívoco ( ++ ).",
        "positivo (3+).",
        "NEGATIVO (ULTRALOW).",
        "NEGATIVO (low).",
    ])

def her2_bad_chunk() -> str:
    # Para romper parseos típicos
    return random.choice([
        "", "???", "score: three", "2plus", "HER2 maybe", "ultra-low??", "++++"
    ])

def apply_replacements(text: str, new_sid: str, mode: str) -> str:
    """
    mode: OK / VAR / BAD
    Mantiene el texto casi idéntico, tocando solo patrones (sample_id, ER/PR/HER2/Ki67)
    y ANONIMIZA firmas de médicos (Fdo./Firmado).
    """
    if not isinstance(text, str) or not text.strip():
        return text

    out = text

    # ======================
    # Anonimización médicos
    # ======================
    NOMBRES = [
        "Laura", "Marta", "Elena", "Claudia", "Ana", "María",
        "Carlos", "Javier", "David", "Pablo", "Álvaro", "Sergio",
        "Lucía", "Paula", "Irene", "Raúl", "Hugo", "Diego"
    ]
    APELLIDOS = [
        "García", "Fernández", "López", "Martínez", "Sánchez",
        "Pérez", "Gómez", "Ruiz", "Díaz", "Hernández",
        "Navarro", "Romero", "Torres", "Vega", "Ortega"
    ]

    def medico_aleatorio() -> str:
        # "Dra." si nombre típicamente femenino, si no "Dr."
        nombre = random.choice(NOMBRES)
        pref = "Dra." if nombre in {"Laura","Marta","Elena","Claudia","Ana","María","Lucía","Paula","Irene"} else "Dr."
        return f"{pref} {nombre} {random.choice(APELLIDOS)}"

    # Variantes frecuentes de firma al final
    FDO_RE = re.compile(r"(Fdo\.?\s*:?\s*)(.*)$", re.IGNORECASE)
    FIRMADO_RE = re.compile(r"(Firmado\s*:?\s*)(.*)$", re.IGNORECASE)

    # Burgos a, 10/10/25 (si quieres también randomizar fecha, lo hacemos)
    BURGOS_RE = re.compile(r"(Burgos\s+a,?\s*)(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", re.IGNORECASE)

    def fecha_random(_: re.Match) -> str:
        d = random.randint(1, 28)
        m = random.randint(1, 12)
        y = random.choice([2024, 2025, 2026])
        return f"Burgos a, {d:02d}/{m:02d}/{str(y)[-2:]}"

    # ======================
    # 1) Reemplazar sample_id
    # ======================
    if BIOPSIA_RE.search(out):
        # lambda para evitar el bug de "\1" + dígitos (invalid group reference)
        out = BIOPSIA_RE.sub(lambda m: m.group(1) + new_sid, out)
    else:
        # Si no aparece literal "BIOPSIA:", reemplaza cualquier sample_id existente por el nuevo (primer match)
        out = SAMPLE_ID_RE.sub(new_sid, out, count=1)
    out = re.sub(
        r"(BIOPSIA\s*:\s*)([^\s\)]+)",
        lambda m: m.group(1) + new_sid,
        out,
        count=1,
        flags=re.IGNORECASE,
    )
    # ======================
    # 2) ER / PR
    # ======================
    if mode == "OK":
        out = ER_LINE_RE.sub(lambda m: m.group(1) + random.choice(["POSITIVOS", "NEGATIVOS"]), out)
        out = PR_LINE_RE.sub(lambda m: m.group(1) + random.choice(["POSITIVOS", "NEGATIVOS"]), out)

    elif mode == "VAR":
        def _var_word():
            base = random.choice(["POSITIVOS", "NEGATIVOS"])
            return random.choice([base, base.lower(), f" {base} ", base.capitalize()])
        out = ER_LINE_RE.sub(lambda m: m.group(1) + _var_word(), out)
        out = PR_LINE_RE.sub(lambda m: m.group(1) + _var_word(), out)

    else:  # BAD
        out = ER_LINE_RE.sub(lambda m: m.group(1) + random.choice(["POSI TIVOS", "NEGATIV", "??", ""]), out)
        out = PR_LINE_RE.sub(lambda m: m.group(1) + random.choice(["POS", "NEG-", "N/A", ""]), out)

    # ======================
    # 3) HER2
    # ======================
    def _her2_repl(m):
        prefix = m.group(1)
        if mode == "OK":
            return prefix + her2_ok_chunk() + " "
        if mode == "VAR":
            return prefix + her2_var_chunk() + " "
        return prefix + her2_bad_chunk() + " "

    out = HER2_LINE_RE.sub(_her2_repl, out)

    # ======================
    # 4) Ki-67
    # ======================
    def _ki_repl(m):
        prefix = m.group(1)
        if mode == "OK":
            return prefix + f"{pick_ki67_ok()}% "
        if mode == "VAR":
            return prefix + f"{pick_ki67_var()} "
        return prefix + f"{pick_ki67_bad()} "

    out = KI67_RE.sub(_ki_repl, out)

    # ======================
    # 5) Anonimizar médicos / fecha al final
    # ======================
    out = FDO_RE.sub(lambda m: m.group(1) + medico_aleatorio(), out)
    out = FIRMADO_RE.sub(lambda m: m.group(1) + medico_aleatorio(), out)
    out = BURGOS_RE.sub(fecha_random, out)
    
    return out



def find_text_column(df: pd.DataFrame) -> int:
    """
    Detecta la columna “narrativa” por CONTENIDO de celdas.
    Requiere df leído con header=None.
    Devuelve el índice de columna (int).
    """
    candidates = []
    for col in df.columns:
        s = df[col].astype(str)
        score = (
            s.str.contains("ESTUDIO REALIZADO", case=False, na=False).mean()
            + s.str.contains("BIOPSIA", case=False, na=False).mean()
            + s.str.contains("RECEPTORES", case=False, na=False).mean()
        )
        candidates.append((score, col))

    candidates.sort(reverse=True, key=lambda x: x[0])
    best_score, best_col = candidates[0]
    if best_score < 0.3:
        print(f"⚠️ Aviso: columna narrativa no muy clara. Mejor candidata: col={best_col} (score={best_score:.2f})")
    return int(best_col)


def build_ihq_mock_realista():
    if not IN_IHQ.exists():
        raise FileNotFoundError(f"No encuentro {IN_IHQ} en {BASE_DIR}")

    # Leer sin cabecera (tu archivo original no tiene header real)
    df_real = pd.read_excel(IN_IHQ, header=None)

    if df_real.empty:
        raise ValueError("ENVIO_IHQ.xlsx está vacío")

    text_col = find_text_column(df_real)
    print(f"✅ Columna narrativa detectada (índice): {text_col}")

    # -----------------------------
    # 1) Quedarnos SOLO con filas-caso
    # -----------------------------
    s = df_real.iloc[:, text_col].astype(str)
    mask_case = s.str.contains("ESTUDIO REALIZADO", case=False, na=False) & s.str.contains("BIOPSIA", case=False, na=False)
    df_cases = df_real[mask_case].copy()

    if df_cases.empty:
        # fallback si por lo que sea no detecta con esos dos tokens
        mask_case = s.str.contains("BIOPSIA", case=False, na=False)
        df_cases = df_real[mask_case].copy()

    if df_cases.empty:
        raise ValueError(
            "No se han detectado filas-caso (con 'ESTUDIO REALIZADO'/'BIOPSIA') en la columna narrativa. "
            "Revisa find_text_column() o el Excel de entrada."
        )

    print(f"✅ Filas-caso detectadas en el Excel real: {len(df_cases)}")

    # -----------------------------
    # 2) Construir 300 casos duplicando SOLO df_cases
    # -----------------------------
    df = pd.concat([df_cases] * ((N_TOTAL // len(df_cases)) + 1), ignore_index=True).iloc[:N_TOTAL].copy()

    # IDs nuevos (válidos siempre) para emparejar con el PDF
    sample_ids = [make_sample_id(i) for i in range(1, N_TOTAL + 1)]

    # -----------------------------
    # 3) Replacements SOLO en la celda narrativa de cada caso
    # -----------------------------
    for i in range(N_TOTAL):
        if i < N_OK:
            mode = "OK"
        elif i < N_OK + N_VAR:
            mode = "VAR"
        else:
            mode = "BAD"

        sid = sample_ids[i]
        original = df.iat[i, text_col]
        df.iat[i, text_col] = apply_replacements(str(original), sid, mode)

        # En BAD, si quieres provocar "no match" por extractor, rompe el ID SOLO dentro del texto
        if mode == "BAD" and (i % 4 == 0):
            df.iat[i, text_col] = SAMPLE_ID_RE.sub(f"XX{i:05d}", str(df.iat[i, text_col]), count=1)

    # Guardar como matriz sin cabecera
    df.to_excel(OUT_IHQ, index=False, header=False)
    print(f"✅ Excel IHQ mock PERFECTO creado: {OUT_IHQ}")

    return sample_ids



def build_mmt_pdf_parser(sample_ids: list[str]):
    c = canvas.Canvas(str(OUT_PDF), pagesize=A4)
    w, h = A4

    def draw_case(idx: int, sid: str, mode: str):
        y = h - 60
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, "MammaTyper® Report (MOCK DEBUG)"); y -= 24
        c.setFont("Helvetica", 11)
        c.drawString(50, y, f"Sample ID: {sid}"); y -= 18
        c.drawString(50, y, "Gene   Value   Status"); y -= 18

        def line(gene, value, status):
            nonlocal y
            c.drawString(50, y, f"{gene:<6}  {value:<8}  {status}")
            y -= 14

        def st_ok():
            return random.choice(["Positive", "Negative"])

        def st_var():
            return random.choice(["Positive", "Negative", "positive", "negative", " POSITIVE ", "neg"])

        def st_bad():
            return random.choice(["", "??", "N/A", "equivocal", "posi tive", "----"])

        if mode == "OK":
            esr1 = st_ok(); pgr = st_ok(); mki67 = st_ok()
            erbb2 = random.choice(["low", "zero", "ultra low", "negative", "positive"])
        elif mode == "VAR":
            esr1 = st_var(); pgr = st_var(); mki67 = st_var()
            erbb2 = random.choice([" Low ", "ZERO", "ultra low", "NEGATIVE", "POSITIVE", "pos", "neg"])
        else:
            esr1 = st_bad(); pgr = st_bad(); mki67 = st_bad()
            erbb2 = random.choice(["", "???", "low??", "superpositive", None])

        def val_for(status, gene):
            s = (status or "").strip().lower()
            if "pos" in s:
                return f"{random.uniform(36.3, 38.0):.2f}" if gene == "MKI67" else f"{random.uniform(38.0, 41.0):.2f}"
            if "neg" in s or "low" in s or "zero" in s or "ultra" in s:
                return f"{random.uniform(34.5, 36.2):.2f}" if gene == "MKI67" else f"{random.uniform(36.0, 39.9):.2f}"
            return f"{random.uniform(30.0, 45.0):.2f}"

        line("ESR1",  val_for(esr1, "ESR1"),  esr1 or "")
        line("PGR",   val_for(pgr, "PGR"),   pgr or "")
        line("ERBB2", val_for(erbb2 or "", "ERBB2"), (erbb2 or ""))
        line("MKI67", val_for(mki67, "MKI67"), mki67 or "")

        c.setFont("Helvetica-Oblique", 9)
        c.drawString(50, 40, f"MOCK DEBUG · Caso {idx+1}/{len(sample_ids)} · Bloque: {mode}")

    for i, sid in enumerate(sample_ids):
        if i < N_OK:
            mode = "OK"
        elif i < N_OK + N_VAR:
            mode = "VAR"
        else:
            mode = "BAD"

        draw_case(i, sid, mode)
        c.showPage()

    c.save()
    print(f"✅ PDF MMT mock (parser) creado: {OUT_PDF}")


if __name__ == "__main__":
    sids = build_ihq_mock_realista()

    # ✅ PDF: SIEMPRE usa los sample_id válidos generados (nunca BAD1, BAD2...)
    build_mmt_pdf_parser(sids)

    print("✅ Listo. Usa estos archivos en tu app:")
    print(f"   - {OUT_IHQ.name}")
    print(f"   - {OUT_PDF.name}")