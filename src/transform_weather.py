import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


load_dotenv()
db_url = os.getenv("DATABASE_URL")


try:
    engine = create_engine(db_url)
    print("\nIniciando proceso ETL para datos climaticos...")

    with engine.connect() as connection:
        # CORREGIDO (paso 1): NOT IN -> NOT EXISTS para evitar el bloqueo
        # silencioso por NULLs en la subconsulta (mismo bug que redBus).
        #
        # CORREGIDO (paso 2): se agrega ON CONFLICT (weather_date, city)
        # DO NOTHING. Esto es necesario porque raw.weather_raw todavia
        # contiene filas duplicadas antiguas (varios raw_id distintos con
        # la misma city + target_date), generadas por el bug de fecha
        # hardcodeada que tenia ingest_weather.py antes de corregirlo.
        # Sin este ON CONFLICT, un solo residuo duplicado hace fallar
        # TODO el INSERT por la constraint UNIQUE(weather_date, city),
        # aunque el resto de filas nuevas sean validas.
        query = text("""
            INSERT INTO staging.fact_weather_daily (
                raw_id, city, weather_date, temp_max, temp_min, precipitation
            )
            SELECT
                r.id,
                r.city,
                r.target_date,
                CAST(r.raw_data->'daily'->'temperature_2m_max'->>0 AS NUMERIC),
                CAST(r.raw_data->'daily'->'temperature_2m_min'->>0 AS NUMERIC),
                CAST(r.raw_data->'daily'->'precipitation_sum'->>0 AS NUMERIC)
            FROM raw.weather_raw r
            WHERE NOT EXISTS (
                SELECT 1
                FROM staging.fact_weather_daily s
                WHERE s.raw_id = r.id
            )
            ON CONFLICT (weather_date, city) DO NOTHING;
        """)

        result = connection.execute(query)
        connection.commit()

        print(f"Exito! Se procesaron {result.rowcount} registros de clima hacia la capa Staging.")
        print("(Los residuos duplicados de fechas antiguas se omiten automaticamente.)")
        print("====================================================\n")

except Exception as e:
    print("\n[ERROR] Ocurrio un problema en la transformacion del clima:")
    print(e)
    raise