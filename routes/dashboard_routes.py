from flask import Blueprint, abort, redirect, render_template, session, url_for

from models.database import get_connection

dashboard = Blueprint("dashboard", __name__)


def _require_role(role):
    return "user_id" in session and session.get("rol") == role


@dashboard.route("/paciente_home")
def paciente_home():
    if not _require_role("paciente"):
        return redirect(url_for("auth.login"))

    conn = get_connection()
    user_id = session["user_id"]

    paciente = conn.execute(
        "SELECT * FROM usuario WHERE id = ? AND rol = 'paciente'",
        (user_id,),
    ).fetchone()
    if not paciente:
        conn.close()
        abort(404)

    historial = conn.execute(
        """
        SELECT h.*, u.nombre AS profesional_nombre
        FROM historial_medico h
        LEFT JOIN usuario u ON u.id = h.profesional_id
        WHERE h.paciente_id = ?
        ORDER BY h.fecha DESC
        LIMIT 8
        """,
        (user_id,),
    ).fetchall()

    estudios = conn.execute(
        """
        SELECT i.*, u.nombre AS profesional_nombre
        FROM imagen_citologica i
        JOIN usuario u ON u.id = i.profesional_id
        WHERE i.paciente_id = ?
        ORDER BY i.fecha DESC
        LIMIT 5
        """,
        (user_id,),
    ).fetchall()

    profesionales = conn.execute(
        """
        SELECT DISTINCT u.id, u.nombre, u.especialidad, u.institucion, u.email, u.telefono
        FROM usuario u
        LEFT JOIN asignacion a ON a.profesional_id = u.id AND a.paciente_id = ?
        LEFT JOIN imagen_citologica i ON i.profesional_id = u.id AND i.paciente_id = ?
        WHERE u.rol = 'profesional' AND (a.id IS NOT NULL OR i.id IS NOT NULL)
        ORDER BY u.nombre
        """,
        (user_id, user_id),
    ).fetchall()

    if not profesionales:
        profesionales = conn.execute(
            """
            SELECT id, nombre, especialidad, institucion, email, telefono
            FROM usuario
            WHERE rol = 'profesional'
            ORDER BY created_at DESC, nombre
            LIMIT 4
            """
        ).fetchall()

    resumen = {
        "historial_items": conn.execute(
            "SELECT COUNT(*) FROM historial_medico WHERE paciente_id = ?",
            (user_id,),
        ).fetchone()[0],
        "estudios_realizados": conn.execute(
            "SELECT COUNT(*) FROM imagen_citologica WHERE paciente_id = ?",
            (user_id,),
        ).fetchone()[0],
        "contactos_activos": len(profesionales),
    }
    conn.close()

    return render_template(
        "paciente_home.html",
        paciente=paciente,
        historial=historial,
        estudios=estudios,
        profesionales=profesionales,
        resumen=resumen,
    )


@dashboard.route("/profesional_home")
def profesional_home():
    if not _require_role("profesional"):
        return redirect(url_for("auth.login"))

    conn = get_connection()
    user_id = session["user_id"]

    profesional = conn.execute(
        "SELECT * FROM usuario WHERE id = ? AND rol = 'profesional'",
        (user_id,),
    ).fetchone()
    if not profesional:
        conn.close()
        abort(404)

    pacientes = conn.execute(
        """
        SELECT
            u.id,
            u.nombre,
            u.email,
            u.telefono,
            u.motivo_consulta,
            u.antecedentes,
            COUNT(DISTINCT i.id) AS estudios,
            MAX(i.fecha) AS ultima_revision
        FROM usuario u
        LEFT JOIN imagen_citologica i
            ON i.paciente_id = u.id AND i.profesional_id = ?
        WHERE u.rol = 'paciente'
        GROUP BY u.id, u.nombre, u.email, u.telefono, u.motivo_consulta, u.antecedentes
        ORDER BY COALESCE(MAX(i.fecha), u.created_at) DESC, u.nombre
        """,
        (user_id,),
    ).fetchall()

    estudios_recientes = conn.execute(
        """
        SELECT i.*, u.nombre AS paciente_nombre
        FROM imagen_citologica i
        JOIN usuario u ON u.id = i.paciente_id
        WHERE i.profesional_id = ?
        ORDER BY i.fecha DESC
        LIMIT 6
        """,
        (user_id,),
    ).fetchall()

    resumen = {
        "pacientes": conn.execute(
            "SELECT COUNT(*) FROM usuario WHERE rol = 'paciente'"
        ).fetchone()[0],
        "estudios": conn.execute(
            "SELECT COUNT(*) FROM imagen_citologica WHERE profesional_id = ?",
            (user_id,),
        ).fetchone()[0],
        "conversaciones": conn.execute(
            """
            SELECT COUNT(DISTINCT CASE
                WHEN emisor_id = ? THEN receptor_id
                WHEN receptor_id = ? THEN emisor_id
            END)
            FROM mensaje
            WHERE emisor_id = ? OR receptor_id = ?
            """,
            (user_id, user_id, user_id, user_id),
        ).fetchone()[0],
        "estudios_hoy": conn.execute(
            """
            SELECT COUNT(*)
            FROM imagen_citologica
            WHERE profesional_id = ?
              AND date(fecha) = date('now', 'localtime')
            """,
            (user_id,),
        ).fetchone()[0],
    }
    conn.close()

    return render_template(
        "profesional_home.html",
        profesional=profesional,
        pacientes=pacientes,
        estudios_recientes=estudios_recientes,
        resumen=resumen,
    )
