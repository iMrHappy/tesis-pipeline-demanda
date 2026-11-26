"""
guardia_diaria.py
Dice al workflow si la captura de redBus de HOY (fecha de Lima) ya esta completa.
Escribe ya_corrio=true|false en $GITHUB_OUTPUT. Los crons de respaldo usan esto para no duplicar el trabajo.

v3.3: las fechas que ya no se pueden capturar por el desfase UTC (ej. D+0 despues de las 19:00 Lima)
no cuentan como pendientes; si faltan, se deja un ::warning:: pero el run no se ejecuta en vano.

El numero de fechas esperadas sale de OFFSETS en test_apify.py (una sola fuente de verdad).

Ubicacion: src/guardia_diaria.py
Ejecucion: python src/guardia_diaria.py
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from test_apify import OFFSETS, fecha_pasada_en_utc

load_dotenv()

hoy = datetime.now(ZoneInfo("America/Lima")).date()
esperadas = [(hoy + timedelta(days=o)).isoformat() for o in OFFSETS]
posibles = [f for f in esperadas if not fecha_pasada_en_utc(f)]
imposibles = [f for f in esperadas if f not in posibles]

engine = create_engine(os.getenv("DATABASE_URL"))
with engine.connect() as conn:
    filas = conn.execute(
        text(
            "SELECT DISTINCT date_of_journey FROM raw.redbus_services_raw "
            "WHERE (extraction_timestamp AT TIME ZONE 'America/Lima')::date = :hoy"
        ),
        {"hoy": hoy},
    ).fetchall()

capturadas = {str(r[0])[:10] for r in filas}
pendientes = [f for f in posibles if f not in capturadas]
completo = len(pendientes) == 0

for f in imposibles:
    if f not in capturadas:
        print(f"::warning::{f} ya no se puede capturar hoy (desfase UTC).")

print(f"Hoy (Lima) {hoy}: capturadas {sorted(capturadas)} | pendientes {pendientes} -> "
      f"{'COMPLETO, no hace falta correr' if completo else 'INCOMPLETO, se ejecuta la ingesta'}")

salida = os.getenv("GITHUB_OUTPUT")
if salida:
    with open(salida, "a", encoding="utf-8") as f:
        f.write(f"ya_corrio={'true' if completo else 'false'}\n")