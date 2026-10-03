from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

NOMBRE_CONTACTO = "Pata de lana"

options = Options()
options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

driver = webdriver.Chrome(options=options)

print("Conectado a WhatsApp Web")
print(f"Buscando mensajes de: {NOMBRE_CONTACTO}")

# Variable para recordar el último mensaje procesado y no repetirlo
ultimo_mensaje = None
# Variable para recordar el ID del último mensaje procesado
ultimo_id_mensaje = None

while True:
    try:
        # --- PASO 1: Encontrar y hacer clic en el contacto ---
        # Usamos el título que es más estable que las clases
        contacto = driver.find_element(By.CSS_SELECTOR, f'[title="{NOMBRE_CONTACTO}"]')
        
        # Verificamos si ya estamos en el chat correcto para no hacer clic siempre
        try:
            # Buscamos el encabezado del chat para ver si coincide el nombre
            header_title = driver.find_element(By.CSS_SELECTOR, 'span[data-testid="conversation-info-header-chat-title"]').text
            if header_title != NOMBRE_CONTACTO:
                contacto.click()
                time.sleep(1.5) # Esperamos a que cargue el chat
        except:
            # Si no encontramos el header, es porque no estamos en un chat, hacemos clic
            contacto.click()
            time.sleep(1.5)

        # --- PASO 2: Buscar los mensajes en el chat ---
        # Buscamos TODOS los contenedores de mensajes en el chat actual.
        # El atributo 'data-id' es único para cada mensaje.
        mensajes = driver.find_elements(By.CSS_SELECTOR, 'div[data-id]')

        if not mensajes:
            # Si no hay mensajes, esperamos un poco y volvemos a intentar
            time.sleep(2)
            continue

        # --- PASO 3: Identificar el último mensaje y su remitente ---
        # Iteramos sobre los mensajes desde el final hacia atrás para encontrar el último
        for msg in reversed(mensajes):
            msg_id = msg.get_attribute('data-id')
            
            # Si ya procesamos este mensaje, saltamos al siguiente
            if msg_id == ultimo_id_mensaje:
                break # Ya llegamos a un mensaje ya procesado, salimos del bucle

            # Dentro del contenedor del mensaje, buscamos la "colita" del mensaje.
            # 'tail-out' significa que el mensaje es NUESTRO (saliente).
            # 'tail-in' significa que el mensaje es de la OTRA PERSONA (entrante).
            es_mensaje_saliente = False
            try:
                # Buscamos el elemento span con data-testid="tail-out"
                msg.find_element(By.CSS_SELECTOR, 'span[data-testid="tail-out"]')
                es_mensaje_saliente = True
            except:
                # Si no encontramos 'tail-out', podría ser un mensaje entrante
                pass

            # Si el mensaje NO es saliente (es entrante), lo procesamos
            if not es_mensaje_saliente:
                # Buscamos el texto DENTRO de este contenedor de mensaje específico.
                # Usamos el selector 'span[data-testid="selectable-text"]' que es muy específico.
                try:
                    texto_elemento = msg.find_element(By.CSS_SELECTOR, 'span[data-testid="selectable-text"]')
                    texto_mensaje = texto_elemento.text.strip()
                    
                    # Verificamos que el texto no esté vacío y que sea diferente al último
                    if texto_mensaje and texto_mensaje != ultimo_mensaje:
                        ultimo_mensaje = texto_mensaje
                        ultimo_id_mensaje = msg_id # Guardamos el ID para no repetirlo
                        
                        print()
                        print("================================")
                        print(f"MENSAJE NUEVO DE {NOMBRE_CONTACTO}:")
                        print(texto_mensaje)
                        print("================================")
                        print()
                
                except Exception as e:
                    # Si no encontramos el texto, probablemente sea un sticker, imagen, etc.
                    # Lo marcamos como procesado para no volver a intentarlo
                    ultimo_id_mensaje = msg_id
                    # print(f"Mensaje sin texto (posiblemente multimedia): {msg_id}")

            # Si encontramos un mensaje entrante nuevo, ya no necesitamos seguir mirando los antiguos
            if not es_mensaje_saliente and msg_id == ultimo_id_mensaje:
                 break

        # --- PASO 4: Esperar antes de la siguiente comprobación ---
        time.sleep(2)

    except Exception as e:
        # Este error suele ocurrir si no encuentra el contacto
        print(f"Esperando a {NOMBRE_CONTACTO}... (Asegúrate de que el chat esté visible o el contacto exista)")
        time.sleep(3)