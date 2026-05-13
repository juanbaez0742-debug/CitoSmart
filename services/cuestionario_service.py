from models.database import get_connection

def guardar_paciente(data):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO paciente (nombre, edad, sintomas, antecedentes)
        VALUES (?, ?, ?, ?)
    """, (
        data['nombre'],
        data['edad'],
        data['sintomas'],
        data['antecedentes']
    ))

    conn.commit()
    conn.close()

def guardar_profesional(data):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO profesional (nombre, especialidad, experiencia, evaluacion)
        VALUES (?, ?, ?, ?)
    """, (
        data['nombre'],
        data['especialidad'],
        data['experiencia'],
        data['evaluacion']
    ))

    conn.commit()
    conn.close()