import os
import json
import requests
from datetime import date
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


# 1. Cargar conexion
load_dotenv()
db_url = os.getenv("DATABASE_URL")

# 2. Configurar parametros para Open-Meteo (Chiclayo)
latitud = "-6.7714"
longitud = "-79.8409"
ciudad = "Chiclayo"

# CORREGIDO: la fecha ya NO esta hardcodeada. Se usa la fecha actual
# del dia en que corre el script (cron diario), para que cada
# ejecucion inserte un dia nuevo en vez de repetir siempre 2026-09-07.
fecha_viaje = date.today().strftime("%Y-%m-%d")

url = f"https://api.open-meteo.com/v1/forecast?latitude={latitud}&longitude={longitud}&start_date={fecha_viaje}&end_date={fecha_viaje}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=America%2FLima"


try:
    print(f"\n[1/3] Consultando el clima para {ciudad} el {fecha_viaje}...")

    respuesta = requests.get(url)

    if respuesta.status_code == 200:
        datos_clima = respuesta.json()

        engine = create_engine(db_url)
        with engine.connect() as connection:
            # CORREGIDO: raw.weather_raw solo tiene PRIMARY KEY (id),
            # NO existe una restriccion UNIQUE sobre (city, target_date).
            # Por eso, en vez de usar ON CONFLICT (que fallaria con un
            # error de PostgreSQL al no existir esa restriccion), se
            # verifica manualmente si ya existe un registro para esta
            # ciudad y fecha antes de insertar. Esto evita filas
            # duplicadas que romperian el JOIN en vw_demand_features.
            existe_query = text("""
                SELECT COUNT(*) FROM raw.weather_raw
                WHERE city = :city AND target_date = :date
            """)
            ya_existe = connection.execute(existe_query, {
                "city": ciudad,
                "date": fecha_viaje
            }).scalar()

            if ya_existe > 0:
                print(f"[2/3] Ya existe un registro de clima para {ciudad} en {fecha_viaje}. No se duplica.")
                print("====================================================\n")
            else:
                print("[2/3] Datos obtenidos exitosamente. Guardando en Supabase...")
                insert_query = text("""
                    INSERT INTO raw.weather_raw (city, target_date, raw_data)
                    VALUES (:city, :date, :raw_json)
                """)
                connection.execute(insert_query, {
                    "city": ciudad,
                    "date": fecha_viaje,
                    "raw_json": json.dumps(datos_clima)
                })
                connection.commit()
                print("[3/3] Completado. El JSON del clima se inserto correctamente.")
                print("====================================================\n")
    else:
        print("\n[ERROR] La API del clima devolvio un error:", respuesta.status_code)

except Exception as e:
    print("\n[ERROR] Ocurrio un problema con el script del clima:")
    print(e)