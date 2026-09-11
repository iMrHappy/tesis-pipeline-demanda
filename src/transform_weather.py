import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
db_url = os.getenv("DATABASE_URL")

try:
    engine = create_engine(db_url)
    print("\nIniciando proceso ETL para datos climáticos...")
    
    with engine.connect() as connection:
        # Extraemos los datos navegando por el JSON. 
        # El ->>0 saca el primer elemento de la lista (índice 0)
        query = text("""
            INSERT INTO staging.fact_weather_daily (
                raw_id, city, weather_date, temp_max, temp_min, precipitation
            )
            SELECT 
                id,
                city,
                target_date,
                CAST(raw_data->'daily'->'temperature_2m_max'->>0 AS NUMERIC),
                CAST(raw_data->'daily'->'temperature_2m_min'->>0 AS NUMERIC),
                CAST(raw_data->'daily'->'precipitation_sum'->>0 AS NUMERIC)
            FROM raw.weather_raw
            WHERE id NOT IN (SELECT raw_id FROM staging.fact_weather_daily);
        """)
        
        result = connection.execute(query)
        connection.commit()
        
        print(f"¡Éxito! Se procesaron {result.rowcount} registros de clima hacia la capa Staging.")
        print("====================================================\n")
        
except Exception as e:
    print("\n[ERROR] Ocurrió un problema en la transformación del clima:")
    print(e)