import base64
import json
import mimetypes
from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from models.database import get_connection
from services.ia_analisis import PREDICTOR, ejecutar_modelo

ia = Blueprint("ia", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _require_login(role=None):
    if "user_id" not in session:
        return False
    if role and session.get("rol") != role:
        return False
    return True


def _build_probability_summary(probabilidades):
    if not probabilidades:
        return None

    top = probabilidades[0]
    summary = {
        "top_display_name": top.get("display_name", top.get("label", "Sin clase")),
        "top_probability": top.get("probability", 0),
        "uncertainty_label": "Baja",
        "uncertainty_message": "La clase principal se separa con claridad de las alternativas mostradas.",
    }

    if len(probabilidades) < 2:
        return summary

    second = probabilidades[1]
    margin = float(top.get("probability", 0)) - float(second.get("probability", 0))

    if margin < 8:
        summary["uncertainty_label"] = "Alta"
        summary["uncertainty_message"] = (
            "Las dos clases mas probables estan muy cercanas; conviene revisar la muestra con especial cautela."
        )
    elif margin < 15:
        summary["uncertainty_label"] = "Moderada"
        summary["uncertainty_message"] = (
            "La clase principal aventaja a la siguiente, pero la diferencia aun sugiere revisar alternativas cercanas."
        )

    return summary


def _active_model_info():
    metadata = PREDICTOR.metadata
    class_names = metadata.get("target_classes") or metadata.get("class_names", [])
    display_names = metadata.get("display_names", {})
    image_size = metadata.get("image_size", [224, 224])
    is_two_stage = bool(metadata.get("stage1_class_names")) and bool(metadata.get("stage2_class_names"))
    return {
        "class_labels": [
            display_names.get(class_name.lower(), class_name) for class_name in class_names
        ],
        "image_size": image_size,
        "model_scope": "triaje citologico en dos etapas"
        if is_two_stage
        else (
            "triaje citologico proxy de 3 clases"
            if len(class_names) == 3
            else "clasificacion citologica configurada"
        ),
    }


@ia.route("/ia/health")
def ia_health():
    PREDICTOR._ensure_loaded()
    loaded_model = (
        PREDICTOR.model is not None
        or (
            PREDICTOR.stage1_model is not None
            and PREDICTOR.stage2_model is not None
        )
    )
    return jsonify(
        {
            "loaded_model": loaded_model,
            "model_error": PREDICTOR.model_error,
            "model_path": PREDICTOR.model_path,
            "active_model": _active_model_info(),
        }
    )


def _load_study(estudio_id):
    conn = get_connection()
    estudio = conn.execute(
        """
        SELECT
            i.*,
            p.nombre AS paciente_nombre,
            p.email AS paciente_email,
            pr.nombre AS profesional_nombre
        FROM imagen_citologica i
        JOIN usuario p ON p.id = i.paciente_id
        JOIN usuario pr ON pr.id = i.profesional_id
        WHERE i.id = ?
        """,
        (estudio_id,),
    ).fetchone()
    conn.close()
    return estudio


def _authorize_study_access(estudio):
    if not estudio:
        abort(404)

    if session.get("rol") == "paciente" and estudio["paciente_id"] != session["user_id"]:
        abort(403)
    if session.get("rol") == "profesional" and estudio["profesional_id"] != session["user_id"]:
        abort(403)


def _study_view_context(estudio):
    probabilidades = []
    if estudio["probabilidades_ia"]:
        try:
            probabilidades = json.loads(estudio["probabilidades_ia"])
        except json.JSONDecodeError:
            probabilidades = []
    probability_summary = _build_probability_summary(probabilidades)

    if estudio["estado_ia"] in {"bloqueado", "error_modelo"}:
        recomendaciones = [
            "Confirmar que la imagen corresponde a una muestra citologica adecuada antes de volver a analizarla.",
            "Revisar manualmente la muestra y considerar una nueva captura si la calidad o el encuadre no son adecuados.",
            "No usar esta salida para concluir una clasificacion celular automatica definitiva.",
        ]
    else:
        recomendaciones = [
            "Correlacionar la clasificacion celular con el contexto clinico y los antecedentes reportados.",
            "Verificar la calidad de la muestra y repetir el estudio si el profesional lo considera necesario.",
            "Usar la salida de IA como apoyo a la revision profesional, no como diagnostico definitivo.",
        ]
    limitaciones = [
        "El modelo clasifica patrones celulares del dataset de entrenamiento y no emite un diagnostico histopatologico definitivo.",
        "El rendimiento puede variar si la imagen proviene de otro laboratorio, otra tincion o una calidad de captura distinta.",
        "La interpretacion final debe integrar revision profesional, calidad de muestra y contexto clinico del paciente.",
    ]

    return {
        "estudio": estudio,
        "recomendaciones": recomendaciones,
        "probabilidades": probabilidades,
        "probability_summary": probability_summary,
        "limitaciones": limitaciones,
        "analysis_blocked": estudio["estado_ia"] in {"bloqueado", "error_modelo"},
        "analysis_unavailable": estudio["estado_ia"] == "error_modelo",
        "active_model": _active_model_info(),
    }


def _embedded_image_data(filename):
    image_path = Path(current_app.config["UPLOAD_FOLDER"]) / filename
    if not image_path.exists():
        return None

    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    with image_path.open("rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


@ia.route("/uploads/<path:filename>")
def archivo_subido(filename):
    if not _require_login():
        return redirect(url_for("auth.login"))
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)


@ia.route("/subir_imagen", methods=["GET", "POST"])
def subir_imagen():
    if not _require_login("profesional"):
        return redirect(url_for("auth.login"))

    conn = get_connection()
    pacientes = conn.execute(
        """
        SELECT id, nombre, email, motivo_consulta
        FROM usuario
        WHERE rol = 'paciente'
        ORDER BY nombre
        """
    ).fetchall()
    selected_patient_id = request.args.get("paciente_id", "").strip()

    if request.method == "POST":
        paciente_id = request.form.get("paciente_id", "").strip()
        titulo = request.form.get("titulo", "").strip() or "Estudio citologico"
        observaciones = request.form.get("observaciones", "").strip()
        diagnostico_profesional = request.form.get("diagnostico_profesional", "").strip()
        imagen = request.files.get("imagen")

        if not paciente_id:
            conn.close()
            return render_template(
                "subir_imagen.html",
                pacientes=pacientes,
                selected_patient_id=selected_patient_id,
                error="Selecciona un paciente antes de continuar.",
                active_model=_active_model_info(),
            )

        if not imagen or not imagen.filename:
            conn.close()
            return render_template(
                "subir_imagen.html",
                pacientes=pacientes,
                selected_patient_id=selected_patient_id,
                error="Debes seleccionar una imagen para analizar.",
                active_model=_active_model_info(),
            )

        if not _allowed_file(imagen.filename):
            conn.close()
            return render_template(
                "subir_imagen.html",
                pacientes=pacientes,
                selected_patient_id=selected_patient_id,
                error="Formato no permitido. Usa PNG, JPG, JPEG, WEBP o GIF.",
                active_model=_active_model_info(),
            )

        ext = imagen.filename.rsplit(".", 1)[1].lower()
        filename = secure_filename(f"{uuid4().hex}.{ext}")
        destino = Path(current_app.config["UPLOAD_FOLDER"]) / filename
        imagen.save(destino)

        analisis = ejecutar_modelo(destino, observaciones)
        cursor = conn.execute(
            """
            INSERT INTO imagen_citologica (
                profesional_id, paciente_id, ruta_imagen, resultado_ia, titulo,
                observaciones, diagnostico_profesional, nivel_riesgo, confianza, resumen_ia,
                probabilidades_ia, estado_ia
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["user_id"],
                paciente_id,
                filename,
                analisis["clasificacion"],
                titulo,
                observaciones,
                diagnostico_profesional,
                analisis["nivel_riesgo"],
                analisis["confianza"],
                analisis["resumen"],
                json.dumps(analisis.get("probabilidades", []), ensure_ascii=False),
                analisis.get("estado", "valido"),
            ),
        )
        estudio_id = cursor.lastrowid

        asignacion = conn.execute(
            """
            SELECT id
            FROM asignacion
            WHERE profesional_id = ? AND paciente_id = ?
            """,
            (session["user_id"], paciente_id),
        ).fetchone()

        if not asignacion:
            conn.execute(
                """
                INSERT INTO asignacion (profesional_id, paciente_id, evaluacion, notas)
                VALUES (?, ?, ?, ?)
                """,
                (
                    session["user_id"],
                    paciente_id,
                    analisis["clasificacion"],
                    observaciones,
                ),
            )

        detalle = (
            f"Resultado IA: {analisis['clasificacion']}. "
            f"Nivel de riesgo: {analisis['nivel_riesgo']}. "
            f"Diagnostico profesional: {diagnostico_profesional or 'Pendiente de comentario adicional'}."
        )
        conn.execute(
            """
            INSERT INTO historial_medico (
                paciente_id, titulo, tipo, descripcion, detalle, origen, profesional_id, estudio_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paciente_id,
                titulo,
                "diagnostico",
                analisis["clasificacion"],
                detalle,
                "ia",
                session["user_id"],
                estudio_id,
            ),
        )
        conn.commit()
        conn.close()

        return redirect(url_for("ia.resultado", estudio_id=estudio_id))

    conn.close()
    return render_template(
        "subir_imagen.html",
        pacientes=pacientes,
        selected_patient_id=selected_patient_id,
        error=None,
        active_model=_active_model_info(),
    )


@ia.route("/resultado/<int:estudio_id>")
def resultado(estudio_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    estudio = _load_study(estudio_id)
    _authorize_study_access(estudio)
    return render_template("resultado.html", **_study_view_context(estudio))


@ia.route("/resultado/<int:estudio_id>/reporte")
def descargar_reporte(estudio_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    estudio = _load_study(estudio_id)
    _authorize_study_access(estudio)
    context = _study_view_context(estudio)
    context["image_data_uri"] = _embedded_image_data(estudio["ruta_imagen"])

    report_html = render_template("reporte_estudio.html", **context)
    response = make_response(report_html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="reporte_estudio_{estudio_id}.html"'
    )
    return response


@ia.route("/resultado/<int:estudio_id>/reporte/imprimible")
def reporte_imprimible(estudio_id):
    if not _require_login():
        return redirect(url_for("auth.login"))

    estudio = _load_study(estudio_id)
    _authorize_study_access(estudio)
    context = _study_view_context(estudio)
    context["image_data_uri"] = _embedded_image_data(estudio["ruta_imagen"])
    context["print_mode"] = True
    return render_template("reporte_estudio.html", **context)
