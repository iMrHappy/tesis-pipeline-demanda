"""
test_apify.py
Ingesta de redBus -> raw.redbus_services_raw (ventana rodante: hoy y los proximos DIAS_HACIA_ADELANTE dias).

Mejoras respecto a la version anterior:
  - Usa la fecha de LIMA (el runner de GitHub trabaja en UTC y podria desfasar los dias).
  - Es idempotente: si una fecha ya se capturo hoy, la salta (permite reintentar sin duplicar filas ni gastar Apify).
  - Cada fecha se guarda en una sola transaccion: o entran todas sus filas o ninguna.
  - Reintenta cada fecha antes de rendirse y termina con codigo 1 si alguna fecha quedo sin capturar,
    para que el reintento del workflow tenga efecto.

Ubicacion: src/test_apify.py
Requiere en .env o secrets: APIFY_API_TOKEN, DATABASE_URL
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apify_client import ApifyClient
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

ACTOR = "rl1987/redbus-api-scraper"
DIAS_HACIA_ADELANTE = 3      # ajustar segun presupuesto de Apify
MAX_ITEMS = 15
INTENTOS_POR_FECHA = 2
ESPERA_SEGUNDOS = 30
ZONA = ZoneInfo("America/Lima")

SQL_YA_CAPTURADA = text(
    "SELECT COUNT(*) FROM raw.redbus_services_raw "
    "WHERE date_of_journey = :f AND (extraction_timestamp AT TIME ZONE 'America/Lima')::date = :hoy"
)
SQL_INSERTAR = text(
    "INSERT INTO raw.redbus_services_raw "
    "(extraction_timestamp, source_city, destination_city, date_of_journey, raw_data) "
    "VALUES (CURRENT_TIMESTAMP, 'Lima', 'Chiclayo', :f, CAST(:raw_data AS jsonb))"
)


def traer_servicios(client, fecha):
    run_input = {
        "country": "peru",
        "dateOfJourney": fecha,
        "destination": "Chiclayo",
        "source": "Lima",
        "maxItems": MAX_ITEMS,
        "proxyConfiguration": {"useApifyProxy": True},
    }
    run = client.actor(ACTOR).call(run_input=run_input)
    estado = getattr(run, "status", None)
    dataset_id = getattr(run, "default_dataset_id", getattr(run, "defaultDatasetId", None))
    if estado != "SUCCEEDED" or not dataset_id:
        raise RuntimeError(f"Apify devolvio estado {estado}")
    items = list(client.dataset(dataset_id).iterate_items())
    if not items:
        raise RuntimeError("Apify no devolvio servicios")
    return items


def main():
    engine = create_engine(os.getenv("DATABASE_URL"))
    client = ApifyClient(os.getenv("APIFY_API_TOKEN"))

    hoy = datetime.now(ZONA).date()
    fechas = [(hoy + timedelta(days=o)).isoformat() for o in range(0, DIAS_HACIA_ADELANTE + 1)]
    print(f"Hoy (Lima): {hoy} | fechas a consultar: {fechas}")

    fallidas = []
    for fecha in fechas:
        with engine.connect() as conn:
            ya = conn.execute(SQL_YA_CAPTURADA, {"f": fecha, "hoy": hoy}).scalar()
        if ya:
            print(f"[OMITIDA] {fecha}: ya capturada hoy ({ya} filas)")
            continue

        for intento in range(1, INTENTOS_POR_FECHA + 1):
            try:
                items = traer_servicios(client, fecha)
                with engine.begin() as conn:
                    for item in items:
                        conn.execute(SQL_INSERTAR, {"f": fecha, "raw_data": json.dumps(item)})
                print(f"[OK] {fecha}: {len(items)} servicios guardados")
                break
            except Exception as e:
                print(f"[ADVERTENCIA] {fecha}, intento {intento}/{INTENTOS_POR_FECHA}: {e}")
                if intento < INTENTOS_POR_FECHA:
                    time.sleep(ESPERA_SEGUNDOS)
        else:
            fallidas.append(fecha)

    if fallidas:
        print(f"[ERROR] No se pudo capturar: {fallidas}")
        sys.exit(1)
    print("Captura completa.")


if __name__ == "__main__":
    main()