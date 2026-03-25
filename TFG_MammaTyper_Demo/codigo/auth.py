# auth.py
import streamlit as st

from db import (
    any_users_exist,
    create_user,
    get_user,
    verify_password,
    touch_last_login,
    update_user_password,
    log_action,
)

# Etiquetas “bonitas” para mostrar en la interfaz.
# La clave es el nombre interno del rol; el valor es lo que verá el usuario.
ROLE_LABELS = {
    "basico": "Usuario básico",
    "jefe": "Jefe de servicio",
    "admin": "Administrador",
}

# Orden jerárquico de roles:
# sirve para decidir si un rol “cumple” un requisito mínimo (por ejemplo, jefe >= basico).
ROLE_ORDER = ["basico", "jefe", "admin"]


def _role_at_least(user_role: str, required: str) -> bool:
    """
    Comprueba si el rol del usuario es igual o superior al rol requerido.

    Ejemplos:
    - user_role="admin", required="jefe"  -> True
    - user_role="basico", required="jefe" -> False

    Si llega un rol desconocido, se devuelve False por seguridad.
    """
    try:
        return ROLE_ORDER.index(user_role) >= ROLE_ORDER.index(required)
    except ValueError:
        return False


def current_user():
    """
    Devuelve el usuario autenticado actual desde `st.session_state`.

    Estructura esperada:
    st.session_state["user"] = {"username": ..., "role": ...}
    """
    return st.session_state.get("user")


def logout():
    """
    Cierra la sesión del usuario actual.

    Qué hace:
    - Registra la acción en auditoría (si hay usuario).
    - Elimina el usuario de la sesión.
    - Marca la sesión como no autenticada.
    """
    u = current_user()
    if u:
        log_action(u.get("username"), "logout", None)
    st.session_state.pop("user", None)
    st.session_state["auth_ok"] = False


def require_role(required: str) -> bool:
    """
    Verifica si el usuario actual tiene al menos el rol indicado.

    Se usa como “check” rápido en la UI para habilitar/deshabilitar pantallas o acciones.
    """
    u = current_user()
    if not u:
        return False
    return _role_at_least(u.get("role", "basico"), required)


def render_login_gate(app_title: str = "MammaScope · Análisis de Concordancia IHQ – MammaTyper®"):
    """
    Puerta de entrada de autenticación.

    Función:
    - Si hay una sesión válida, deja continuar.
    - Si no hay sesión válida, muestra:
        1) Un “bootstrap” para crear el primer admin (si no existen usuarios).
        2) Un formulario de login normal (si ya hay usuarios).
    - Si el usuario no está autenticado al final, detiene la app con `st.stop()`.

    Idea clave:
    Este patrón garantiza que el resto de la aplicación solo se ejecute cuando hay sesión.
    """
    u = current_user()
    if u and st.session_state.get("auth_ok", False):
        return u

    # Estado por defecto: no autenticado, hasta que se demuestre lo contrario.
    st.session_state["auth_ok"] = False
    # Logo centrado en la pantalla de login
    from pathlib import Path
    logo_path = Path("media/logo.png")
    if logo_path.exists():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(str(logo_path), width=500)

    st.title(app_title)

    # -------------------------
    # Bootstrap: creación del primer admin
    # -------------------------
    # Si la base de datos no tiene ningún usuario, se obliga a crear el primero con rol admin.
    # Esto evita que la app quede “bloqueada” sin forma de acceso.
    if not any_users_exist():
        st.info(
            "No hay usuarios creados todavía. Para inicializar la aplicación, crea el primer usuario **Administrador**."
        )
        with st.form("init_admin"):
            username = st.text_input("Usuario (admin)", value="admin")
            pw1 = st.text_input("Contraseña", type="password")
            pw2 = st.text_input("Repetir contraseña", type="password")
            submit = st.form_submit_button("Crear administrador")

        if submit:
            # Validaciones mínimas para evitar creación de cuentas inválidas.
            if not username.strip():
                st.error("El usuario no puede estar vacío.")
                st.stop()
            if len(pw1) < 6:
                st.error("La contraseña debe tener al menos 6 caracteres.")
                st.stop()
            if pw1 != pw2:
                st.error("Las contraseñas no coinciden.")
                st.stop()

            try:
                create_user(username=username.strip(), password=pw1, role="admin", must_change_password=False)
                log_action(username.strip(), "user_create_first_admin", {"username": username.strip()})
                st.success("Administrador creado. Ya puedes iniciar sesión.")
                # Se recarga para que desaparezca el bootstrap y aparezca el login normal.
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo crear el administrador: {e}")

    # -------------------------
    # Login normal
    # -------------------------
    # Se muestra siempre que ya exista al menos un usuario en la base de datos.
    st.subheader("Iniciar sesión")
    with st.form("login_form"):
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        submit = st.form_submit_button("Entrar")

    if submit:
        # 1) Recuperar usuario por nombre.
        user = get_user(username.strip())
        if not user:
            # Auditoría sin username real (no existe); se registra el intento fallido.
            log_action(None, "login_fail", {"username": username.strip(), "reason": "no_user"})
            st.error("Usuario o contraseña incorrectos.")
            st.stop()

        # 2) Usuario desactivado: impedir login aunque la contraseña sea correcta.
        if not user.get("is_active", True):
            log_action(user.get("username"), "login_fail", {"reason": "inactive"})
            st.error("Usuario desactivado. Contacta con el administrador.")
            st.stop()

        # 3) Verificación de contraseña contra el hash almacenado.
        if not verify_password(password, user["password_hash"]):
            log_action(user.get("username"), "login_fail", {"reason": "bad_password"})
            st.error("Usuario o contraseña incorrectos.")
            st.stop()

        # 4) Login correcto: se guarda una versión “ligera” del usuario en session_state.
        # Se evita guardar datos sensibles o innecesarios en memoria de sesión.
        st.session_state["user"] = {"username": user["username"], "role": user["role"]}
        st.session_state["auth_ok"] = True

        # Se actualiza fecha/hora de último login (útil para trazabilidad).
        touch_last_login(user["username"])

        # Auditoría: evento de login OK con rol.
        log_action(user["username"], "login_ok", {"role": user["role"]})

        # Si está marcado, se forzará el cambio de contraseña en el panel lateral.
        st.session_state["force_pw_change"] = bool(user.get("must_change_password"))

        # Se recarga la app para entrar al flujo normal ya autenticado.
        st.rerun()

    # Si llega aquí, el usuario no está autenticado: se bloquea el resto de la app.
    st.stop()


def render_account_panel():
    """
    Panel en sidebar para:
    - Mostrar usuario y rol actual.
    - Forzar cambio de contraseña si es obligatorio.
    - Permitir cambio de contraseña voluntario.
    - Cerrar sesión.

    Nota:
    Esta función asume que `render_login_gate()` ya ha validado la sesión.
    """
    u = current_user()
    if not u:
        return

    st.sidebar.markdown("---")
    st.sidebar.subheader("Sesión")
    st.sidebar.write(f"👤 **{u['username']}**")
    st.sidebar.caption(f"Rol: {ROLE_LABELS.get(u['role'], u['role'])}")

    # -------------------------
    # Cambio de contraseña obligatorio
    # -------------------------
    # Si el usuario fue creado con "must_change_password", se le obliga a cambiarla antes
    # de continuar usando la aplicación.
    if st.session_state.get("force_pw_change", False):
        st.sidebar.warning("Debes cambiar tu contraseña para continuar.")
        with st.sidebar.form("force_change_pw"):
            pw1 = st.text_input("Nueva contraseña", type="password")
            pw2 = st.text_input("Repetir", type="password")
            ok = st.form_submit_button("Cambiar contraseña")

        if ok:
            if len(pw1) < 6:
                st.sidebar.error("Mínimo 6 caracteres.")
            elif pw1 != pw2:
                st.sidebar.error("No coinciden.")
            else:
                # Se actualiza la contraseña y se limpia el flag de “cambio obligatorio”.
                update_user_password(u["username"], pw1, clear_must_change=True)
                log_action(u["username"], "password_change_forced", None)
                st.session_state["force_pw_change"] = False
                st.sidebar.success("Contraseña cambiada.")
                st.rerun()

        # Bloqueo total de la app hasta que se cambie la contraseña.
        st.stop()

    # -------------------------
    # Cambio de contraseña voluntario (Mi cuenta)
    # -------------------------
    # Se solicita la contraseña actual para evitar cambios accidentales o por sesión abierta.
    with st.sidebar.expander("Mi cuenta", expanded=False):
        with st.form("change_pw"):
            pw_old = st.text_input("Contraseña actual", type="password")
            pw1 = st.text_input("Nueva contraseña", type="password")
            pw2 = st.text_input("Repetir nueva contraseña", type="password")
            ok = st.form_submit_button("Actualizar contraseña")

        if ok:
            # Se vuelve a consultar el usuario completo para validar el hash actual.
            user_full = get_user(u["username"])
            if not user_full or not verify_password(pw_old, user_full["password_hash"]):
                st.error("La contraseña actual no es correcta.")
            elif len(pw1) < 6:
                st.error("La nueva contraseña debe tener al menos 6 caracteres.")
            elif pw1 != pw2:
                st.error("Las nuevas contraseñas no coinciden.")
            else:
                update_user_password(u["username"], pw1, clear_must_change=True)
                log_action(u["username"], "password_change", None)
                st.success("Contraseña actualizada.")

    # -------------------------
    # Cierre de sesión
    # -------------------------
    if st.sidebar.button("Cerrar sesión"):
        logout()
        st.rerun()