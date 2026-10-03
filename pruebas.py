import re
import ollama
import mysql.connector

# --- Conexión ---
try:
    conexion = mysql.connector.connect(
        host='localhost',
        user='root',
        password='',
        database='usuario'
    )
except mysql.connector.Error as err:
    print(f"Error al conectar a la base de datos: {err}")
    raise SystemExit(1)

ESQUEMA = """Tabla usuario(
    id INT PRIMARY KEY AUTO_INCREMENT,
    nombre VARCHAR(50),
    apellido VARCHAR(50),
    dni INT
)"""


def generar_sql(pregunta: str) -> str:
    prompt = f"""/no_think
Sos un generador de consultas MySQL.
Esquema:
{ESQUEMA}

Devolveme la informacion con un lenguaje natural, no me des la consulta SQL, sos una recepcionista de una inmobiliaria

Pedido: {pregunta}"""

    respuesta = ollama.generate(model='qwen3:4b', prompt=prompt)['response']

    # Quitar bloque <think>...</think> si el modelo lo genera igual
    respuesta = re.sub(r"<think>.*?</think>", "", respuesta, flags=re.DOTALL)
    # Quitar cercos de markdown ```sql ... ```
    respuesta = re.sub(r"```(?:sql)?", "", respuesta, flags=re.IGNORECASE)

    return respuesta.strip().rstrip(";").strip()


def es_consulta_segura(sql: str) -> bool:
    sql_min = sql.lower()
    if not sql_min.startswith("select"):
        return False
    if ";" in sql:  # evita múltiples sentencias
        return False
    prohibidas = ["insert", "update", "delete", "drop", "alter",
                  "truncate", "create", "grant", "into outfile"]
    return not any(re.search(rf"\b{p}\b", sql_min) for p in prohibidas)


pregunta = "Hola, hay personas con el nombre Valentina?"

sql = generar_sql(pregunta)
print("SQL generado:", sql)

if not es_consulta_segura(sql):
    print("La consulta generada no es segura, no se ejecuta.")
else:
    cursor = conexion.cursor(dictionary=True)
    try:
        cursor.execute(sql)
        for fila in cursor.fetchall():
            print(fila)
    except mysql.connector.Error as err:
        print(f"Error al ejecutar la consulta: {err}")
    finally:
        cursor.close()

conexion.close()