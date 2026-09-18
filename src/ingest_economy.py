import os
import yfinance as yf
from datetime import date
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


# 1. Cargar conexion
load_dotenv()
db_url = os.getenv("DATABASE_URL")

# CORREGIDO: ya no esta hardcodeada. Antes decia:
#   fecha_viaje = "2026-09-07"  # Tu fecha piloto
# Esto causaba que el ON CONFLICT (target_date) DO UPDATE sobrescribiera
# SIEMPRE la misma fila del 7 de septiembre con los precios del dia en
# que se ejecutara el script, sin generar ningun error visible, y sin
# acumular historial real de tipo de cambio ni precio del petroleo.
fecha_viaje = date.today().strftime("%Y-%m-%d")


try:
    engine = create_engine(db_url)
    print("\n[1/3] Conectando a los mercados para extraer Petroleo y Dolar...")

    # 2. Extraer datos (Descargamos los ultimos 5 dias para saltar los fines de semana cerrados)
    # Ticker CL=F es Petroleo Crudo WTI, PEN=X es Dolar/Sol Peruano
    oil_data = yf.Ticker("CL=F").history(period="5d")
    usd_pen_data = yf.Ticker("PEN=X").history(period="5d")

    # Tomamos el ultimo precio de cierre disponible
    latest_oil_price = float(oil_data['Close'].iloc[-1])
    latest_usd_pen = float(usd_pen_data['Close'].iloc[-1])

    # 3. Calcular la variable proxy de combustible local
    fuel_proxy = latest_oil_price * latest_usd_pen

    print(f"[2/3] Datos obtenidos exitosamente para {fecha_viaje}:")
    print(f"      - Barril Petroleo WTI : ${latest_oil_price:.2f}")
    print(f"      - Tipo de Cambio      : S/{latest_usd_pen:.3f}")
    print(f"      -> Proxy Combustible  : S/{fuel_proxy:.2f}")

    # 4. Guardar en Supabase
    with engine.connect() as connection:
        query = text("""
            INSERT INTO staging.fact_economy (target_date, usd_pen, wti_price, fuel_local_proxy)
            VALUES (:date, :usd, :wti, :proxy)
            ON CONFLICT (target_date) DO UPDATE
            SET usd_pen = EXCLUDED.usd_pen, wti_price = EXCLUDED.wti_price, fuel_local_proxy = EXCLUDED.fuel_local_proxy;
        """)

        connection.execute(query, {
            "date": fecha_viaje,
            "usd": latest_usd_pen,
            "wti": latest_oil_price,
            "proxy": fuel_proxy
        })
        connection.commit()

    print("\n[3/3] Exito! Variables economicas inyectadas en la base de datos.")
    print("====================================================\n")

except Exception as e:
    print("\n[ERROR] Ocurrio un problema en la extraccion economica:")
    print(e)