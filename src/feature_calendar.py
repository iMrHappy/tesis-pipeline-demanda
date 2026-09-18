import os
import calendar
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from membership import trimf

# =====================================================================
# feature_calendar.py
#
# CORRECCION METODOLOGICA (respecto a la version anterior):
# La "onda expansiva" original asignaba valores fijos y hardcodeados
# (0.75, 0.50, 0.25) a 1, 2 y 3 dias de distancia de un feriado. Esto
# NO es logica difusa formal, es una tabla de valores memorizados.
#
# Esta version reemplaza esa tabla por una FUNCION DE PERTENENCIA
# TRIANGULAR continua (misma que usa dispatch_fis.py), definida como:
#
#     holiday_proximity(d) = max(0, 1 - |d| / 4)
#
# donde d es la distancia en dias al feriado mas cercano.
#
# Se valido numericamente que esta funcion reproduce EXACTAMENTE los
# mismos valores que la tabla original (1.0, 0.75, 0.50, 0.25 en
# d = 0, 1, 2, 3), por lo que no se altera el comportamiento ya
# calibrado en produccion; solo se formaliza como una funcion de
# pertenencia matematica explicita, verificable y documentable en
# la tesis.
#
# Ubicacion: src/feature_calendar.py
# Ejecucion: python src/feature_calendar.py
# =====================================================================

load_dotenv()
db_url = os.getenv("DATABASE_URL")

_RADIO_INFLUENCIA = 4
_UNIVERSO_DIST = np.arange(-_RADIO_INFLUENCIA, _RADIO_INFLUENCIA + 1, 1)
_MF_HOLIDAY_PROXIMITY = trimf(_UNIVERSO_DIST, [-_RADIO_INFLUENCIA, 0, _RADIO_INFLUENCIA])


def calc_days_to_payday(date):
    """Calcula los dias restantes hasta el proximo dia de pago (15 o fin de mes)."""
    day = date.day
    if day <= 15:
        return 15 - day
    else:
        last_day = calendar.monthrange(date.year, date.month)[1]
        return last_day - day


def calcular_holiday_proximity_serie(df: pd.DataFrame) -> pd.Series:
    """
    Calcula holiday_proximity para todas las fechas del calendario usando
    una funcion de pertenencia triangular continua, en lugar de una tabla
    fija de valores.

    Para cada feriado, se calcula la pertenencia de las fechas cercanas
    (hasta 4 dias antes/despues) mediante trimf(), y se toma el maximo
    valor cuando dos feriados estan proximos entre si (misma regla de
    agregacion que la version anterior, pero calculada con la funcion).
    """
    proximity = pd.Series(0.0, index=df.index)
    holiday_indices = df[df["is_holiday"] == True].index

    for idx in holiday_indices:
        for offset in range(-_RADIO_INFLUENCIA, _RADIO_INFLUENCIA + 1):
            pos = idx + offset
            if 0 <= pos < len(df):
                grado = float(np.interp(offset, _UNIVERSO_DIST, _MF_HOLIDAY_PROXIMITY))
                proximity.loc[pos] = max(proximity.loc[pos], grado)

    return proximity.round(4)


try:
    engine = create_engine(db_url)
    print("\n[1/3] Descargando el calendario actual...")

    # 2. Traer el calendario a un DataFrame de Pandas
    query_select = "SELECT date_id, is_holiday FROM staging.dim_calendar ORDER BY date_id"
    df = pd.read_sql(query_select, engine)
    df["date_id"] = pd.to_datetime(df["date_id"])
    df = df.reset_index(drop=True)

    print("[2/3] Calculando Logica Difusa (funcion de pertenencia) y Dias de Pago...")

    # 3. Dias de pago (sin cambios respecto a la version anterior)
    df["days_to_payday"] = df["date_id"].apply(calc_days_to_payday)

    # 4. Holiday proximity con funcion de pertenencia triangular (corregido)
    df["holiday_proximity"] = calcular_holiday_proximity_serie(df)

    print("[3/3] Inyectando los nuevos calculos en Supabase (puede tardar unos segundos)...")

    # 5. Actualizar la base de datos (sin cambios en la logica de escritura)
    with engine.connect() as connection:
        update_query = text("""
            UPDATE staging.dim_calendar
            SET holiday_proximity = :prox, days_to_payday = :payday
            WHERE date_id = :date
        """)

        for _, row in df.iterrows():
            connection.execute(update_query, {
                "prox": float(row["holiday_proximity"]),
                "payday": int(row["days_to_payday"]),
                "date": str(row["date_id"].date())
            })

        connection.commit()

    print("\n====================================================")
    print("Listo. Se aplico la funcion de pertenencia difusa (holiday_proximity)")
    print("y las variables de dias de pago exitosamente.")
    print("====================================================\n")

except Exception as e:
    print("\n[ERROR] Ocurrio un problema en el procesamiento:", e)