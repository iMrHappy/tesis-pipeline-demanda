"""
test_apify.py
Ingesta de redBus -> raw.redbus_services_raw.

Consulta cada dia las fechas de viaje definidas en OFFSETS (0 = hoy, 3 = dentro de 3 dias).
  - Es idempotente: si una fecha ya se capturo hoy (fecha de Lima), la salta.
  - Cada fecha se guarda en una sola transaccion: o entran todas sus filas o ninguna.
  - Reintenta cada fecha y termina con codigo 1 si alguna queda sin capturar.
  - Avisa si el resultado llega al tope de MAX_ITEMS (posible truncamiento).
  - Defensa D-10: el actor trabaja en UTC. Si la fecha pedida ya paso en UTC (desde las 19:00 de Lima
    para la fecha de hoy), NO llama a Apify. Ademas, si los servicios recibidos no salen en la fecha
    pedida, NO los guarda (el actor los sustituye por "hoy + 7").
  - OFFSETS se puede sobreescribir sin tocar el codigo con la variable de entorno OFFSETS
    (ej. OFFSETS=2 captura solo hoy+2; OFFSETS=0,3 es lo habitual). Vacia = valor por defecto.

Costo (Starter, 13/11/2026): ~US$ 0.003 por servicio devuelto (60 servicios = US$ 0.18).
    costo diario = len(OFFSETS) * servicios_por_fecha * 0.003

Ubicacion: src/test_apify.py
Requiere en .env o secrets: APIFY_API_TOKEN, DATABASE_URL
Opcional: MAX_ITEMS y OFFSETS (variables de entorno).
"""

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apify_client import ApifyClient
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

ACTOR = "rl1987/redbus-api-scraper"
OFFSETS = [0, 3]     # D+0 (objetivo) y D+3 (pronostico). Anadir 1 solo si el presupuesto lo permite
MAX_ITEMS = int(os.getenv("MAX_ITEMS") or "60")   # ajustar tras medir cuantos servicios hay por fecha
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


class FechaSustituida(Exception):
    """Los servicios recibidos no salen en la fecha pedida (redBus/actor la sustituyo)."""


def offsets_a_usar():
    """OFFSETS por defecto, o los de la variable de entorno OFFSETS (ej. '2' o '0,3')."""
    crudo = (os.getenv("OFFSETS") or "").strip()
    if not crudo:
        return list(OFFSETS)
    return [int(x) for x in crudo.split(",") if x.strip() != ""]


def fecha_pasada_en_utc(fecha, ahora_utc=None):
    """True si la fecha de viaje (AAAA-MM-DD) ya paso segun el reloj UTC, que es el que usa el actor."""
    hoy_utc = (ahora_utc or datetime.now(timezone.utc)).date()
    return date.fromisoformat(fecha) < hoy_utc


def fecha_de_salida(item):
    """Fecha (date) de salida de un servicio, o None si no se puede leer."""
    crudo = item.get("departureTime") if isinstance(item, dict) else None
    if not crudo:
        return None
    try:
        return datetime.fromisoformat(str(crudo).replace("Z", "")).date()
    except ValueError:
        return None


def verificar_fecha_servicios(items, fecha):
    """Lanza FechaSustituida si ningun servicio sale en la fecha pedida. Si las fechas no se pueden leer, no bloquea."""
    pedida = date.fromisoformat(fecha)
    fechas = [d for d in (fecha_de_salida(i) for i in items) if d is not None]
    if fechas and pedida not in fechas:
        raise FechaSustituida(
            f"los servicios salen entre {min(fechas)} y {max(fechas)}, no el {fecha}"
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
    offsets = offsets_a_usar()
    fechas = [(hoy + timedelta(days=o)).isoformat() for o in offsets]
    print(f"Hoy (Lima): {hoy} | fechas a consultar: {fechas} | maxItems={MAX_ITEMS}")

    fallidas = []
    for fecha in fechas:
        with engine.connect() as conn:
            ya = conn.execute(SQL_YA_CAPTURADA, {"f": fecha, "hoy": hoy}).scalar()
        if ya:
            print(f"[OMITIDA] {fecha}: ya capturada hoy ({ya} filas)")
            continue

        if fecha_pasada_en_utc(fecha):
            print(f"[NO CAPTURADA] {fecha}: la fecha ya paso en UTC (el actor la sustituiria por hoy+7). "
                  f"No se llama a Apify.")
            fallidas.append(fecha)
            continue

        for intento in range(1, INTENTOS_POR_FECHA + 1):
            try:
                items = traer_servicios(client, fecha)
                verificar_fecha_servicios(items, fecha)
                with engine.begin() as conn:
                    for item in items:
                        conn.execute(SQL_INSERTAR, {"f": fecha, "raw_data": json.dumps(item)})
                aviso = "  [AVISO] llego al tope: subir MAX_ITEMS" if len(items) >= MAX_ITEMS else ""
                print(f"[OK] {fecha}: {len(items)} servicios guardados{aviso}")
                break
            except FechaSustituida as e:
                print(f"[NO CAPTURADA] {fecha}: {e}. No se guarda ni se reintenta.")
                fallidas.append(fecha)
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