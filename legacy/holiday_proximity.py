"""
holiday_proximity.py
Calcula la variable "holiday_proximity" para dim_calendar usando una
funcion de pertenencia difusa CONTINUA, en lugar de la tabla fija de
valores (0.8, 0.4) usada en la version anterior del proyecto.

Esta variable se usa como FEATURE de entrada para el modelo XGBoost
(NO es el sistema de recomendacion de despacho; ese esta en dispatch_fis.py).
"""

import numpy as np
from datetime import date, timedelta
from src.fuzzy.membership import trimf


# Funcion de pertenencia triangular: el pico (1.0) esta en el dia del feriado (0),
# decae linealmente hasta 5 dias antes o despues.
_UNIVERSO_DIAS = np.arange(-5, 6, 1)
_MF_PROXIMIDAD = trimf(_UNIVERSO_DIAS, [-5, 0, 5])


def calcular_holiday_proximity(fecha: date, feriados: list[date]) -> float:
    """
    Calcula el grado de pertenencia (0 a 1) de una fecha respecto a su
    feriado mas cercano, usando una funcion de pertenencia triangular
    continua.

    Args:
        fecha: fecha a evaluar.
        feriados: lista de fechas de feriados oficiales (calendario peruano).

    Returns:
        float entre 0 y 1. 1.0 = es feriado. Decrece gradualmente
        conforme la fecha se aleja del feriado mas cercano.
    """
    if not feriados:
        return 0.0

    diferencias_dias = [(fecha - f).days for f in feriados]
    dia_mas_cercano = min(diferencias_dias, key=abs)

    dia_mas_cercano = max(-5, min(5, dia_mas_cercano))
    grado = float(np.interp(dia_mas_cercano, _UNIVERSO_DIAS, _MF_PROXIMIDAD))
    return round(grado, 4)


if __name__ == "__main__":
    feriados_2026 = [date(2026, 10, 8), date(2026, 12, 25)]

    fechas_prueba = [
        date(2026, 10, 8),   # el feriado mismo
        date(2026, 10, 7),   # un dia antes
        date(2026, 10, 5),   # tres dias antes
        date(2026, 9, 30),   # lejos del feriado
    ]

    for f in fechas_prueba:
        proximidad = calcular_holiday_proximity(f, feriados_2026)
        print(f"{f} -> holiday_proximity = {proximidad}")
