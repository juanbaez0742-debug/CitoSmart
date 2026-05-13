import sqlite3
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "database.db"))).expanduser()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_exists(conn, table_name, column_name):
    columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(column[1] == column_name for column in columns)


def _add_column_if_missing(conn, table_name, definition):
    column_name = definition.split()[0]
    if not _column_exists(conn, table_name, column_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS usuario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            rol TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS paciente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            edad INTEGER,
            sintomas TEXT,
            antecedentes TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS profesional (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            especialidad TEXT,
            experiencia TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS imagen_citologica (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profesional_id INTEGER,
            paciente_id INTEGER,
            ruta_imagen TEXT,
            resultado_ia TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS asignacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profesional_id INTEGER,
            paciente_id INTEGER,
            evaluacion TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS mensaje (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emisor_id INTEGER,
            receptor_id INTEGER,
            contenido TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS historial_medico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER,
            descripcion TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    usuario_columns = [
        "nombre TEXT",
        "email TEXT",
        "telefono TEXT",
        "fecha_nacimiento TEXT",
        "edad INTEGER",
        "genero TEXT",
        "direccion TEXT",
        "antecedentes TEXT",
        "alergias TEXT",
        "motivo_consulta TEXT",
        "especialidad TEXT",
        "cedula TEXT",
        "institucion TEXT",
        "experiencia TEXT",
        "biografia TEXT",
        "perfil_completado INTEGER DEFAULT 1",
        "created_at TEXT",
    ]
    imagen_columns = [
        "titulo TEXT",
        "observaciones TEXT",
        "diagnostico_profesional TEXT",
        "nivel_riesgo TEXT",
        "confianza TEXT",
        "resumen_ia TEXT",
        "probabilidades_ia TEXT",
        "estado_ia TEXT",
    ]
    historial_columns = [
        "titulo TEXT",
        "tipo TEXT",
        "detalle TEXT",
        "origen TEXT",
        "profesional_id INTEGER",
        "estudio_id INTEGER",
    ]
    asignacion_columns = [
        "estado TEXT DEFAULT 'activo'",
        "notas TEXT",
        "fecha TEXT",
    ]
    mensaje_columns = ["leido INTEGER DEFAULT 0"]

    for column in usuario_columns:
        _add_column_if_missing(conn, "usuario", column)
    for column in imagen_columns:
        _add_column_if_missing(conn, "imagen_citologica", column)
    for column in historial_columns:
        _add_column_if_missing(conn, "historial_medico", column)
    for column in asignacion_columns:
        _add_column_if_missing(conn, "asignacion", column)
    for column in mensaje_columns:
        _add_column_if_missing(conn, "mensaje", column)

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuario_username ON usuario(username)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_usuario_rol ON usuario(rol)"
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_imagen_paciente_profesional
        ON imagen_citologica(paciente_id, profesional_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mensaje_participantes
        ON mensaje(emisor_id, receptor_id, fecha)
        """
    )

    conn.commit()
    conn.close()
