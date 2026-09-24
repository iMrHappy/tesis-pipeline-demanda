import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Cargar variables de entorno
load_dotenv()
db_url = os.getenv("DATABASE_URL")

try:
    engine = create_engine(db_url)
    print("\nIniciando proceso ETL (Transformación y Carga)...")
    
    with engine.connect() as connection:
        # 2. Consulta SQL que extrae del JSON, calcula y carga en staging
        # Usamos WHERE para que solo procese los registros nuevos que aún no están en staging
        query = text("""
                        INSERT INTO staging.fact_redbus_snapshots (
                raw_id, 
                extraction_timestamp, 
                operator_name, 
                bus_type, 
                source_city, 
                destination_city, 
                departure_time, 
                total_seats, 
                available_seats, 
                occupied_seats_proxy, 
                min_fare, 
                lead_time_hours
            )
            SELECT 
                id,
                extraction_timestamp,
                raw_data->>'travelsName',
                raw_data->>'busType',
                raw_data->>'source',
                raw_data->>'destination',
                CAST(raw_data->>'departureTime' AS TIMESTAMP),
                CAST(raw_data->>'totalSeats' AS INTEGER),
                CAST(raw_data->>'availableSeats' AS INTEGER),
                (CAST(raw_data->>'totalSeats' AS INTEGER) - CAST(raw_data->>'availableSeats' AS INTEGER)),
                CAST(raw_data->>'minFare' AS NUMERIC),
                EXTRACT(EPOCH FROM (CAST(raw_data->>'departureTime' AS TIMESTAMP) - (extraction_timestamp AT TIME ZONE 'America/Lima'))) / 3600.0
            FROM raw.redbus_services_raw r
            WHERE NOT EXISTS (
                SELECT 1 FROM staging.fact_redbus_snapshots s WHERE s.raw_id = r.id
);
        """)
        
        # 3. Ejecutar y confirmar los cambios
        result = connection.execute(query)
        connection.commit()
        
        print(f"¡Éxito! Se procesaron {result.rowcount} registros hacia la capa Staging.")
        print("====================================================\n")
        
except Exception as e:
    print("\n[ERROR] Ocurrió un problema en la transformación:")
    print(e)
    raise