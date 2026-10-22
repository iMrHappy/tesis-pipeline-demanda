"""
guardia_diaria.py
Dice al workflow si la captura de redBus de HOY (fecha de Lima) ya esta completa.
Escribe ya_corrio=true|false en $GITHUB_OUTPUT. El cron de respaldo usa esto para no duplicar el trabajo.

Ubicacion: src/guardia_diaria.py
Ejecucion: python src/guardia_diaria.py
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# Fechas de viaje que debe consultar test_apify.py cada dia (hoy + 3 dias = 4 fechas)
DIAS_ESPERADOS = int(os.getenv("DIAS_ESPERADOS", "4"))

hoy = datetime.now(ZoneInfo("America/Lima")).date()
engine = create_engine(os.getenv("DATABASE_URL"))

with engine.connect() as conn:
    capturadas = conn.execute(
        text(
            "SELECT COUNT(DISTINCT date_of_journey) FROM raw.redbus_services_raw "
            "WHERE (extraction_timestamp AT TIME ZONE 'America/Lima')::date = :hoy"
        ),
        {"hoy": hoy},
    ).scalar()

completo = (capturadas or 0) >= DIAS_ESPERADOS
print(f"Hoy (Lima) {hoy}: {capturadas} de {DIAS_ESPERADOS} fechas capturadas -> "
      f"{'COMPLETO, no hace falta correr' if completo else 'INCOMPLETO, se ejecuta la ingesta'}")

salida = os.getenv("GITHUB_OUTPUT")
if salida:
    with open(salida, "a", encoding="utf-8") as f:
        f.write(f"ya_corrio={'true' if completo else 'false'}\n")
