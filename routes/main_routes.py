from flask import Blueprint, redirect, render_template, session, url_for

main = Blueprint("main", __name__)


@main.route("/")
def index():
    if session.get("rol") == "paciente":
        return redirect(url_for("dashboard.paciente_home"))
    if session.get("rol") == "profesional":
        return redirect(url_for("dashboard.profesional_home"))
    return render_template("index.html")
