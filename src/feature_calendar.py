
import os
import sys
import calendar
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(PROJECT_ROOT))

from legacy.membership import trimf


# ============================================================
# feature_calendar.py
#
# CORRECCIÓN METODOLÓGICA:
# La proximidad a feriados utiliza una función de pertenencia
# triangular continua:
#
# holiday_proximity(d) = max(0, 1 - |d| / 4)
#
# Se conservan los valores:
# d = 0 -> 1.00
# d = 1 -> 0.75
# d = 2 -> 0.50
# d = 3 -> 0.25
# d = 4 -> 0.00
# ============================================================


# ============================================================
# CONFIGURACIÓN DE BASE DE DATOS
# ============================================================

load_dotenv(PROJECT_ROOT / ".env")

db_url = os.getenv("DATABASE_URL")

if not db_url:
    raise ValueError(
        "No se encontró DATABASE_URL. "
        "Verifica que exista el archivo .env "
        "o que la variable esté configurada en el entorno."
    )


# ============================================================
# CONFIGURACIÓN DE LÓGICA DIFUSA
# ============================================================

_RADIO_INFLUENCIA = 4

_UNIVERSO_DIST = np.arange(
    -_RADIO_INFLUENCIA,
    _RADIO_INFLUENCIA + 1,
    1
)

_MF_HOLIDAY_PROXIMITY = trimf(
    _UNIVERSO_DIST,
    [-_RADIO_INFLUENCIA, 0, _RADIO_INFLUENCIA]
)


# ============================================================
# CÁLCULO DE DÍAS HASTA EL PRÓXIMO DÍA DE PAGO
# ============================================================

def calc_days_to_payday(date):
    """
    Calcula los días restantes hasta el próximo día de pago
    (15 o último día del mes).
    """

    day = date.day

    if day <= 15:
        return 15 - day
    else:
        last_day = calendar.monthrange(
            date.year,
            date.month
        )[1]

        return last_day - day


# ============================================================
# CÁLCULO DE PROXIMIDAD A FERIADOS
# ============================================================

def calcular_holiday_proximity_serie(df: pd.DataFrame) -> pd.Series:
    """
    Calcula holiday_proximity para todas las fechas del calendario
    utilizando una función de pertenencia triangular continua.

    Para cada feriado, calcula la pertenencia de las fechas cercanas
    (hasta 4 días antes y después) mediante trimf().

    Cuando dos feriados están próximos entre sí, se conserva
    el máximo grado de pertenencia.
    """

    proximity = pd.Series(
        0.0,
        index=df.index,
        dtype=float
    )

    holiday_indices = df[
        df["is_holiday"] == True
    ].index

    for idx in holiday_indices:

        for offset in range(
            -_RADIO_INFLUENCIA,
            _RADIO_INFLUENCIA + 1
        ):

            pos = idx + offset

            if 0 <= pos < len(df):

                grado = float(
                    np.interp(
                        offset,
                        _UNIVERSO_DIST,
                        _MF_HOLIDAY_PROXIMITY
                    )
                )

                proximity.loc[pos] = max(
                    proximity.loc[pos],
                    grado
                )

    return proximity.round(4)


# ============================================================
# PROCESAMIENTO PRINCIPAL
# ============================================================

def main():

    engine = None

    try:

        engine = create_engine(db_url)

        print("\n[1/3] Descargando el calendario actual...")

        # Obtener calendario desde Supabase
        query_select = """
            SELECT date_id, is_holiday
            FROM staging.dim_calendar
            ORDER BY date_id
        """

        df = pd.read_sql(
            query_select,
            engine
        )

        df["date_id"] = pd.to_datetime(df["date_id"])

        df = df.reset_index(drop=True)

        print(
            "[2/3] Calculando lógica difusa "
            "y días de pago..."
        )

        # Calcular días restantes hasta el próximo pago
        df["days_to_payday"] = df["date_id"].apply(
            calc_days_to_payday
        )

        # Calcular proximidad a feriados
        df["holiday_proximity"] = (
            calcular_holiday_proximity_serie(df)
        )

        print(
            "[3/3] Inyectando los nuevos cálculos "
            "en Supabase (puede tardar unos segundos)..."
        )

        # Actualizar registros en Supabase
        with engine.connect() as connection:

            update_query = text("""
                UPDATE staging.dim_calendar
                SET
                    holiday_proximity = :prox,
                    days_to_payday = :payday
                WHERE date_id = :date
            """)

            for _, row in df.iterrows():

                connection.execute(
                    update_query,
                    {
                        "prox": float(
                            row["holiday_proximity"]
                        ),

                        "payday": int(
                            row["days_to_payday"]
                        ),

                        "date": str(
                            row["date_id"].date()
                        )
                    }
                )

            connection.commit()

        print("\n====================================================")
        print(
            "Listo. Se aplicó la función de pertenencia difusa "
            "(holiday_proximity)"
        )
        print(
            "y las variables de días de pago exitosamente."
        )
        print("====================================================\n")

    except Exception as e:

        print(
            "\n[ERROR] Ocurrió un problema en el procesamiento:",
            e
        )

        raise

    finally:

        if engine is not None:
            engine.dispose()


# ============================================================
# PUNTO DE ENTRADA
# ============================================================

if __name__ == "__main__":
    main()
