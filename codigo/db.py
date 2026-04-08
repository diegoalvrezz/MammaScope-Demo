# db.py
import os
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
import base64
import hashlib
import hmac
import secrets
import json

# Ruta local de la base de datos.
# Se guarda junto al código para que la app sea autocontenida y fácil de desplegar en local.
BASE_DIR = os.path.dirname(__file__)
# Permite sobrescribir la ruta desde variables de entorno (para demo y despliegues).
DB_PATH = os.environ.get("TFG_MAMMA_DB_PATH", os.path.join(BASE_DIR, "tfg_mamma.db"))


def get_connection() -> sqlite3.Connection:
    """
    Crea y devuelve una conexión SQLite lista para usar.

    Decisiones:
    - PRAGMA foreign_keys = ON: activa integridad referencial si hay claves foráneas.
    - row_factory = sqlite3.Row: permite acceder a columnas por nombre además de por índice.

    Si la conexión falla, se lanza un RuntimeError con un mensaje más legible.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        raise RuntimeError(f"Error al conectar con la base de datos: {e}")


def bd_existe() -> bool:
    """
    Indica si el archivo físico de la base de datos existe en disco.
    """
    return Path(DB_PATH).exists()


def _tabla_tiene_columna(conn: sqlite3.Connection, tabla: str, columna: str) -> bool:
    """
    Comprueba si una tabla contiene una columna concreta.

    Se usa en la migración “segura” para añadir columnas nuevas sin romper bases antiguas.
    """
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({tabla});")
    cols = [r[1] for r in cur.fetchall()]  # r[1] corresponde al nombre de la columna
    return columna in cols


def _add_column_if_missing(conn: sqlite3.Connection, tabla: str, columna: str, decl: str) -> None:
    """
    Añade una columna a una tabla si no existe.

    Importante:
    - SQLite permite ALTER TABLE ... ADD COLUMN de forma incremental.
    - No borra ni transforma datos previos: es una migración conservadora.
    """
    if not _tabla_tiene_columna(conn, tabla, columna):
        cur = conn.cursor()
        cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {decl};")
        conn.commit()


def init_db() -> None:
    """
    Inicializa la estructura de la base de datos (tablas) y aplica migraciones básicas.

    Objetivo:
    - Permitir que la app arranque tanto con una BD nueva como con una BD antigua.
    - Si hay columnas nuevas (por evolución del proyecto), se añaden sin perder datos.

    Nota:
    Se aplica una migración “segura” basada en:
    - comprobar si existe la columna
    - si falta, hacer ALTER TABLE ADD COLUMN
    """
    conn = get_connection()
    cur = conn.cursor()

    # -------------------------
    # Tabla principal: muestras emparejadas (Excel + PDF)
    # -------------------------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS muestras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Identificación
            nhc TEXT,
            sample_id TEXT NOT NULL UNIQUE,
            fecha_excel TEXT,

            -- Contexto / Excel
            ronda TEXT,
            celularidad REAL,

            -- Subtipos
            subtipo_ihq TEXT,
            subtipo_mmt TEXT,
            subtipo_mmt_detalle TEXT,
            fecha_informe_mmt TEXT,

            -- Marcadores MammaTyper (PDF)
            ERBB2_value REAL,
            ERBB2_status TEXT,
            ESR1_value REAL,
            ESR1_status TEXT,
            PGR_value REAL,
            PGR_status TEXT,
            MKI67_value REAL,
            MKI67_status TEXT,

            -- HER2 por IHQ y SISH (Patwin)
            ERBB2_IHQ_SISH TEXT,
            HER2_SISH_result TEXT,
            HER2_final TEXT,
            HER2_IHQ_score TEXT,

            -- Receptores hormonales IHQ (Patwin)
            ESR1_IHQ TEXT,
            ESR1_IHQ_intensidad TEXT,
            PGR_IHQ TEXT,
            PGR_IHQ_intensidad TEXT,

            -- Ki67 IHQ (Patwin)
            KI67_IHQ REAL,

            -- P53 y CK19 IHQ (Patwin)
            P53_IHQ_status TEXT,
            P53_IHQ_pct REAL,
            CK19_IHQ_status TEXT,

            -- Firmantes
            firmantes_diag TEXT,

            -- Porcentajes receptores (Patwin)
            ESR1_IHQ_pct REAL,
            PGR_IHQ_pct REAL,

            -- Mensajes / avisos
            aviso TEXT
        );
        """
    )

    # -------------------------
    # Tabla auxiliar: registros sin correspondencia (Excel sin PDF / PDF sin Excel)
    # -------------------------
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS muestras_sin_match (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id TEXT NOT NULL,
            origen TEXT NOT NULL,
            fecha_proceso TEXT,
            detalle TEXT
        );
        """
    )

    # -------------------------
    # Tablas de autenticación y auditoría
    # -------------------------
    # usuarios_app: credenciales y estado del usuario.
    # audit_log: trazabilidad de acciones relevantes (login, importaciones, guardados, etc.).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios_app (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('basico','jefe','admin')),
            is_active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            last_login TEXT
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (datetime('now')),
            username TEXT,
            action TEXT NOT NULL,
            details TEXT
        );
        """
    )

    conn.commit()

    # -------------------------
    # Migración: columnas nuevas para métricas de cutoffs / deltas / equivalencias
    # -------------------------
    # Estas columnas se añadieron para enriquecer la interpretación (p. ej. “cercanía al cutoff”).
    # Se añaden solo si faltan, para mantener compatibilidad con BDs creadas en versiones previas.
    nuevas = [
        # ERBB2
        ("ERBB2_cutoff_nearest", "REAL"),
        ("ERBB2_delta_cutoff", "REAL"),
        ("ERBB2_delta_to_positive", "REAL"),
        ("ERBB2_equiv", "TEXT"),
        # ESR1
        ("ESR1_cutoff_nearest", "REAL"),
        ("ESR1_delta_cutoff", "REAL"),
        ("ESR1_delta_to_positive", "REAL"),
        ("ESR1_equiv", "TEXT"),
        # PGR
        ("PGR_cutoff_nearest", "REAL"),
        ("PGR_delta_cutoff", "REAL"),
        ("PGR_delta_to_positive", "REAL"),
        ("PGR_equiv", "TEXT"),
        # MKI67
        ("MKI67_cutoff_nearest", "REAL"),
        ("MKI67_delta_cutoff", "REAL"),
        ("MKI67_delta_to_positive", "REAL"),
        ("MKI67_equiv", "TEXT"),
    ]
    for col, decl in nuevas:
        _add_column_if_missing(conn, "muestras", col, decl)

    conn.close()


def muestra_existe(sample_id: str) -> bool:
    """
    Comprueba si un sample_id ya existe en la tabla `muestras`.

    Se usa antes de insertar para distinguir entre inserción nueva
    y actualización, permitiendo informar al usuario en el Paso 2.
    """
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM muestras WHERE sample_id = ? LIMIT 1;", (sample_id,))
    existe = cur.fetchone() is not None
    conn.close()
    return existe


def insertar_muestra_combinada(muestra: Dict[str, Any]) -> str:
    """
    Inserta o actualiza una muestra emparejada (Excel + PDF) en la tabla `muestras`.

    Detalles importantes:
    - Se usa INSERT OR REPLACE para que el `sample_id` (UNIQUE) actúe como "clave natural".
      Si entra una muestra ya existente, se reemplaza (actualiza).
    - La consulta se construye de forma dinámica (lista de columnas + placeholders),
      evitando errores típicos por desajuste entre columnas y valores.

    Retorna
    -------
    str
        - "insert" : muestra nueva, insertada por primera vez.
        - "update" : muestra ya existente, actualizada con los nuevos datos.
    """
    init_db()

    # Detectar si es inserción nueva o actualización antes de ejecutar.
    sid = muestra.get("sample_id")
    es_actualizacion = bool(sid and muestra_existe(str(sid)))

    conn = get_connection()
    cur = conn.cursor()

    # Lista explícita de columnas soportadas por la app.
    cols = [
        # Identificación
        "nhc", "sample_id", "fecha_excel",
        # Contexto
        "ronda", "celularidad",
        # Subtipos
        "subtipo_ihq", "subtipo_mmt", "subtipo_mmt_detalle", "fecha_informe_mmt",
        # MMT
        "ERBB2_value", "ERBB2_status",
        "ESR1_value", "ESR1_status",
        "PGR_value", "PGR_status",
        "MKI67_value", "MKI67_status",
        # Métricas derivadas (cutoffs / deltas / equivalencias)
        "ERBB2_cutoff_nearest", "ERBB2_delta_cutoff", "ERBB2_delta_to_positive", "ERBB2_equiv",
        "ESR1_cutoff_nearest",  "ESR1_delta_cutoff",  "ESR1_delta_to_positive",  "ESR1_equiv",
        "PGR_cutoff_nearest",   "PGR_delta_cutoff",   "PGR_delta_to_positive",   "PGR_equiv",
        "MKI67_cutoff_nearest", "MKI67_delta_cutoff", "MKI67_delta_to_positive", "MKI67_equiv",
        # HER2 IHQ/SISH
        "ERBB2_IHQ_SISH", "HER2_SISH_result", "HER2_final", "HER2_IHQ_score",
        # HR IHQ
        "ESR1_IHQ", "ESR1_IHQ_intensidad",
        "PGR_IHQ", "PGR_IHQ_intensidad",
        # Ki67 IHQ
        "KI67_IHQ",
        # P53/CK19
        "P53_IHQ_status", "P53_IHQ_pct", "CK19_IHQ_status",
        # Firmantes + % HR
        "firmantes_diag", "ESR1_IHQ_pct", "PGR_IHQ_pct",
        # Aviso
        "aviso",
    ]

    vals = [muestra.get(c) for c in cols]
    placeholders = ",".join(["?"] * len(cols))

    sql = f"""
        INSERT OR REPLACE INTO muestras ({",".join(cols)})
        VALUES ({placeholders});
    """
    cur.execute(sql, vals)
    conn.commit()
    conn.close()

    return "update" if es_actualizacion else "insert"
def registrar_muestra_sin_match(sample_id: str, origen: str, detalle: Optional[str] = None) -> None:
    """
    Registra un caso sin correspondencia en `muestras_sin_match`.

    Se usa cuando:
    - el sample_id está en PDF pero no en Excel, o
    - el sample_id está en Excel pero no en PDF.

    `origen` indica de qué fuente proviene el registro (por ejemplo: "PDF" o "EXCEL").
    `detalle` sirve para dejar trazabilidad humana del motivo.
    """
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO muestras_sin_match (sample_id, origen, fecha_proceso, detalle)
        VALUES (?, ?, datetime('now','localtime'), ?);
        """,
        (sample_id, origen, detalle),
    )

    conn.commit()
    conn.close()


def eliminar_muestras_sin_match_por_ids(ids: list[int]) -> None:
    """
    Elimina registros de `muestras_sin_match` seleccionando por su id interno.

    Nota:
    - Es una operación irreversible.
    - Se usa normalmente desde la pantalla de “Bases no cruzadas” para limpiar errores.
    """
    if not ids:
        return
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in ids)
    cur.execute(f"DELETE FROM muestras_sin_match WHERE id IN ({placeholders});", ids)
    conn.commit()
    conn.close()


def eliminar_muestras_sin_match_por_sample_ids(sample_ids: list[str]) -> None:
    """
    Elimina registros de `muestras_sin_match` por `sample_id`.

    Útil si quieres limpiar “en bloque” todos los eventos asociados a un identificador de muestra.
    """
    if not sample_ids:
        return
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in sample_ids)
    cur.execute(f"DELETE FROM muestras_sin_match WHERE sample_id IN ({placeholders});", sample_ids)
    conn.commit()
    conn.close()


# ==========================
# Autenticación: hashing de contraseñas + gestión de usuarios + auditoría
# ==========================

# Parámetros de hash PBKDF2.
# PBKDF2 con SHA-256 es un enfoque estándar y robusto para contraseñas.
# El número de iteraciones aumenta el coste de ataques de fuerza bruta.
_PBKDF2_ALGO = "pbkdf2_sha256"
_PBKDF2_ITERS = 200_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """
    Calcula un hash seguro de contraseña.

    Formato almacenado:
    pbkdf2_sha256$iters$salt_b64$hash_b64

    Motivo:
    - Guardar contraseñas en claro es un riesgo grave.
    - Se usa salt aleatoria por contraseña para evitar ataques por tablas rainbow.
    """
    if not isinstance(password, str) or len(password) < 1:
        raise ValueError("Contraseña inválida.")
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return f"{_PBKDF2_ALGO}${_PBKDF2_ITERS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """
    Verifica una contraseña contra el hash almacenado.

    Seguridad:
    - Se usa hmac.compare_digest para comparación en tiempo constante,
      reduciendo el riesgo de ataques por timing.
    """
    try:
        algo, iters_s, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != _PBKDF2_ALGO:
            return False
        iters = int(iters_s)
        salt = base64.b64decode(salt_b64.encode())
        expected = base64.b64decode(hash_b64.encode())
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def any_users_exist() -> bool:
    """
    Devuelve True si existe al menos un usuario en la tabla `usuarios_app`.

    Se usa para decidir si hay que mostrar el “bootstrap” del primer admin.
    """
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM usuarios_app;")
    n = cur.fetchone()[0] or 0
    conn.close()
    return n > 0


def get_user(username: str) -> Optional[Dict[str, Any]]:
    """
    Recupera un usuario por nombre.

    Devuelve:
    - Un diccionario con campos relevantes (incluyendo password_hash para verificación),
      o None si no existe.
    """
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT username, password_hash, role, is_active, must_change_password, created_at, last_login
        FROM usuarios_app
        WHERE username = ?;
        """,
        (username,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "username": row[0],
        "password_hash": row[1],
        "role": row[2],
        "is_active": bool(row[3]),
        "must_change_password": bool(row[4]),
        "created_at": row[5],
        "last_login": row[6],
    }


def list_users() -> List[Dict[str, Any]]:
    """
    Lista usuarios para la pantalla de administración.

    Se evita devolver `password_hash` porque no hace falta en la interfaz
    y reduce exposición accidental de información sensible.
    """
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT username, role, is_active, must_change_password, created_at, last_login
        FROM usuarios_app
        ORDER BY username COLLATE NOCASE;
        """
    )
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append(
            {
                "username": r[0],
                "role": r[1],
                "is_active": bool(r[2]),
                "must_change_password": bool(r[3]),
                "created_at": r[4],
                "last_login": r[5],
            }
        )
    return out


def create_user(username: str, password: str, role: str = "basico", must_change_password: bool = False) -> None:
    """
    Crea un usuario nuevo en `usuarios_app`.

    - role limita los permisos disponibles.
    - must_change_password permite obligar a cambiar la contraseña al primer inicio.
    """
    if role not in ("basico", "jefe", "admin"):
        raise ValueError("Rol inválido.")
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO usuarios_app (username, password_hash, role, is_active, must_change_password)
        VALUES (?, ?, ?, 1, ?);
        """,
        (username.strip(), hash_password(password), role, int(bool(must_change_password))),
    )
    conn.commit()
    conn.close()


def set_user_role(username: str, role: str) -> None:
    """
    Cambia el rol de un usuario existente.
    """
    if role not in ("basico", "jefe", "admin"):
        raise ValueError("Rol inválido.")
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios_app SET role = ? WHERE username = ?;", (role, username))
    conn.commit()
    conn.close()


def set_user_active(username: str, is_active: bool) -> None:
    """
    Activa o desactiva una cuenta.

    Si is_active=False, el usuario no podrá iniciar sesión.
    """
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios_app SET is_active = ? WHERE username = ?;", (int(bool(is_active)), username))
    conn.commit()
    conn.close()


def set_user_must_change_password(username: str, must_change: bool) -> None:
    """
    Activa o desactiva el flag de “cambio obligatorio de contraseña” en el próximo login.
    """
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE usuarios_app SET must_change_password = ? WHERE username = ?;",
        (int(bool(must_change)), username),
    )
    conn.commit()
    conn.close()


def update_user_password(username: str, new_password: str, clear_must_change: bool = True) -> None:
    """
    Actualiza la contraseña de un usuario.

    - La contraseña se almacena como hash PBKDF2.
    - clear_must_change=True elimina la obligación de cambio tras actualizarla.
    """
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE usuarios_app SET password_hash = ?, must_change_password = ? WHERE username = ?;",
        (hash_password(new_password), 0 if clear_must_change else 1, username),
    )
    conn.commit()
    conn.close()


def touch_last_login(username: str) -> None:
    """
    Actualiza la marca de tiempo del último inicio de sesión del usuario.
    """
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios_app SET last_login = datetime('now') WHERE username = ?;", (username,))
    conn.commit()
    conn.close()


def log_action(username: Optional[str], action: str, details: Optional[Dict[str, Any]] = None) -> None:
    """
    Registra un evento en la tabla `audit_log`.

    - username puede ser None (por ejemplo, intento de login con usuario inexistente).
    - details se guarda como JSON para permitir trazabilidad estructurada.

    Importante:
    - Esta función está diseñada para no romper la app: si falla, se ignora (best-effort).
    """
    try:
        init_db()
        conn = get_connection()
        cur = conn.cursor()
        det = None
        if details is not None:
            det = json.dumps(details, ensure_ascii=False)
        cur.execute(
            "INSERT INTO audit_log (username, action, details) VALUES (?, ?, ?);",
            (username, action, det),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_audit_log(limit: int = 200) -> List[Dict[str, Any]]:
    """
    Devuelve los últimos eventos del audit_log (ordenados del más reciente al más antiguo).
    """
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT ts, username, action, details FROM audit_log ORDER BY id DESC LIMIT ?;",
        (int(limit),),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"ts": ts, "username": user, "action": action, "details": details} for ts, user, action, details in rows]


def export_db_filtered(exclude_tables: List[str]) -> bytes:
    """
    Exporta una copia de la base de datos en formato bytes, excluyendo tablas concretas.

    Uso típico:
    - Generar un paquete de transferencia “limpio” (por ejemplo, sin usuarios o sin auditoría).
    - Permitir sincronización offline con control de qué se comparte.

    Cómo funciona:
    1) Abre la BD original.
    2) Crea una BD en memoria.
    3) Copia el esquema y los datos solo de las tablas permitidas.
    4) Vuelca la BD en memoria a un archivo temporal y devuelve sus bytes.
    """
    init_db()
    src = get_connection()
    src.row_factory = sqlite3.Row

    mem = sqlite3.connect(":memory:")
    mem.execute("PRAGMA foreign_keys=OFF;")

    # Se lee el esquema desde sqlite_master para replicar tablas.
    cur = src.cursor()
    cur.execute(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE type='table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name;
        """
    )
    tables = [(r[0], r[1]) for r in cur.fetchall() if r[0] not in set(exclude_tables)]

    # 1) Crear tablas (solo las incluidas)
    for name, sql in tables:
        if sql:
            mem.execute(sql)

    # 2) Copiar datos tabla a tabla
    for name, _sql in tables:
        rows = src.execute(f"SELECT * FROM {name};").fetchall()
        if not rows:
            continue
        cols = rows[0].keys()
        placeholders = ",".join(["?"] * len(cols))
        mem.executemany(
            f"INSERT INTO {name} ({','.join(cols)}) VALUES ({placeholders});",
            [tuple(r[c] for c in cols) for r in rows],
        )

    mem.commit()

    # Se vuelca la BD en memoria a disco temporal, porque es la forma más sencilla
    # de obtener bytes completos de un SQLite “real” con su formato correcto.
    import tempfile
    import os as _os

    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    _os.close(fd)
    try:
        disk = sqlite3.connect(tmp_path)
        mem.backup(disk)
        disk.close()
        with open(tmp_path, "rb") as f:
            b = f.read()
        return b
    finally:
        # Limpieza defensiva: se intenta cerrar y borrar incluso si hubo errores.
        try:
            mem.close()
        except Exception:
            pass
        try:
            src.close()
        except Exception:
            pass
        try:
            _os.remove(tmp_path)
        except Exception:
            pass