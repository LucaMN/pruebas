import mysql.connector

#Funcion que permite realizar la conexion a la bd
def conexionBaseDatos():
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