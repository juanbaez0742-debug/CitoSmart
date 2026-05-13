import os
import sys
import threading
import webbrowser
from datetime import timedelta
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
BASE_DIR = THIS_FILE.parent
SHORT_APP_DIR = Path(r"C:\CitoSmart_clean")
BOOTSTRAP_FLAG = "CITOSMART_BOOTSTRAPPED"


def _maybe_relaunch_with_project_python():
    if os.environ.get(BOOTSTRAP_FLAG) == "1":
        return

    preferred_targets = [
        (
            SHORT_APP_DIR / ".venv311" / "Scripts" / "python.exe",
            SHORT_APP_DIR / "app.py",
        ),
        (
            BASE_DIR / ".venv311" / "Scripts" / "python.exe",
            THIS_FILE,
        ),
    ]

    current_python = Path(sys.executable).resolve()
    current_app = THIS_FILE

    for python_path, app_path in preferred_targets:
        if not python_path.exists() or not app_path.exists():
            continue

        if current_python == python_path.resolve() and current_app == app_path.resolve():
            return

        os.environ[BOOTSTRAP_FLAG] = "1"
        os.execv(str(python_path), [str(python_path), str(app_path), *sys.argv[1:]])


_maybe_relaunch_with_project_python()

from flask import Flask, redirect, request, session, url_for

from models.database import get_connection, init_db
from routes.auth_routes import auth
from routes.chat_routes import chat
from routes.cuestionarios_routes import cuestionarios
from routes.dashboard_routes import dashboard
from routes.ia_routes import ia
from routes.main_routes import main


app = Flask(
    __name__,
    static_folder="statics",
    static_url_path="/static",
    template_folder="templates",
)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "citosmart_clave_super_secreta")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "uploads"))
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

init_db()

app.register_blueprint(main)
app.register_blueprint(cuestionarios)
app.register_blueprint(auth)
app.register_blueprint(ia)
app.register_blueprint(dashboard)
app.register_blueprint(chat)


@app.before_request
def _lock_private_flow_until_profile_is_complete():
    endpoint = request.endpoint or ""
    if endpoint.startswith("static"):
        return None

    public_endpoints = {
        "main.index",
        "auth.login",
        "auth.register",
        "auth.logout",
    }
    profile_endpoints = {
        "auth.complete_profile",
        "auth.logout",
    }

    user_id = session.get("user_id")
    if not user_id:
        if endpoint in public_endpoints:
            return None
        return redirect(url_for("auth.login"))

    conn = get_connection()
    user = conn.execute(
        "SELECT id, rol, nombre, username, perfil_completado FROM usuario WHERE id = ?",
        (user_id,),
    ).fetchone()
    conn.close()

    if not user:
        session.clear()
        return redirect(url_for("auth.login"))

    session["rol"] = user["rol"]
    session["nombre"] = user["nombre"] or user["username"]

    if not user["perfil_completado"] and endpoint not in profile_endpoints:
        return redirect(url_for("auth.complete_profile"))

    return None


if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5001")).start()
    app.run(debug=True, port=5001)


def create_app():
    return app
