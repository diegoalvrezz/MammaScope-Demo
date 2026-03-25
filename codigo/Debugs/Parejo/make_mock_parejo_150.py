import re
import random
from pathlib import Path
from typing import List, Tuple, Optional

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ======================
# CONFIG
# ======================
SEED = 123
N_TOTAL = 150

# Tasas de discordancia MMT vs IHQ (realistas / ajustables)
# Ejemplo: 0.08 => 8% de casos con flip (MMT distinto a IHQ) para ese biomarcador
DISCORD_ER = 0.06
DISCORD_PR = 0.10
DISCORD_HER2 = 0.08
DISCORD_KI67 = 0.12

# Cutoff Ki67 (IHQ) para binarizar (tu regla)
KI67_CUTOFF = 20

# Prefijo año + letra fija B (IMPORTANTE: tu extractor actual busca \d{2}B...)
# Si quieres simular 2026 usa "26B". Si tu extractor se rompe, usa "25B".
YEAR_PREFIX = 25  # 25 o 26
LETTER = "B"

BASE_DIR = Path(__file__).resolve().parent
IN_IHQ = BASE_DIR / "ENVIO_IHQ.xlsx"  # plantilla real (para conservar estructura)
OUT_IHQ = BASE_DIR / "IHQ_mock_150_parejo.xlsx"
OUT_PDF = BASE_DIR / "MMT_mock_150_parejo.pdf"

random.seed(SEED)

# ======================
# Regex / patrones
# ======================
SAMPLE_ID_RE = re.compile(r"\b\d{2}B\d{5}\b")  # 25B12345
BIOPSIA_RE = re.compile(r"(BIOPSIA\s*:\s*)([^\s\)]+)", re.IGNORECASE)

# Detectores de bloques a reemplazar (no “perfectos”, pero robustos)
ER_LINE_RE = re.compile(r"(ESTROGENOS\s*:\s*)(.*?)(?=(RECEPTORES\s+DE\s+PROGESTERONA|PROGESTERONA\s*:|FACTORES|P-\s*53|HER[\-\s]*2|Ki\s*-\s*67|CK[\-\s]*19|Burgos|Fdo|$))",
                        re.IGNORECASE | re.DOTALL)
PR_LINE_RE = re.compile(r"(PROGESTERONA\s*:\s*)(.*?)(?=(FACTORES|P-\s*53|HER[\-\s]*2|Ki\s*-\s*67|CK[\-\s]*19|Burgos|Fdo|$))",
                        re.IGNORECASE | re.DOTALL)
HER2_LINE_RE = re.compile(r"(HER[\-\s]*2\s*:\s*)(.*?)(?=(Ki\s*-\s*67|CK[\-\s]*19|Burgos|Fdo|$))",
                          re.IGNORECASE | re.DOTALL)
KI67_RE = re.compile(r"(Ki\s*-\s*67\s*:\s*)(.*?)(?=(CK[\-\s]*19|Burgos|Fdo|$))",
                     re.IGNORECASE | re.DOTALL)

FDO_RE = re.compile(r"(Fdo\.?\s*:?\s*)(.*)$", re.IGNORECASE)
FIRMADO_RE = re.compile(r"(Firmado\s*:?\s*)(.*)$", re.IGNORECASE)
BURGOS_RE = re.compile(r"(Burgos\s+a,?\s*)(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", re.IGNORECASE)

# ======================
# Nombres fake (anonimización)
# ======================
NOMBRES_F = ["Laura", "Marta", "Elena", "Claudia", "Ana", "María", "Lucía", "Paula", "Irene"]
NOMBRES_M = ["Carlos", "Javier", "David", "Pablo", "Álvaro", "Sergio", "Raúl", "Hugo", "Diego"]
APELLIDOS = ["García", "Fernández", "López", "Martínez", "Sánchez", "Pérez", "Gómez", "Ruiz", "Díaz", "Hernández",
             "Navarro", "Romero", "Torres", "Vega", "Ortega"]

def medico_aleatorio() -> str:
    if random.random() < 0.5:
        nombre = random.choice(NOMBRES_F)
        pref = "Dra."
    else:
        nombre = random.choice(NOMBRES_M)
        pref = "Dr."
    return f"{pref} {nombre} {random.choice(APELLIDOS)}"

def fecha_random(_: re.Match) -> str:
    d = random.randint(1, 28)
    m = random.randint(1, 12)
    y = random.choice([2024, 2025, 2026])
    return f"Burgos a, {d:02d}/{m:02d}/{str(y)[-2:]}"

# ======================
# Sample IDs
# ======================
def make_sample_id(i: int) -> str:
    # XXB + 5 dígitos (siempre válido para tu extractor)
    tail = 10000 + i  # asegura 5 dígitos y orden
    return f"{YEAR_PREFIX:02d}{LETTER}{tail:05d}"

# ======================
# Generación de “estado verdadero”
# ======================
def flip_with_prob(val: int, p: float) -> int:
    return 1 - val if random.random() < p else val

def pick_percent_pos(low: int = 1, high: int = 100) -> int:
    # En clínica: ER/PR suelen tener rangos, pero para mock vale
    return random.randint(low, high)

def er_pr_chunk(is_pos: int, pct: int) -> str:
    # Coherente: POSITIVOS con + y %, NEGATIVOS con 0% y sin +
    if is_pos == 1:
        # intensidad simulada
        intensity = random.choice(["(+/+++)", "(++/+++)", "(+++/+++)"])
        return f"POSITIVOS {intensity} en el {pct}% de los núcleos de las células tumorales."
    else:
        return "NEGATIVOS en las células tumorales."

def her2_chunk_ihq(is_pos: int) -> str:
    # Simplificado pero compatible con tus reglas
    if is_pos == 1:
        return random.choice(["POSITIVO (3+).", "amplificado."])
    else:
        return random.choice(["NEGATIVO (HER-2 LOW/+).", "NEGATIVO (ULTRA LOW).", "equívoco (++)."])

def ki67_text(val: int) -> str:
    # Mantener formato clásico: “Ki - 67 : 20%”
    # Nota: si quieres >20 sea “alto”, aquí controlas la distribución.
    return f"{val}%"

def pick_ki67_value(is_high: int) -> int:
    # Controla Ki67 para que binarice con cutoff=20 de forma realista
    if is_high == 1:
        return random.choice([25, 30, 35, 40, 45, 50, 60])
    else:
        return random.choice([4, 8, 10, 12, 15, 18, 20])

# ======================
# MMT: status y valores coherentes con status
# ======================
def mmt_status_from_bin(x: int, var: bool = True) -> str:
    if x == 1:
        base = "Positive"
        return random.choice([base, base.lower(), f" {base} "]) if var else base
    else:
        base = "Negative"
        return random.choice([base, base.lower(), f" {base} "]) if var else base

def mmt_status_erbb2_from_bin(x: int, var: bool = True) -> str:
    # En tu binarización: positive=1; low/zero/ultra/negative=0
    if x == 1:
        base = "positive"
        return random.choice([base, base.upper(), "Positive", " POSITIVE "]) if var else "Positive"
    else:
        base = random.choice(["low", "zero", "ultra low", "negative"])
        return random.choice([base, base.upper(), f" {base} "]) if var else base

def mmt_value_for(gene: str, status: str) -> str:
    s = (status or "").strip().lower()
    # Rangos parecidos a los que ya venías usando en mocks
    if gene == "MKI67":
        if "pos" in s:
            return f"{random.uniform(36.3, 38.0):.2f}"
        if "neg" in s or "low" in s or "zero" in s or "ultra" in s:
            return f"{random.uniform(34.5, 36.2):.2f}"
        return f"{random.uniform(30.0, 45.0):.2f}"
    else:
        if "pos" in s:
            return f"{random.uniform(38.0, 41.0):.2f}"
        if "neg" in s or "low" in s or "zero" in s or "ultra" in s:
            return f"{random.uniform(36.0, 39.9):.2f}"
        return f"{random.uniform(30.0, 45.0):.2f}"

# ======================
# Detectar columna narrativa (header=None)
# ======================
def find_text_col_idx(df: pd.DataFrame) -> int:
    candidates: List[Tuple[float, int]] = []
    for col in df.columns:
        s = df[col].astype(str)
        score = (
            s.str.contains("ESTUDIO REALIZADO", case=False, na=False).mean()
            + s.str.contains("BIOPSIA", case=False, na=False).mean()
            + s.str.contains("RECEPTORES", case=False, na=False).mean()
        )
        candidates.append((score, int(col)))
    candidates.sort(reverse=True, key=lambda x: x[0])
    best_score, best_col = candidates[0]
    if best_score < 0.3:
        print(f"⚠️ Aviso: columna narrativa no muy clara. Mejor candidata: {best_col} (score={best_score:.2f})")
    return best_col

# ======================
# Reescritura controlada del texto narrativo (coherente)
# ======================
def apply_replacements_parejo(text: str, sid: str, er: int, pr: int, her2: int, ki67: int) -> str:
    if not isinstance(text, str) or not text.strip():
        return text

    out = text

    # 1) sample_id (siempre)
    if BIOPSIA_RE.search(out):
        out = BIOPSIA_RE.sub(lambda m: m.group(1) + sid, out, count=1)
    else:
        # si no hay BIOPSIA:, reemplaza el primer 25Bxxxxx que encuentre, y si no existe lo deja
        out = SAMPLE_ID_RE.sub(sid, out, count=1)

    # 2) ER
    er_pct = pick_percent_pos(1, 100) if er == 1 else 0
    out = ER_LINE_RE.sub(lambda m: m.group(1) + er_pr_chunk(er, er_pct) + " ", out, count=1)

    # 3) PR
    pr_pct = pick_percent_pos(1, 100) if pr == 1 else 0
    out = PR_LINE_RE.sub(lambda m: m.group(1) + er_pr_chunk(pr, pr_pct) + " ", out, count=1)

    # 4) HER2
    out = HER2_LINE_RE.sub(lambda m: m.group(1) + her2_chunk_ihq(her2) + " ", out, count=1)

    # 5) Ki67
    out = KI67_RE.sub(lambda m: m.group(1) + ki67_text(ki67) + " ", out, count=1)

    # 6) Anonimización firma/fecha
    out = BURGOS_RE.sub(fecha_random, out)
    out = FDO_RE.sub(lambda m: m.group(1) + medico_aleatorio(), out)
    out = FIRMADO_RE.sub(lambda m: m.group(1) + medico_aleatorio(), out)

    return out

# ======================
# Construcción IHQ + generación de estados “verdaderos”
# ======================
def build_ihq_mock_150_parejo() -> Tuple[List[str], List[dict]]:
    if not IN_IHQ.exists():
        raise FileNotFoundError(f"No encuentro {IN_IHQ} en {BASE_DIR}")

    # Leer como matriz sin cabecera (igual que tu excel real)
    df_real = pd.read_excel(IN_IHQ, header=None)
    if df_real.empty:
        raise ValueError("ENVIO_IHQ.xlsx está vacío")

    text_col = find_text_col_idx(df_real)
    print(f"✅ Columna narrativa detectada (índice): {text_col}")

    # Repetir plantilla real para conservar estructura
    df = pd.concat([df_real] * ((N_TOTAL // len(df_real)) + 1), ignore_index=True).iloc[:N_TOTAL].copy()

    sample_ids = [make_sample_id(i) for i in range(1, N_TOTAL + 1)]

    # Guardamos “verdad” y IHQ para luego construir el PDF coherente
    truth_rows: List[dict] = []

    for i, sid in enumerate(sample_ids):
        # “Estado verdadero” (distribuciones razonables)
        er_true = 1 if random.random() < 0.75 else 0
        pr_true = 1 if random.random() < 0.65 else 0
        her2_true = 1 if random.random() < 0.18 else 0
        ki67_true = 1 if random.random() < 0.45 else 0  # alto vs bajo

        ki67_val = pick_ki67_value(ki67_true)

        original = str(df.iat[i, text_col])
        df.iat[i, text_col] = apply_replacements_parejo(
            original, sid, er_true, pr_true, her2_true, ki67_val
        )

        truth_rows.append({
            "sample_id": sid,
            "ER_IHQ_bin": er_true,
            "PR_IHQ_bin": pr_true,
            "HER2_IHQ_bin": her2_true,
            "KI67_IHQ_value": ki67_val,
            "KI67_IHQ_bin": 1 if ki67_val > KI67_CUTOFF else 0,
        })

    # Guardar sin header, sin índice (como tu real)
    df.to_excel(OUT_IHQ, index=False, header=False)
    print(f"✅ Excel IHQ mock parejo creado: {OUT_IHQ.name}")

    return sample_ids, truth_rows

# ======================
# PDF MMT correlacionado con IHQ (parejo, no idéntico)
# ======================
def build_mmt_pdf_150_parejo(sample_ids: List[str], truth_rows: List[dict]) -> None:
    c = canvas.Canvas(str(OUT_PDF), pagesize=A4)
    w, h = A4

    # Map rápido sid -> truth
    truth = {r["sample_id"]: r for r in truth_rows}

    def draw_case(idx: int, sid: str):
        y = h - 60
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, "MammaTyper® Report (MOCK DEBUG · PAREJO)"); y -= 24
        c.setFont("Helvetica", 11)
        c.drawString(50, y, f"Sample ID: {sid}"); y -= 18
        c.drawString(50, y, "Gene   Value   Status"); y -= 18

        def line(gene: str, value: str, status: str):
            nonlocal y
            c.drawString(50, y, f"{gene:<6}  {value:<8}  {status}")
            y -= 14

        t = truth[sid]

        # MMT bin = IHQ bin con flips controlados
        er_mmt = flip_with_prob(t["ER_IHQ_bin"], DISCORD_ER)
        pr_mmt = flip_with_prob(t["PR_IHQ_bin"], DISCORD_PR)
        her2_mmt = flip_with_prob(t["HER2_IHQ_bin"], DISCORD_HER2)
        ki67_mmt = flip_with_prob(t["KI67_IHQ_bin"], DISCORD_KI67)

        esr1_status = mmt_status_from_bin(er_mmt, var=True)
        pgr_status = mmt_status_from_bin(pr_mmt, var=True)
        erbb2_status = mmt_status_erbb2_from_bin(her2_mmt, var=True)
        mki67_status = mmt_status_from_bin(ki67_mmt, var=True)

        line("ESR1",  mmt_value_for("ESR1", esr1_status),  esr1_status)
        line("PGR",   mmt_value_for("PGR", pgr_status),    pgr_status)
        line("ERBB2", mmt_value_for("ERBB2", erbb2_status), erbb2_status)
        line("MKI67", mmt_value_for("MKI67", mki67_status), mki67_status)

        c.setFont("Helvetica-Oblique", 9)
        c.drawString(50, 40, f"MOCK PAREJO · Caso {idx+1}/{len(sample_ids)}")

    for i, sid in enumerate(sample_ids):
        draw_case(i, sid)
        c.showPage()

    c.save()
    print(f"✅ PDF MMT mock parejo creado: {OUT_PDF.name}")

# ======================
# MAIN
# ======================
if __name__ == "__main__":
    sids, truth_rows = build_ihq_mock_150_parejo()
    build_mmt_pdf_150_parejo(sids, truth_rows)

    print("\n✅ Listo. Usa estos archivos en tu app:")
    print(f"   - {OUT_IHQ.name}")
    print(f"   - {OUT_PDF.name}")
    print("\nNotas:")
    print(" - Este mock está diseñado para que el cruce sea 150/150 (todos tienen Sample ID detectable).")
    print(" - Las discordancias son bajas y controladas (ajustables con DISCORD_*).")
