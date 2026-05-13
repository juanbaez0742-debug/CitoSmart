from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from models.database import get_connection

chat = Blueprint("chat", __name__)


def _require_login():
    return "user_id" in session


def _load_contacts(conn, user_id, role):
    target_role = "profesional" if role == "paciente" else "paciente"
    contacts = conn.execute(
        """
        SELECT DISTINCT
            u.id,
            u.nombre,
            u.especialidad,
            u.email,
            u.telefono,
            MAX(m.fecha) AS ultimo_mensaje
        FROM usuario u
        LEFT JOIN mensaje m
            ON (m.emisor_id = u.id AND m.receptor_id = ?)
            OR (m.receptor_id = u.id AND m.emisor_id = ?)
        LEFT JOIN asignacion a
            ON ((a.paciente_id = ? AND a.profesional_id = u.id)
            OR (a.profesional_id = ? AND a.paciente_id = u.id))
        LEFT JOIN imagen_citologica i
            ON ((i.paciente_id = ? AND i.profesional_id = u.id)
            OR (i.profesional_id = ? AND i.paciente_id = u.id))
        WHERE u.rol = ?
        GROUP BY u.id, u.nombre, u.especialidad, u.email, u.telefono
        HAVING COUNT(m.id) > 0 OR COUNT(a.id) > 0 OR COUNT(i.id) > 0
        ORDER BY COALESCE(MAX(m.fecha), MAX(i.fecha), u.created_at) DESC, u.nombre
        """,
        (user_id, user_id, user_id, user_id, user_id, user_id, target_role),
    ).fetchall()

    if contacts:
        return contacts

    return conn.execute(
        """
        SELECT id, nombre, especialidad, email, telefono, NULL AS ultimo_mensaje
        FROM usuario
        WHERE rol = ?
        ORDER BY created_at DESC, nombre
        LIMIT 12
        """,
        (target_role,),
    ).fetchall()


@chat.route("/mensajes")
def mensajes():
    if not _require_login():
        return redirect(url_for("auth.login"))

    conn = get_connection()
    contacts = _load_contacts(conn, session["user_id"], session["rol"])
    contact_ids = [str(contact["id"]) for contact in contacts]
    selected_contact_id = request.args.get("contact")

    if selected_contact_id not in contact_ids and contacts:
        selected_contact_id = str(contacts[0]["id"])

    active_contact = None
    if selected_contact_id:
        active_contact = conn.execute(
            "SELECT * FROM usuario WHERE id = ?",
            (selected_contact_id,),
        ).fetchone()

    conn.close()
    return render_template(
        "chat.html",
        contacts=contacts,
        active_contact=active_contact,
    )


@chat.route("/chat/<int:receptor_id>")
def chat_view(receptor_id):
    if not _require_login():
        return redirect(url_for("auth.login"))
    return redirect(url_for("chat.mensajes", contact=receptor_id))


@chat.route("/enviar_mensaje", methods=["POST"])
def enviar_mensaje():
    if not _require_login():
        return jsonify({"status": "error", "message": "Sesion no valida"}), 401

    data = request.json or {}
    receptor_id = data.get("receptor_id")
    mensaje = (data.get("mensaje") or "").strip()

    if not receptor_id or not mensaje:
        return jsonify({"status": "error", "message": "Mensaje vacio"}), 400

    conn = get_connection()
    receptor = conn.execute(
        "SELECT id FROM usuario WHERE id = ?",
        (receptor_id,),
    ).fetchone()
    if not receptor:
        conn.close()
        return jsonify({"status": "error", "message": "Contacto no encontrado"}), 404

    conn.execute(
        "INSERT INTO mensaje (emisor_id, receptor_id, contenido) VALUES (?, ?, ?)",
        (session["user_id"], receptor_id, mensaje),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@chat.route("/obtener_mensajes/<int:receptor_id>")
def obtener_mensajes(receptor_id):
    if not _require_login():
        return jsonify([]), 401

    conn = get_connection()
    mensajes = conn.execute(
        """
        SELECT * FROM mensaje
        WHERE (emisor_id = ? AND receptor_id = ?)
           OR (emisor_id = ? AND receptor_id = ?)
        ORDER BY fecha ASC
        """,
        (session["user_id"], receptor_id, receptor_id, session["user_id"]),
    ).fetchall()
    conn.close()

    return jsonify(
        [
            {
                "emisor": mensaje["emisor_id"],
                "contenido": mensaje["contenido"],
                "fecha": mensaje["fecha"],
            }
            for mensaje in mensajes
        ]
    )
