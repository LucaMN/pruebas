from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import time
import re
import difflib
import ollama
import mysql.connector

# --- Configuración ---
NOMBRE_CONTACTO = "Pata de lana"
RESPONDER_AUTOMATICAMENTE = True  # False para solo probar sin enviar
TIEMPO_ESPERA_LOOP = 2  # segundos entre cada chequeo
DEBUG = True  # imprime qué ve el script en cada mensaje nuevo

# False (recomendado): solo se ignora lo que el propio bot envió (se reconoce
#   por su texto). Todo lo demás se responde, aunque WhatsApp lo marque como
#   "saliente".
# True: además ignora todo lo que el DOM marque como saliente (esa marca
#   resultó poco confiable en las pruebas).
IGNORAR_MENSAJES_SALIENTES = False

ESQUEMA = """Tabla usuario(
    id INT PRIMARY KEY AUTO_INCREMENT,
    nombre VARCHAR(50),
    apellido VARCHAR(50),
    dni INT
)"""

# --- Historial de respuestas enviadas por el bot (ya normalizadas) ---
respuestas_enviadas = []

# --- IDs de mensajes que ya vimos ---
ids_vistos = set()


def normalizar(texto: str) -> str:
    """Deja solo letras y números en minúscula.

    Así se ignoran emojis, espacios dobles, saltos de línea y signos al
    comparar. Es necesario porque WhatsApp muestra los emojis como imágenes:
    el texto que lee Selenium NO los incluye, y comparar el texto crudo
    fallaba (enviado '¡De nada! 😊 ¿...' vs leído '¡De nada!  ¿...')."""
    return re.sub(r"[\W_]+", "", texto.lower())


def es_respuesta_del_bot(texto: str) -> bool:
    """True si el texto es (prácticamente) algo que el bot ya envió."""
    t = normalizar(texto)
    if not t:
        return False
    for enviada in respuestas_enviadas:
        if t == enviada:
            return True
        # Margen por si WhatsApp altera algo mínimo al renderizar
        if len(t) >= 15 and difflib.SequenceMatcher(None, t, enviada).ratio() >= 0.9:
            return True
    return False


# --- Conexión a BD ---
def conectar_bd():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='',
        database='usuario'
    )


# --- Paso 1: Generar SQL a partir del mensaje ---
def generar_sql(mensaje: str) -> str:
    prompt = f"""/no_think
Sos un generador de consultas MySQL. Dado el siguiente esquema:
{ESQUEMA}

Generá ÚNICAMENTE la consulta SQL (SELECT) que responda al pedido del usuario.
No agregues explicaciones, ni texto adicional, ni bloques de markdown.
Si el pedido no se puede responder con una consulta SELECT sobre la tabla 'usuario', respondé exactamente: NO_CONSULTA

Pedido: {mensaje}"""

    respuesta = ollama.generate(model='qwen3:4b', prompt=prompt)['response']
    respuesta = re.sub(r"<think>.*?</think>", "", respuesta, flags=re.DOTALL)
    respuesta = re.sub(r"```(?:sql)?", "", respuesta, flags=re.IGNORECASE)
    return respuesta.strip().rstrip(";").strip()


# --- Validación de seguridad SQL ---
def es_consulta_segura(sql: str) -> bool:
    sql_min = sql.lower().strip()
    if not sql_min.startswith("select"):
        return False
    if ";" in sql:
        return False
    prohibidas = ["insert", "update", "delete", "drop", "alter",
                  "truncate", "create", "grant", "into outfile"]
    return not any(re.search(rf"\b{p}\b", sql_min) for p in prohibidas)


# --- Paso 2: Ejecutar SQL ---
def ejecutar_consulta(sql: str):
    conexion = conectar_bd()
    cursor = conexion.cursor(dictionary=True)
    try:
        cursor.execute(sql)
        return cursor.fetchall()
    except mysql.connector.Error as err:
        return f"Error SQL: {err}"
    finally:
        cursor.close()
        conexion.close()


# --- Paso 3: Generar respuesta natural ---
def generar_respuesta_natural(mensaje: str, resultados) -> str:
    prompt = f"""Sos una recepcionista amable de una inmobiliaria.
El cliente envió este mensaje por WhatsApp: "{mensaje}"

Consultaste la base de datos y obtuviste este resultado:
{resultados}

Respondé al cliente de forma natural, breve y cordial (como si fuera un mensaje de WhatsApp).
No menciones bases de datos, SQL ni términos técnicos. Solo dá la respuesta."""

    respuesta = ollama.generate(model='qwen3:4b', prompt=prompt)['response']
    respuesta = re.sub(r"<think>.*?</think>", "", respuesta, flags=re.DOTALL)
    return respuesta.strip()


# --- Procesar mensaje completo ---
def procesar_mensaje(mensaje: str) -> str:
    print(f"\n📩 Mensaje recibido: {mensaje}")

    sql = generar_sql(mensaje)
    print(f"🔧 SQL generado: {sql}")

    if sql == "NO_CONSULTA" or not es_consulta_segura(sql):
        respuesta = generar_respuesta_natural(
            mensaje,
            "No hay información relevante en la base de datos."
        )
        print(f"🤖 Respuesta IA: {respuesta}")
        return respuesta

    resultados = ejecutar_consulta(sql)
    print(f"🗄️ Resultados BD: {resultados}")

    respuesta = generar_respuesta_natural(mensaje, resultados)
    print(f"🤖 Respuesta IA: {respuesta}")
    return respuesta


# --- 🔒 Verificación: Estar en el chat correcto ---
def estamos_en_chat_correcto() -> bool:
    """Verifica que el chat actual sea el del contacto esperado."""
    try:
        header = driver.find_element(
            By.CSS_SELECTOR,
            'span[data-testid="conversation-info-header-chat-title"]'
        )
        return header.text.strip() == NOMBRE_CONTACTO
    except Exception:
        return False


# --- 🚀 Enviar mensaje por WhatsApp (con re-verificación) ---
def enviar_mensaje(texto: str) -> bool:
    """Escribe el texto en el input del chat activo y lo envía con Enter.
    Re-verifica que estamos en el chat correcto antes de enviar."""

    if not estamos_en_chat_correcto():
        print(f"⚠️ NO se envía: el chat activo no es '{NOMBRE_CONTACTO}'.")
        return False

    try:
        input_box = driver.find_element(
            By.CSS_SELECTOR,
            'div[data-testid="conversation-compose-box-input"]'
        )
        input_box.click()
        time.sleep(0.5)

        # Limpiar el input por si quedó algo escrito
        input_box.send_keys(Keys.CONTROL, "a")
        input_box.send_keys(Keys.DELETE)
        time.sleep(0.2)

        # Escribir el texto
        input_box.send_keys(texto)
        time.sleep(0.5)

        # Doble chequeo antes de presionar Enter
        if not estamos_en_chat_correcto():
            print("⚠️ Chat cambió mientras escribíamos. Abortando envío.")
            input_box.send_keys(Keys.CONTROL, "a")
            input_box.send_keys(Keys.DELETE)
            return False

        # Guardamos la respuesta ANTES de enviar, así cuando aparezca
        # en el chat ya la reconocemos como nuestra.
        respuestas_enviadas.append(normalizar(texto))
        if len(respuestas_enviadas) > 50:
            respuestas_enviadas.pop(0)

        # Enviar
        ActionChains(driver).send_keys(Keys.ENTER).perform()
        time.sleep(0.5)

        print(f"✅ Respuesta enviada por WhatsApp: {texto}")
        return True

    except Exception as e:
        print(f"❌ Error al enviar mensaje: {e}")
        return False


# --- Asegurar que estamos parados en el chat correcto ---
def ir_al_chat_del_contacto() -> bool:
    """Hace clic en el contacto si no estamos ya en su chat."""
    try:
        if estamos_en_chat_correcto():
            return True

        contacto = driver.find_element(
            By.CSS_SELECTOR, f'[title="{NOMBRE_CONTACTO}"]'
        )
        contacto.click()
        time.sleep(1.5)

        return estamos_en_chat_correcto()
    except Exception:
        return False


# --- 🌱 Marcar mensajes existentes al iniciar ---
def marcar_mensajes_iniciales():
    """Al arrancar, guarda los IDs de todos los mensajes que ya están en
    pantalla para no responder a mensajes viejos."""
    try:
        mensajes = driver.find_elements(By.CSS_SELECTOR, 'div[data-id]')
        for m in mensajes:
            mid = m.get_attribute('data-id')
            if mid:
                ids_vistos.add(mid)
        print(f"🌱 {len(ids_vistos)} mensajes preexistentes ignorados.")
    except Exception as e:
        print(f"⚠️ No se pudieron marcar los mensajes iniciales: {e}")


def es_mensaje_saliente(msg) -> bool:
    """Intenta detectar si WhatsApp marca el mensaje como saliente.
    Hoy solo se usa para diagnóstico (y si IGNORAR_MENSAJES_SALIENTES=True)."""
    clases = msg.get_attribute('class') or ""
    if "message-out" in clases:
        return True
    if "message-in" in clases:
        return False

    try:
        msg.find_element(By.CSS_SELECTOR, 'span[data-testid="tail-out"]')
        return True
    except Exception:
        pass

    try:
        msg.find_element(By.CSS_SELECTOR, '.message-out')
        return True
    except Exception:
        pass

    return False


def leer_texto(msg) -> str:
    """Devuelve el texto del mensaje ('' si no tiene)."""
    try:
        elementos = msg.find_elements(
            By.CSS_SELECTOR, 'span[data-testid="selectable-text"]'
        )
        return " ".join(e.text.strip() for e in elementos if e.text.strip())
    except Exception:
        return ""


# --- Selenium: conexión a WhatsApp ---
options = Options()
options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=options)

print("Conectado a WhatsApp Web")
print(f"Buscando mensajes de: {NOMBRE_CONTACTO}")

# Ir al chat del contacto al iniciar
if ir_al_chat_del_contacto():
    print(f"✅ Chat de '{NOMBRE_CONTACTO}' abierto.")
else:
    print(f"⚠️ No se pudo abrir el chat de '{NOMBRE_CONTACTO}'. Esperando...")

# Marcar los mensajes actuales como vistos (evita responder viejos)
marcar_mensajes_iniciales()

print("\n🟢 Escuchando mensajes nuevos...\n")

# --- Loop principal ---
try:
    while True:
        try:
            # Asegurarnos de estar en el chat correcto
            if not estamos_en_chat_correcto():
                if not ir_al_chat_del_contacto():
                    print(f"Esperando a {NOMBRE_CONTACTO}...")
                    time.sleep(3)
                    continue

            # Obtener mensajes (en orden cronológico)
            mensajes = driver.find_elements(By.CSS_SELECTOR, 'div[data-id]')

            # Juntar solo los que nunca vimos
            nuevos = []
            for msg in mensajes:
                try:
                    mid = msg.get_attribute('data-id')
                except Exception:
                    continue
                if mid and mid not in ids_vistos:
                    ids_vistos.add(mid)
                    nuevos.append(msg)

            for msg in nuevos:
                try:
                    saliente = es_mensaje_saliente(msg)
                    texto_mensaje = leer_texto(msg)
                    clase = (msg.get_attribute('class') or "")[:80]
                except Exception as e:
                    if DEBUG:
                        print(f"👀 Elemento nuevo ilegible ({e})")
                    continue

                if DEBUG:
                    print(f"👀 Elemento nuevo | saliente={saliente} | "
                          f"texto={texto_mensaje[:60]!r} | clase={clase!r}")

                if not texto_mensaje:
                    continue

                # 1) Lo que envió el bot: se reconoce por su texto
                if es_respuesta_del_bot(texto_mensaje):
                    print("↩️ Ignorado: es una respuesta del bot.")
                    continue

                # 2) Opcional: ignorar todo lo que el DOM marque como saliente
                if saliente and IGNORAR_MENSAJES_SALIENTES:
                    print("↩️ Ignorado: marcado como saliente.")
                    continue

                # Procesar con IA y responder
                respuesta = procesar_mensaje(texto_mensaje)

                if RESPONDER_AUTOMATICAMENTE and respuesta:
                    enviar_mensaje(respuesta)
                    time.sleep(1.5)

            time.sleep(TIEMPO_ESPERA_LOOP)

        except Exception as e:
            print(f"Esperando a {NOMBRE_CONTACTO}... ({e})")
            time.sleep(3)
finally:
    print("🔴 El script se detuvo")