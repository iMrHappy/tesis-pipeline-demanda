import os
import json
from dotenv import load_dotenv
from apify_client import ApifyClient
from sqlalchemy import create_engine, text

# 1. Cargar todas las credenciales de seguridad
load_dotenv()
apify_token = os.getenv("APIFY_API_TOKEN")
db_url = os.getenv("DATABASE_URL")

try:
    # 2. Inicializar conectores
    client = ApifyClient(apify_token)
    engine = create_engine(db_url)
    
    print("\n[1/3] Conectando a Apify para extraer datos de Lima a Chiclayo...")
    
    # Parámetros de búsqueda
    run_input = {
        "country": "peru",
        "dateOfJourney": "2026-09-07",
        "destination": "Chiclayo",
        "source": "Lima",
        "maxItems": 5, 
        "proxyConfiguration": {
            "useApifyProxy": True
        }
    }
    
    # Ejecutar extracción
    run = client.actor("rl1987/redbus-api-scraper").call(run_input=run_input)
    estado = getattr(run, "status", None)
    id_dataset = getattr(run, "default_dataset_id", getattr(run, "defaultDatasetId", None))
    
    if estado != "SUCCEEDED":
        print("\n[ADVERTENCIA] La extracción falló. Estado:", estado)
    else:
        print("[2/3] Extracción exitosa. Guardando en Supabase (PostgreSQL)...")
        
        # 3. Conectar a la base de datos e insertar los datos iterativamente
        with engine.connect() as connection:
            query = text("""
                INSERT INTO raw.redbus_services_raw 
                (source_city, destination_city, date_of_journey, raw_data)
                VALUES (:source, :destination, :date_journey, :raw_json)
            """)
            
            contador = 0
            for item in client.dataset(id_dataset).iterate_items():
                # Aseguramos los datos base para las columnas relacionales
                src = item.get("source", "Lima")
                dst = item.get("destination", "Chiclayo")
                doj = "2026-09-07" # Fecha de nuestra prueba
                
                # Ejecutamos la inserción por cada bus encontrado
                connection.execute(query, {
                    "source": src,
                    "destination": dst,
                    "date_journey": doj,
                    "raw_json": json.dumps(item) # Empaquetamos todo el objeto a JSONB
                })
                contador += 1
                
            # Confirmamos todas las inserciones
            connection.commit()
            
            print(f"[3/3] ¡Completado! Se insertaron {contador} viajes en tu base de datos.")
            print("====================================================\n")

except Exception as e:
    print("\n[ERROR] Ocurrió un problema en el pipeline:")
    print(type(e).__name__, e)