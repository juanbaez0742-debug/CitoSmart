import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from models.database import get_connection

auth = Blueprint("auth", __name__)


def _safe_int(value):
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _load_user(conn, user_id):
    return conn.execute(
        "SELECT * FROM usuario WHERE id = ?",
        (user_id,),
    ).fetchone()


@auth.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id") and session.get("rol") == "paciente":
        return redirect(url_for("dashboard.paciente_home"))
    if session.get("user_id") and session.get("rol") == "profesional":
        return redirect(url_for("dashboard.profesional_home"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        remember = request.form.get("remember")

        conn = get_connection()
        user = conn.execute(
            "SELECT * FROM usuario WHERE username = ? OR email = ?",
            (identifier, identifier),
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["rol"] = user["rol"]
            session["nombre"] = user["nombre"] or user["username"]

            if remember:
                session.permanent = True

            if not user["perfil_completado"]:
                flash("Completa tu perfil inicial para desbloquear el resto de la plataforma.", "info")
                return redirect(url_for("auth.complete_profile"))

            if user["rol"] == "paciente":
                return redirect(url_for("dashboard.paciente_home"))
            return redirect(url_for("dashboard.profesional_home"))

        flash("Credenciales incorrectas. Verifica tu correo y contrasena.", "danger")

    return render_template("login.html")


@auth.route("/register", methods=["GET", "POST"])
def register():
    selected_role = request.args.get("rol", "paciente")

    if request.method == "POST":
        rol = request.form.get("rol", "").strip()
        email = request.form.get("email", "").strip()
        telefono = request.form.get("telefono", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        nombre = request.form.get("nombre", "").strip()
        selected_role = rol or selected_role
        username = email.lower()

        if rol not in {"paciente", "profesional"}:
            flash("Selecciona un tipo de cuenta valido.", "danger")
            return render_template("register.html", selected_role=selected_role)

        if not password or not nombre or not email or not telefono:
            flash("Completa los campos obligatorios para crear tu cuenta.", "danger")
            return render_template("register.html", selected_role=selected_role)

        if password != confirm_password:
            flash("Las contrasenas no coinciden.", "danger")
            return render_template("register.html", selected_role=selected_role)

        conn = get_connection()
        existing = conn.execute(
            """
            SELECT id, username, email
            FROM usuario
            WHERE username = ?
               OR (email IS NOT NULL AND email = ?)
            """,
            (username, email),
        ).fetchone()

        if existing:
            conn.close()
            flash("Ya existe una cuenta con ese usuario o correo.", "warning")
            return render_template("register.html", selected_role=selected_role)

        payload = {
            "username": username,
            "password": generate_password_hash(password),
            "rol": rol,
            "nombre": nombre,
            "email": email,
            "telefono": telefono,
        }

        try:
            cursor = conn.execute(
                """
                INSERT INTO usuario (
                    username, password, rol, nombre, email, telefono, perfil_completado, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                """,
                (
                    payload["username"],
                    payload["password"],
                    payload["rol"],
                    payload["nombre"],
                    payload["email"],
                    payload["telefono"],
                    0,
                ),
            )
            user_id = cursor.lastrowid
            conn.commit()
            session["user_id"] = user_id
            session["rol"] = rol
            session["nombre"] = nombre
            flash("Cuenta creada correctamente. Ahora completa tu perfil para desbloquear la plataforma.", "success")
            return redirect(url_for("auth.complete_profile"))
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("No fue posible crear la cuenta porque el usuario ya existe.", "danger")
        finally:
            conn.close()

    return render_template("register.html", selected_role=selected_role)


@auth.route("/complete-profile", methods=["GET", "POST"])
def complete_profile():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))

    conn = get_connection()
    user = _load_user(conn, session["user_id"])
    if not user:
        conn.close()
        session.clear()
        flash("Tu sesion ya no es valida. Inicia sesion nuevamente.", "warning")
        return redirect(url_for("auth.login"))

    if user["perfil_completado"]:
        conn.close()
        if user["rol"] == "profesional":
            return redirect(url_for("dashboard.profesional_home"))
        return redirect(url_for("dashboard.paciente_home"))

    if request.method == "POST":
        if user["rol"] == "paciente":
            antecedentes = request.form.get("antecedentes", "").strip()
            if not antecedentes:
                conn.close()
                flash("Agrega al menos los antecedentes clinicos principales para continuar.", "danger")
                return render_template("complete_profile.html", user=user)

            payload = {
                "fecha_nacimiento": request.form.get("fecha_nacimiento", "").strip(),
                "edad": _safe_int(request.form.get("edad")),
                "genero": request.form.get("genero", "").strip(),
                "direccion": request.form.get("direccion", "").strip(),
                "antecedentes": antecedentes,
                "alergias": request.form.get("alergias", "").strip(),
                "motivo_consulta": request.form.get("motivo_consulta", "").strip(),
            }

            conn.execute(
                """
                UPDATE usuario
                SET fecha_nacimiento = ?, edad = ?, genero = ?, direccion = ?,
                    antecedentes = ?, alergias = ?, motivo_consulta = ?, perfil_completado = 1
                WHERE id = ?
                """,
                (
                    payload["fecha_nacimiento"],
                    payload["edad"],
                    payload["genero"],
                    payload["direccion"],
                    payload["antecedentes"],
                    payload["alergias"],
                    payload["motivo_consulta"],
                    user["id"],
                ),
            )
            conn.execute(
                """
                INSERT INTO historial_medico (
                    paciente_id, titulo, tipo, descripcion, detalle, origen
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    "Perfil clinico inicial",
                    "registro",
                    "El paciente completo su antecedente clinico inicial al crear la cuenta.",
                    f"Motivo de consulta: {payload['motivo_consulta'] or 'No especificado'}. "
                    f"Antecedentes: {payload['antecedentes']}.",
                    "registro",
                ),
            )
            conn.commit()
            conn.close()
            flash("Perfil clinico guardado. Ya puedes entrar a tu panel.", "success")
            return redirect(url_for("dashboard.paciente_home"))

        especialidad = request.form.get("especialidad", "").strip()
        experiencia = request.form.get("experiencia", "").strip()
        if not especialidad or not experiencia:
            conn.close()
            flash("Completa al menos la especialidad y la experiencia profesional para continuar.", "danger")
            return render_template("complete_profile.html", user=user)

        payload = {
            "especialidad": especialidad,
            "cedula": request.form.get("cedula", "").strip(),
            "institucion": request.form.get("institucion", "").strip(),
            "experiencia": experiencia,
            "biografia": request.form.get("biografia", "").strip(),
        }

        conn.execute(
            """
            UPDATE usuario
            SET especialidad = ?, cedula = ?, institucion = ?, experiencia = ?,
                biografia = ?, perfil_completado = 1
            WHERE id = ?
            """,
            (
                payload["especialidad"],
                payload["cedula"],
                payload["institucion"],
                payload["experiencia"],
                payload["biografia"],
                user["id"],
            ),
        )
        conn.commit()
        conn.close()
        flash("Perfil profesional guardado. Ya puedes entrar a tu panel.", "success")
        return redirect(url_for("dashboard.profesional_home"))

    conn.close()
    return render_template("complete_profile.html", user=user)


@auth.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
