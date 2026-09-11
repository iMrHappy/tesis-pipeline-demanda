import os
import requests
import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Configuración inicial
load_dotenv()
db_url = os.getenv("DATABASE_URL")
api_key = os.getenv("TOMTOM_API_KEY")

try:
    engine = create_engine(db_url)
    print("\n[1/3] Consultando el tráfico satelital de TomTom (Lima -> Chiclayo)...")
    
    # Coordenadas exactas
    origen = "-12.0464,-77.0428"
    destino = "-6.7714,-79.8409"
    
    # Construir la URL
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{origen}:{destino}/json"
    params = {
        "key": api_key,
        "traffic": "true",
        "routeType": "fastest",
        "travelMode": "bus"
    }
    
    response = requests.get(url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        summary = data['routes'][0]['summary']
        
        # Extracción segura: usamos .get() para evitar KeyErrors
        # Si no hay tráfico, TomTom podría omitir la llave, así que ponemos 0 por defecto
        current_time_sec = summary.get('travelTimeInSeconds', 0)
        delay_sec = summary.get('trafficDelayInSeconds', 0)
        
        # Matemáticas simples: Tiempo sin tráfico es el real menos la demora
        normal_time_sec = current_time_sec - delay_sec
        
        # Convertir a minutos
        normal_time_min = normal_time_sec // 60
        current_time_min = current_time_sec // 60
        delay_min = delay_sec // 60
        
        hoy = datetime.datetime.now().date()
        
        print(f"[2/3] Datos de tráfico calculados:")
        print(f"      - Fecha de medición : {hoy}")
        print(f"      - Tiempo Ideal : {normal_time_min} mins")
        print(f"      - Tiempo Real Hoy: {current_time_min} mins")
        print(f"      - Retraso en Ruta : {delay_min} mins")
        
        # 3. Guardar en Supabase
        with engine.connect() as connection:
            query = text("""
                INSERT INTO staging.fact_route_traffic (
                    target_date, route_name, normal_travel_time_min, current_travel_time_min, traffic_delay_min
                ) VALUES (
                    :date, :route, :normal, :current, :delay
                )
                ON CONFLICT (target_date) DO UPDATE 
                SET normal_travel_time_min = EXCLUDED.normal_travel_time_min,
                    current_travel_time_min = EXCLUDED.current_travel_time_min,
                    traffic_delay_min = EXCLUDED.traffic_delay_min;
            """)
            
            connection.execute(query, {
                "date": hoy,
                "route": "Lima-Chiclayo",
                "normal": normal_time_min,
                "current": current_time_min,
                "delay": delay_min
            })
            connection.commit()
            
        print("\n[3/3] ¡Éxito! Tiempos de viaje inyectados en la base de datos.")
        print("====================================================\n")
    else:
        print(f"[ERROR] La API de TomTom devolvió el código: {response.status_code}")
        print(response.text)

except Exception as e:
    print("\n[ERROR] Ocurrió un problema en la extracción de tráfico:")
    print(e)