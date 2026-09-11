import os
import json
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Cargar conexión
load_dotenv()
db_url = os.getenv("DATABASE_URL")

# 2. Configurar parámetros para Open-Meteo (Chiclayo)
# Coordenadas aproximadas de Chiclayo
latitud = "-6.7714"
longitud = "-79.8409"
ciudad = "Chiclayo"
fecha_viaje = "2026-09-07"

# URL de la API de Open-Meteo (pedimos temperatura máxima, mínima y precipitación)
url = f"https://api.open-meteo.com/v1/forecast?latitude={latitud}&longitude={longitud}&start_date={fecha_viaje}&end_date={fecha_viaje}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=America%2FLima"

try:
    print(f"\n[1/3] Consultando el clima para {ciudad} el {fecha_viaje}...")
    
    # 3. Hacer la petición a la API
    respuesta = requests.get(url)
    
    if respuesta.status_code == 200:
        datos_clima = respuesta.json()
        print("[2/3] Datos obtenidos exitosamente. Guardando en Supabase...")
        
        # 4. Guardar el JSON crudo en la base de datos
        engine = create_engine(db_url)
        with engine.connect() as connection:
            query = text("""
                INSERT INTO raw.weather_raw (city, target_date, raw_data)
                VALUES (:city, :date, :raw_json)
            """)
            
            connection.execute(query, {
                "city": ciudad,
                "date": fecha_viaje,
                "raw_json": json.dumps(datos_clima)
            })
            connection.commit()
            
            print("[3/3] ¡Completado! El JSON del clima se insertó correctamente.")
            print("====================================================\n")
    else:
        print("\n[ERROR] La API del clima devolvió un error:", respuesta.status_code)

except Exception as e:
    print("\n[ERROR] Ocurrió un problema con el script del clima:")
    print(e)