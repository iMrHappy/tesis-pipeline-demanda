import os
import json
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Cargar las credenciales de tu archivo .env
load_dotenv()
db_url = os.getenv("DATABASE_URL")

# 2. El JSON real que extrajiste manualmente de Apify
viaje_prueba = {
    "id": 335411,
    "travelsName": "Turismo Cautivo",
    "busType": "MASTER",
    "serviceName": "MASTER",
    "departureTime": "2026-09-07 17:00:00",
    "arrivalTime": "2026-09-08 06:00:00",
    "journeyDurationMin": 780,
    "dateOfJourney": None,
    "minFare": 70,
    "maxFare": 100,
    "availableSeats": 40,
    "totalSeats": 63,
    "rating": 4.5,
    "numberOfReviews": "221",
    "boardingPoint": "Gran Terminal Terrestre Plaza Norte",
    "droppingPoint": "Terminal Turismo Cautivo",
    "source": "Lima",
    "destination": "Chiclayo"
}

try:
    # 3. Crear el motor de conexión
    engine = create_engine(db_url)
    
    with engine.connect() as connection:
        # 4. Preparar la consulta SQL de inserción (INSERT)
        query = text("""
            INSERT INTO raw.redbus_services_raw 
            (source_city, destination_city, date_of_journey, raw_data)
            VALUES (:source, :destination, :date_journey, :raw_json)
        """)
        
        # 5. Ejecutar la consulta pasando los valores del diccionario
        connection.execute(query, {
            "source": viaje_prueba["source"],
            "destination": viaje_prueba["destination"],
            "date_journey": "2026-09-07", # Usamos la fecha de salida extraída
            "raw_json": json.dumps(viaje_prueba) # Convertimos el diccionario a texto JSON compatible con PostgreSQL
        })
        
        # 6. Confirmar los cambios en la base de datos (Commit)
        connection.commit()
        
        print("\n====================================================")
        print("¡Éxito! El JSON se insertó correctamente en Supabase.")
        print("====================================================\n")
        
except Exception as e:
    print("\n[ERROR] Ocurrió un problema al insertar:")
    print(e)