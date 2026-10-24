"""
transform_staging.py
raw.redbus_services_raw -> staging.fact_redbus_snapshots

Capacidad corregida con staging.dim_capacity (llave: empresa, tipo, total_api).
El valor original de redBus se conserva en total_seats_api.
Combinaciones sin fila en dim_capacity usan el total de la API y se avisan.
Requiere: DATABASE_URL
"""

import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

SQL_VERIFICAR = text("""
    SELECT
        (to_regclass('staging.dim_capacity') IS NOT NULL),
        EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'staging'
                  AND table_name = 'fact_redbus_snapshots'
                  AND column_name = 'total_seats_api')
""")

SQL_INSERTAR = text("""
    INSERT INTO staging.fact_redbus_snapshots (
        raw_id, extraction_timestamp, operator_name, bus_type,
        source_city, destination_city, departure_time,
        total_seats, total_seats_api, available_seats,
        occupied_seats_proxy, min_fare, lead_time_hours
    )
    SELECT
        r.id,
        r.extraction_timestamp,
        r.raw_data->>'travelsName',
        r.raw_data->>'busType',
        r.raw_data->>'source',
        r.raw_data->>'destination',
        CAST(r.raw_data->>'departureTime' AS TIMESTAMP),
        COALESCE(c.capacity_real, CAST(r.raw_data->>'totalSeats' AS INTEGER)),
        CAST(r.raw_data->>'totalSeats' AS INTEGER),
        CAST(r.raw_data->>'availableSeats' AS INTEGER),
        COALESCE(c.capacity_real, CAST(r.raw_data->>'totalSeats' AS INTEGER))
            - CAST(r.raw_data->>'availableSeats' AS INTEGER),
        CAST(r.raw_data->>'minFare' AS NUMERIC),
        EXTRACT(EPOCH FROM (
            CAST(r.raw_data->>'departureTime' AS TIMESTAMP)
            - (r.extraction_timestamp AT TIME ZONE 'America/Lima')
        )) / 3600.0
    FROM raw.redbus_services_raw r
    LEFT JOIN staging.dim_capacity c
           ON c.operator_name   = r.raw_data->>'travelsName'
          AND c.bus_type        = r.raw_data->>'busType'
          AND c.total_seats_api = CAST(r.raw_data->>'totalSeats' AS INTEGER)
    WHERE NOT EXISTS (
        SELECT 1 FROM staging.fact_redbus_snapshots s WHERE s.raw_id = r.id
    )
""")

SQL_SIN_CAPACIDAD = text("""
    SELECT s.operator_name, s.bus_type, s.total_seats_api,
           MAX(s.available_seats) AS max_disponibles, COUNT(*) AS filas
    FROM staging.fact_redbus_snapshots s
    LEFT JOIN staging.dim_capacity c
           ON c.operator_name = s.operator_name
          AND c.bus_type = s.bus_type
          AND c.total_seats_api = s.total_seats_api
    WHERE s.raw_id IS NOT NULL AND c.operator_name IS NULL
    GROUP BY 1, 2, 3
    ORDER BY filas DESC
""")

SQL_ANOMALIAS = text("""
    SELECT s.operator_name, s.bus_type, s.total_seats_api, c.capacity_real,
           MAX(s.available_seats) AS max_disponibles, COUNT(*) AS filas
    FROM staging.fact_redbus_snapshots s
    JOIN staging.dim_capacity c
      ON c.operator_name = s.operator_name
     AND c.bus_type = s.bus_type
     AND c.total_seats_api = s.total_seats_api
    WHERE s.raw_id IS NOT NULL AND s.available_seats > c.capacity_real
    GROUP BY 1, 2, 3, 4
    ORDER BY 1, 2, 3
""")


def verificar_esquema(conn):
    tiene_dim, tiene_col = conn.execute(SQL_VERIFICAR).one()
    faltan = []
    if not tiene_dim:
        faltan.append("tabla staging.dim_capacity")
    if not tiene_col:
        faltan.append("columna fact_redbus_snapshots.total_seats_api")
    if faltan:
        raise RuntimeError("Falta ejecutar el SQL de esquema en Supabase: " + ", ".join(faltan))


def main():
    engine = create_engine(os.getenv("DATABASE_URL"))
    print("\nIniciando proceso ETL (Transformacion y Carga)...")

    with engine.connect() as conn:
        verificar_esquema(conn)

        result = conn.execute(SQL_INSERTAR)
        conn.commit()
        print(f"Se procesaron {result.rowcount} registros hacia la capa Staging.")

        sin_cap = conn.execute(SQL_SIN_CAPACIDAD).fetchall()
        if sin_cap:
            print("\n[AVISO] Sin capacidad verificada (se usa el total de la API):")
            for op, tipo, total_api, max_disp, filas in sin_cap:
                print(f"  - {op} | {tipo} | total_api={total_api} | max_disp={max_disp} | filas={filas}")

        anomalias = conn.execute(SQL_ANOMALIAS).fetchall()
        if anomalias:
            print("\n[AVISO] Disponibles > capacidad real (revisar dim_capacity):")
            for op, tipo, total_api, cap, max_disp, filas in anomalias:
                print(f"  - {op} | {tipo} | total_api={total_api} | cap={cap} | max_disp={max_disp} | filas={filas}")

    print("====================================================\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\n[ERROR] Ocurrio un problema en la transformacion:")
        print(e)
        sys.exit(1)