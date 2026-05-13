from flask import Blueprint, redirect, url_for

cuestionarios = Blueprint("cuestionarios", __name__)


@cuestionarios.route("/paciente", methods=["GET"])
def paciente():
    return redirect(url_for("auth.register", rol="paciente"))


@cuestionarios.route("/profesional", methods=["GET"])
def profesional():
    return redirect(url_for("auth.register", rol="profesional"))


@cuestionarios.route("/gracias")
def gracias():
    return redirect(url_for("auth.login"))
