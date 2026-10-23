"""
features.py
Constantes y transformaciones de features compartidas por train_xgboost.py y
predict_and_recommend.py. Una sola fuente de verdad: lo que se aplica al entrenar
es exactamente lo que se aplica al predecir.

Criterio de inclusion: toda variable debe existir 72 h antes de la salida.

Variables retiradas (22/10/2026):
  - indice_busqueda, retraso_trafico_min, dolar_compra, precio_petroleo: se miden el dia de la consulta
    y no existen 3 dias antes (ablacion: sin ellas el MAE de XGBoost sube ~0.2 asientos, dentro del ruido).
  - temperatura_maxima, precipitacion: las vistas las unen por la fecha del viaje, es decir, con el clima
    observado ese dia, que a 72 h no se conoce. Volveran al modelo cuando exista el pronostico emitido
    3 dias antes (con su fecha de emision): entonces anadir ambas a NUM.

Ubicacion: src/features.py  (no se ejecuta solo; solo se importa)
"""

import numpy as np
import pandas as pd

TARGET = "ocupacion_final"

# Variables disponibles 72 h antes de la salida (foto D+3 y calendario)
NUM = [
    "asientos_totales", "asientos_disponibles_d3", "ocupacion_d3", "tarifa_d3",
    "horas_antes_snapshot_feature", "proximidad_feriado", "dias_para_quincena",
]
BOOL = ["es_feriado", "es_fin_de_semana"]
CAT = ["operador", "tipo_bus"]
# Las vistas usan COALESCE(...,0): en estas columnas un 0 significa "dato faltante"
CERO_ES_FALTANTE = []


def transformar(df):
    """Limpieza y features derivadas. Se usa igual en entrenamiento y en prediccion."""
    df = df.copy()
    df["departure_time"] = pd.to_datetime(df["departure_time"])
    df["fecha_viaje"] = pd.to_datetime(df["fecha_viaje"]).dt.date
    cols_num = NUM + ([TARGET] if TARGET in df.columns else [])
    for c in cols_num:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in BOOL:
        df[c] = df[c].fillna(False).astype(int)

    for c in CERO_ES_FALTANTE:
        df.loc[df[c] == 0, c] = np.nan
    # Si el clima vuelve al modelo, una temperatura faltante invalida tambien la precipitacion
    if "temperatura_maxima" in NUM and "precipitacion" in NUM:
        df.loc[df["temperatura_maxima"].isna(), "precipitacion"] = np.nan

    df["hora_salida"] = df["departure_time"].dt.hour + df["departure_time"].dt.minute / 60
    df["dia_semana"] = pd.to_datetime(df["fecha_viaje"]).dt.dayofweek
    df["ocupacion_d3_pct"] = df["ocupacion_d3"] / df["asientos_totales"]

    df = df.dropna(subset=["ocupacion_d3", "asientos_totales"])
    return df.sort_values(["fecha_viaje", "departure_time"]).reset_index(drop=True)


def construir_X(df):
    base = df[NUM + BOOL + ["hora_salida", "dia_semana", "ocupacion_d3_pct"]].astype(float)
    dummies = pd.get_dummies(df[CAT], dtype=float)
    return pd.concat([base, dummies], axis=1)