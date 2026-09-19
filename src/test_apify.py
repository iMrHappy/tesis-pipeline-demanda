import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from apify_client import ApifyClient
from sqlalchemy import create_engine, text

load_dotenv()
apify_token = os.getenv("APIFY_API_TOKEN")
db_url = os.getenv("DATABASE_URL")

DIAS_HACIA_ADELANTE = 6  # ventana rodante: hoy + 0 hasta +6 dias

try:
    engine = create_engine(db_url)
    client = ApifyClient(apify_token)

    fechas_a_consultar = [
        (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(0, DIAS_HACIA_ADELANTE + 1)
    ]

    total_insertados = 0

    with engine.connect() as connection:
        query = text("""
            INSERT INTO raw.redbus_services_raw (
                extraction_timestamp, source_city, destination_city, date_of_journey, raw_data
            ) VALUES (
                CURRENT_TIMESTAMP, 'Lima', 'Chiclayo', :fecha_viaje, :raw_data
            )
        """)

        for fecha_viaje in fechas_a_consultar:
            print(f"\nSolicitando datos en Apify para viajes el: {fecha_viaje}...")
            run_input = {
                "country": "peru",
                "dateOfJourney": fecha_viaje,
                "destination": "Chiclayo",
                "source": "Lima",
                "maxItems": 15,
                "proxyConfiguration": {"useApifyProxy": True}
            }
            run = client.actor("rl1987/redbus-api-scraper").call(run_input=run_input)
            estado = getattr(run, "status", None)
            id_dataset = getattr(run, "default_dataset_id", getattr(run, "defaultDatasetId", None))

            if estado != "SUCCEEDED":
                print(f"[ADVERTENCIA] Fallo para {fecha_viaje}. Estado: {estado}")
                continue

            dataset = list(client.dataset(id_dataset).iterate_items())
            print(f"{len(dataset)} buses encontrados para {fecha_viaje}.")

            for item in dataset:
                connection.execute(query, {
                    "fecha_viaje": fecha_viaje,
                    "raw_data": json.dumps(item)
                })
                total_insertados += 1

        connection.commit()

    print(f"\n¡Éxito! {total_insertados} registros crudos insertados en raw.redbus_services_raw (ventana de {DIAS_HACIA_ADELANTE + 1} días).\n")

except Exception as e:
    print("\n[ERROR] Ocurrió un problema:")
    print(type(e).__name__, e)