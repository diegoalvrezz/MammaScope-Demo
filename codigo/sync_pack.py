# sync_pack.py
"""
Empaquetado y sincronización de lotes (sin exponer la BD completa)

Objetivo
--------
Permitir “exportar” un conjunto de muestras (lote) en un ZIP autocontenido
y “reimportarlo” en otra instalación de la app, insertando SOLO las muestras
que no existen todavía (modo insert-only).

Qué incluye el ZIP
------------------
- delta.json: payload con metadatos + lista de muestras (dicts) tal como se insertan en SQLite.
- manifest.json: manifiesto con:
    - recuento de muestras
    - hash SHA256 de delta.json (integridad)
    - meta adicional (opcional)
    - lista de archivos extra incluidos (opcional)

Reglas de importación
---------------------
- Se verifica integridad: SHA256(delta.json) debe coincidir con manifest.json.
- Se inserta una muestra SOLO si su sample_id NO existe ya en la tabla `muestras`.
- Si sample_id ya está en BD: se marca como skipped (no se pisa nada).
- Si falta sample_id o hay error al insertar: se contabiliza como error.

Notas
-----
- Este módulo NO actualiza registros existentes (a propósito).
- Está pensado para compartir “deltas” de datos entre equipos sin copiar la BD completa.
"""

import io
import json
import zipfile
import hashlib
from datetime import datetime
from typing import Any, Dict, List

from db import init_db, get_connection, insertar_muestra_combinada


# =============================================================================
# Utilidades BD: existencia e inserción insert-only
# =============================================================================

def sample_exists(sample_id: str) -> bool:
    """
    Comprueba si sample_id ya existe en la tabla `muestras`.

    Retorna
    -------
    bool
        True  -> ya existe (no se debe reinsertar)
        False -> no existe (se puede insertar)
    """
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM muestras WHERE sample_id = ? LIMIT 1;", (sample_id,))
    ok = cur.fetchone() is not None
    conn.close()
    return ok


def merge_insert_only(muestra: Dict[str, Any]) -> str:
    """
    Inserta una muestra solo si no existe ya en BD.

    Parámetros
    ----------
    muestra : dict
        Diccionario con al menos 'sample_id'. El resto de claves pueden variar.

    Retorna
    -------
    str
        - "insert": insertada correctamente (no existía)
        - "skip":   omitida (ya existía)
        - "error":  muestra inválida (sin sample_id)
    """
    sid = str(muestra.get("sample_id") or "").strip()
    if not sid:
        return "error"

    if sample_exists(sid):
        return "skip"

    # Inserción real (INSERT OR REPLACE en tu db.py, pero aquí “solo llegamos”
    # si NO existe, así que en la práctica actúa como insert-only)
    insertar_muestra_combinada(muestra)
    return "insert"


# =============================================================================
# Exportación: construir ZIP de transferencia
# =============================================================================

def build_transfer_zip(
    lote: List[Dict[str, Any]],
    meta: Dict[str, Any] | None = None,
    extra_files: Dict[str, bytes] | None = None,
) -> bytes:
    """
    Construye un paquete ZIP con:
      - delta.json (datos del lote)
      - manifest.json (integridad + info)
      - archivos extra opcionales (ej: Excel del lote exportado)

    Parámetros
    ----------
    lote : list[dict]
        Lista de muestras (dict). Debe ser no vacía.
    meta : dict | None
        Metadatos opcionales (ej: origen, hospital, versión app, notas).
    extra_files : dict[str, bytes] | None
        Archivos extra a incluir dentro del ZIP. Clave=nombre archivo, valor=bytes.

    Retorna
    -------
    bytes
        Contenido binario del ZIP listo para st.download_button o guardado a disco.
    """
    if not lote:
        raise ValueError("Lote vacío.")

    # Payload principal (delta)
    payload = {
        "type": "tfg_mamma_transfer",
        "version": 1,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "meta": meta or {},
        "muestras": lote,
    }

    # Serializamos delta.json y calculamos hash SHA256 para integridad
    delta_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    sha = hashlib.sha256(delta_bytes).hexdigest()

    # Manifiesto (para validar integridad y describir contenido)
    manifest = {
        "type": "tfg_mamma_transfer_manifest",
        "version": 1,
        "created_at": payload["created_at"],
        "count": len(lote),
        "sha256_delta": sha,
        "meta": meta or {},
        "extra_files": list((extra_files or {}).keys()),
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    # Construcción ZIP en memoria
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("delta.json", delta_bytes)
        z.writestr("manifest.json", manifest_bytes)

        # Archivos extra opcionales (ej: excel del lote)
        if extra_files:
            for fname, fbytes in extra_files.items():
                # Si fbytes es falsy (None, b"", etc.), lo ignoramos
                if fbytes:
                    z.writestr(fname, fbytes)

    return buf.getvalue()


# =============================================================================
# Importación: leer ZIP y aplicar inserción insert-only
# =============================================================================

def import_transfer_zip(zip_bytes: bytes) -> Dict[str, Any]:
    """
    Importa un paquete ZIP generado por build_transfer_zip().

    Pasos:
      1) Lee delta.json y manifest.json
      2) Recalcula SHA256(delta.json) y compara con manifest.json
      3) Inserta cada muestra con merge_insert_only()

    Parámetros
    ----------
    zip_bytes : bytes
        Contenido binario del ZIP.

    Retorna
    -------
    dict
        Resumen de importación:
          - inserted: cuántas se insertaron
          - skipped:  cuántas ya existían
          - errors:   cuántas fallaron (o eran inválidas)
          - count_in_package: total en el paquete
          - meta, created_at: metadatos del paquete
    """
    buf = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(buf, "r") as z:
        delta = json.loads(z.read("delta.json").decode("utf-8"))
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))

    # Verificación de integridad: delta.json no debe haber sido alterado
    delta_bytes = json.dumps(delta, ensure_ascii=False, indent=2).encode("utf-8")
    sha = hashlib.sha256(delta_bytes).hexdigest()
    if sha != manifest.get("sha256_delta"):
        raise ValueError("Integridad fallida: hash no coincide.")

    inserted = skipped = errors = 0

    # Insert-only sobre lo que venga en el paquete
    for m in delta.get("muestras", []):
        try:
            r = merge_insert_only(m)
            if r == "insert":
                inserted += 1
            elif r == "skip":
                skipped += 1
            else:
                # "error" (ej: sample_id vacío)
                errors += 1
        except Exception:
            # Errores de BD / formato inesperado
            errors += 1

    return {
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
        "count_in_package": len(delta.get("muestras", [])),
        "meta": delta.get("meta", {}),
        "created_at": delta.get("created_at"),
    }