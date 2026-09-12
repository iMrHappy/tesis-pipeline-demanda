import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from apify_client import ApifyClient
from sqlalchemy import create_engine, text

# 1. Cargar variables de entorno
load_dotenv()
apify_token = os.getenv("APIFY_API_TOKEN")
db_url = os.getenv("DATABASE_URL")

try:
    engine = create_engine(db_url)
    client = ApifyClient(apify_token)
    
    # 2. Generar fecha dinámica (Mañana) para el análisis de demanda
    fecha_viaje = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"\n[1/3] Solicitando datos en Apify para viajes el: {fecha_viaje}...")
    
    run_input = {
        "country": "peru",
        "dateOfJourney": fecha_viaje,
        "destination": "Chiclayo",
        "source": "Lima",
        "maxItems": 15, # Aumentado para tener una muestra estadística más robusta
        "proxyConfiguration": {
            "useApifyProxy": True
        }
    }
    
    run = client.actor("rl1987/redbus-api-scraper").call(run_input=run_input)
    estado = getattr(run, "status", None)
    id_dataset = getattr(run, "default_dataset_id", getattr(run, "defaultDatasetId", None))
    
    if estado != "SUCCEEDED":
        print(f"\n[ADVERTENCIA] La extracción falló. Estado final: {estado}")
    else:
        dataset = list(client.dataset(id_dataset).iterate_items())
        print(f"[2/3] Extracción exitosa. {len(dataset)} buses encontrados. Guardando en BD...")
        
        # 3. Inserción en Supabase
        with engine.connect() as connection:
            query = text("""
                INSERT INTO staging.fact_redbus_snapshots (
                    extraction_timestamp, operator_name, bus_type, source_city, 
                    destination_city, departure_time, total_seats, available_seats, min_fare
                ) VALUES (
                    CURRENT_TIMESTAMP, :operator, :type, 'Lima', 'Chiclayo', 
                    :dep_time, :total, :avail, :fare
                )
            """)
            
            for item in dataset:
                # El .get() captura los campos del JSON. Los valores a la derecha son fallbacks por si viene nulo.
                connection.execute(query, {
                    "operator": item.get("travelsName", "Desconocido"),
                    "type": item.get("busType", "Estandar"),
                    "dep_time": item.get("departureTime", f"{fecha_viaje} 00:00:00"), 
                    "total": int(item.get("totalSeats", 0) or 0),
                    "avail": int(item.get("availableSeats", 0) or 0),
                    "fare": float(item.get("fare", item.get("baseFare", 0)) or 0)
                })
            connection.commit()
            
        print("[3/3] ¡Éxito! Oferta y precios de redBus inyectados en Supabase.\n")

except Exception as e:
    print("\n[ERROR] Ocurrió un problema:")
    print(type(e).__name__, e)