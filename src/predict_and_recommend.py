"""
predict_and_recommend.py
Integracion end-to-end para el software:

    1. Carga models/demand_model.joblib (paquete generado por train_xgboost.py).
    2. Lee staging.vw_prediction_d3: servicios futuros con su snapshot de ~72 h antes.
    3. Predice la ocupacion final de cada servicio (mismas features del entrenamiento).
    4. Agrega por fecha de viaje y pasa la ocupacion predicha (%) al Sistema de
       Inferencia Difusa (DispatchFuzzySystem) para obtener las unidades adicionales recomendadas.
    5. Guarda un JSON para el dashboard web (docs/data/recomendaciones.json) y una copia
       en models/ultimas_recomendaciones.json.

Ubicacion: src/predict_and_recommend.py   (requiere src/features.py y src/dispatch_fis.py)
Ejecucion (desde la raiz del repo):
    python src/predict_and_recommend.py
    python src/predict_and_recommend.py --fecha 2026-10-13

Requiere en .env: DATABASE_URL  (opcional: MODEL_PATH)
"""

import argparse
import json
import os
from datetime import date

import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from dispatch_fis import DispatchFuzzySystem
from features import construir_X, transformar

load_dotenv()

MODEL_PATH = os.getenv("MODEL_PATH", "models/demand_model.joblib")
VISTA_PRED = "staging.vw_prediction_d3"
SALIDA_JSON = "models/ultimas_recomendaciones.json"
SALIDA_WEB = "docs/data/recomendaciones.json"

# Supuestos de entrada del FIS (coinciden con los universos definidos en dispatch_fis.py)
DIAS_FERIADO_LEJOS = -5      # 0 = dia del feriado; -5 = 5 o mas dias antes
CLIMA_NEUTRO = 50.0          # sin dato de clima futuro


def cargar_modelo(path=MODEL_PATH):
    bundle = joblib.load(path)
    if not isinstance(bundle, dict) or "model" not in bundle:
        raise ValueError("demand_model.joblib no tiene el formato esperado; reejecuta train_xgboost.py")
    return bundle


def _engine():
    return create_engine(os.getenv("DATABASE_URL"))


def cargar_servicios(fecha=None):
    sql, params = f"SELECT * FROM {VISTA_PRED}", {}
    if fecha:
        sql += " WHERE fecha_viaje = :f"
        params["f"] = fecha
    with _engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


def cargar_feriados():
    with _engine().connect() as conn:
        df = pd.read_sql(text("SELECT date_id FROM staging.dim_calendar WHERE is_holiday ORDER BY date_id"), conn)
    return [pd.to_datetime(d).date() for d in df["date_id"]]


def dias_a_feriado(fecha, feriados):
    """0 = es feriado; negativo = dias que faltan para el proximo feriado (min -5)."""
    proximos = [h for h in feriados if h >= fecha]
    if not proximos:
        return DIAS_FERIADO_LEJOS
    return max(DIAS_FERIADO_LEJOS, -(min(proximos) - fecha).days)


def indice_clima(temp_max, precipitacion):
    """0-100 (mayor = mas favorable). Sin dato futuro de clima devuelve un valor neutro."""
    if pd.isna(temp_max):
        return CLIMA_NEUTRO
    precip = 0.0 if pd.isna(precipitacion) else float(precipitacion)
    return float(max(20.0, 100.0 - 10.0 * precip))


def predecir_servicios(df, bundle):
    d = transformar(df)
    if d.empty:
        return d
    X = construir_X(d)
    for c in bundle["features"]:
        if c not in X.columns:
            es_dummy = c.startswith("operador_") or c.startswith("tipo_bus_")
            X[c] = 0.0 if es_dummy else np.nan
    X = X[bundle["features"]]
    pred = bundle["model"].predict(X)
    # La ocupacion final no baja de la observada a D+3 ni supera la capacidad
    d["ocupacion_predicha"] = np.clip(pred, d["ocupacion_d3"].values, d["asientos_totales"].values)
    d["ocupacion_predicha_pct"] = d["ocupacion_predicha"] / d["asientos_totales"] * 100
    return d


def generar_recomendaciones(fecha=None, df=None, feriados=None, bundle=None):
    bundle = bundle or cargar_modelo()
    df = cargar_servicios(fecha) if df is None else df
    if df.empty:
        return {"error": "Sin servicios con snapshot D+3 para predecir. La vista solo muestra viajes "
                         "que salen en ~3 dias (60-84 h): espera al siguiente cron o revisa la ingesta."}
    feriados = cargar_feriados() if feriados is None else feriados

    d = predecir_servicios(df, bundle)
    fis = DispatchFuzzySystem()
    resultados = []
    for fv, g in d.groupby("fecha_viaje"):
        demanda_pct = float(g["ocupacion_predicha"].sum() / g["asientos_totales"].sum() * 100)
        dias = dias_a_feriado(fv, feriados)
        clima = indice_clima(g["temperatura_maxima"].iloc[0], g["precipitacion"].iloc[0])
        r = fis.recomendar(demanda_predicha=demanda_pct, dias_a_feriado=dias, indice_clima=clima)
        resultados.append({
            "fecha_viaje": str(fv),
            "n_servicios": int(len(g)),
            "ocupacion_predicha_pct": round(demanda_pct, 1),
            "dias_a_feriado": dias,
            "indice_clima": round(clima, 1),
            "unidades_recomendadas": r["unidades_recomendadas"],
            "recomendacion": r["etiqueta"],
            "reglas_activadas": {k: round(float(v), 4) for k, v in r["activaciones"].items()},
            "servicios": [
                {
                    "hora_salida": row["departure_time"].strftime("%H:%M"),
                    "operador": row["operador"],
                    "tipo_bus": row["tipo_bus"],
                    "asientos_totales": int(row["asientos_totales"]),
                    "ocupacion_d3": int(row["ocupacion_d3"]),
                    "ocupacion_predicha": round(float(row["ocupacion_predicha"]), 1),
                    "ocupacion_predicha_pct": round(float(row["ocupacion_predicha_pct"]), 1),
                }
                for _, row in g.iterrows()
            ],
        })
    return {
        "generado_en": date.today().isoformat(),
        "modelo": bundle["model_name"],
        "entrenado_en": bundle["entrenado_en"],
        "horizonte": bundle["horizonte"],
        "n_filas_entrenamiento": bundle.get("n_filas"),
        "entrenamiento_desde": bundle.get("fecha_min"),
        "entrenamiento_hasta": bundle.get("fecha_max"),
        "metricas_modelo": bundle.get("metricas_cv"),
        "resultados": resultados,
    }


def guardar(salida):
    for ruta in (SALIDA_JSON, SALIDA_WEB):
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fecha", help="Fecha de viaje YYYY-MM-DD (opcional)")
    args = parser.parse_args()

    salida = generar_recomendaciones(fecha=args.fecha)
    if "error" in salida:
        # No se sobreescribe el JSON anterior para que el dashboard conserve el ultimo dato valido
        print(salida["error"])
    else:
        guardar(salida)
        for r in salida["resultados"]:
            print(f"{r['fecha_viaje']} | {r['n_servicios']} servicios | ocupacion predicha "
                  f"{r['ocupacion_predicha_pct']}% | +{r['unidades_recomendadas']} unidades adicionales | {r['recomendacion']}")
        print(f"\nGuardado en {SALIDA_JSON} y {SALIDA_WEB}")