"""
predict_and_recommend.py  (v3)
Integracion end-to-end para el software:

    1. Carga models/demand_model.joblib (paquete generado por train_xgboost.py).
    2. Lee staging.vw_prediction_d3: servicios futuros con su foto de ~72 h antes.
    3. Predice la ocupacion final de cada servicio (mismas features del entrenamiento).
    4. Agrupa por fecha de viaje y por GRUPO (empresa + tipo de servicio) y aplica el sistema difuso v2,
       que recomienda cuantos buses anadir o quitar (-2 a +2) sobre lo programado. Solo deciden los grupos
       con MIN_SERVICIOS o mas servicios; los demas se muestran como informativos.
    5. Anade la regla fija (la de comparacion) y los resultados de evaluacion si existen en models/.
    6. Guarda el JSON del tablero (docs/data/recomendaciones.json) y una copia en models/.

Ubicacion: src/predict_and_recommend.py
   Requiere: src/features.py, src/dispatch_fis_v2.py, src/evaluar_decision.py
Ejecucion (desde la raiz del repo):
    python src/predict_and_recommend.py
    python src/predict_and_recommend.py --fecha 2026-10-25

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

from dispatch_fis_v2 import DispatchFuzzySystemV2
from evaluar_decision import (MIN_SERVICIOS, OCUPACION_OBJETIVO, anclas_objetivo, comparar,
                              delta_regla, dias_a_feriado)
from features import construir_X, transformar

load_dotenv()

MODEL_PATH = os.getenv("MODEL_PATH", "models/demand_model.joblib")
VISTA_PRED = "staging.vw_prediction_d3"
SALIDA_JSON = "models/ultimas_recomendaciones.json"
SALIDA_WEB = "docs/data/recomendaciones.json"
RUTA_PAREADA = "models/prueba_pareada.csv"
RUTA_ERROR_DECISION = "models/error_decision.csv"
RUTA_DETALLE_DECISION = "models/decisiones_detalle.csv"
VERSION_ESQUEMA = 3


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


def decisiones_por_grupo(d, fecha, feriados, fis):
    """Una decision por grupo (empresa + tipo de servicio) para una fecha."""
    dias = dias_a_feriado(fecha, feriados)
    grupos = []
    for (operador, tipo), g in d.groupby(["operador", "tipo_bus"]):
        n = int(len(g))
        asientos = float(g["asientos_totales"].sum())
        pasajeros = float(g["ocupacion_predicha"].sum())
        ocupacion = pasajeros / asientos * 100
        r = fis.recomendar(ocupacion, dias)
        grupos.append({
            "operador": operador, "tipo_bus": tipo, "n_servicios": n,
            "asientos_totales": int(asientos), "pasajeros_previstos": round(pasajeros, 1),
            "ocupacion_predicha_pct": round(ocupacion, 1),
            "delta_buses": r["delta_buses"], "delta_continuo": r["delta_continuo"], "etiqueta": r["etiqueta"],
            "delta_regla": delta_regla(pasajeros, float(g["asientos_totales"].mean()), n),
            "soporte": r["soporte"], "activaciones": r["activaciones"],
            "decide": n >= MIN_SERVICIOS,
        })
    grupos.sort(key=lambda x: (not x["decide"], -x["delta_buses"], -x["n_servicios"], x["operador"]))
    return grupos, dias


def resumen_fecha(grupos):
    decisorios = [g for g in grupos if g["decide"]]
    conteo = {"aumentar": sum(g["delta_buses"] > 0 for g in decisorios),
              "mantener": sum(g["delta_buses"] == 0 for g in decisorios),
              "reducir": sum(g["delta_buses"] < 0 for g in decisorios),
              "grupos_decisorios": len(decisorios), "grupos": len(grupos)}
    if not decisorios:
        return f"Sin grupos con {MIN_SERVICIOS}+ servicios", conteo
    mayor, menor = max(g["delta_buses"] for g in decisorios), min(g["delta_buses"] for g in decisorios)
    if mayor >= 2:
        return "Aumentar (urgente)", conteo
    if mayor >= 1:
        return "Aumentar", conteo
    if menor <= -1:
        return "Reducir", conteo
    return "Mantener", conteo


def _registros(df):
    """DataFrame -> lista de dicts compatible con JSON (NaN se vuelve null)."""
    return json.loads(df.to_json(orient="records"))


def cargar_evaluacion():
    """Resultados de evaluar_pronostico.py y evaluar_decision.py, si existen (para la pestana Modelo)."""
    ev = {}
    if os.path.exists(RUTA_PAREADA):
        ev["prueba_pareada"] = _registros(pd.read_csv(RUTA_PAREADA))
    if os.path.exists(RUTA_ERROR_DECISION):
        t = pd.read_csv(RUTA_ERROR_DECISION)
        ev["error_decision"] = _registros(t[np.isclose(t["ocupacion_objetivo"], OCUPACION_OBJETIVO)])
    if os.path.exists(RUTA_DETALLE_DECISION):
        det = pd.read_csv(RUTA_DETALLE_DECISION)
        sub = det[det["n_servicios"] >= MIN_SERVICIOS]
        if len(sub):
            ev["comparaciones_decision"] = {
                "OE1: B (XGBoost + regla) frente a A (referencia + regla)": comparar(sub, "B", "A"),
                "OE2: C (XGBoost + difuso) frente a B (XGBoost + regla)": comparar(sub, "C", "B"),
                "Sensibilidad: C' (difuso con percentiles) frente a B": comparar(sub, "Cp", "B"),
            }
    return ev


def generar_recomendaciones(fecha=None, df=None, feriados=None, bundle=None, evaluacion=None):
    bundle = bundle or cargar_modelo()
    df = cargar_servicios(fecha) if df is None else df
    if df.empty:
        return {"error": "Sin servicios con foto D+3 para predecir. La vista solo muestra viajes "
                         "que salen en ~3 dias (60-84 h): espera al siguiente cron o revisa la ingesta."}
    feriados = cargar_feriados() if feriados is None else feriados

    d = predecir_servicios(df, bundle)
    anclas = anclas_objetivo(OCUPACION_OBJETIVO)
    fis = DispatchFuzzySystemV2(*anclas)

    resultados = []
    for fv, g in d.groupby("fecha_viaje"):
        grupos, dias = decisiones_por_grupo(g, fv, feriados, fis)
        etiqueta, conteo = resumen_fecha(grupos)
        resultados.append({
            "fecha_viaje": str(fv),
            "n_servicios": int(len(g)),
            "ocupacion_predicha_pct": round(float(g["ocupacion_predicha"].sum() / g["asientos_totales"].sum() * 100), 1),
            "dias_a_feriado": dias,
            "recomendacion": etiqueta,
            "resumen": conteo,
            "grupos": grupos,
            "servicios": [
                {
                    "hora_salida": row["departure_time"].strftime("%H:%M"),
                    "operador": row["operador"], "tipo_bus": row["tipo_bus"],
                    "asientos_totales": int(row["asientos_totales"]), "ocupacion_d3": int(row["ocupacion_d3"]),
                    "ocupacion_predicha": round(float(row["ocupacion_predicha"]), 1),
                    "ocupacion_predicha_pct": round(float(row["ocupacion_predicha_pct"]), 1),
                }
                for _, row in g.iterrows()
            ],
        })
    return {
        "version_esquema": VERSION_ESQUEMA,
        "generado_en": date.today().isoformat(),
        "modelo": bundle["model_name"],
        "entrenado_en": bundle["entrenado_en"],
        "horizonte": bundle["horizonte"],
        "n_filas_entrenamiento": bundle.get("n_filas"),
        "entrenamiento_desde": bundle.get("fecha_min"),
        "entrenamiento_hasta": bundle.get("fecha_max"),
        "metricas_modelo": bundle.get("metricas_cv"),
        "parametros": {"ocupacion_objetivo": OCUPACION_OBJETIVO, "min_servicios": MIN_SERVICIOS,
                       "anclas_difuso": [round(a, 1) for a in anclas]},
        "evaluacion": cargar_evaluacion() if evaluacion is None else evaluacion,
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
        # No se sobreescribe el JSON anterior para que el panel conserve el ultimo dato valido
        print(salida["error"])
    else:
        guardar(salida)
        for r in salida["resultados"]:
            c = r["resumen"]
            print(f"{r['fecha_viaje']} | {r['n_servicios']} servicios | ocupacion {r['ocupacion_predicha_pct']}% | "
                  f"{r['recomendacion']} | grupos que deciden: {c['grupos_decisorios']} "
                  f"(aumentar {c['aumentar']}, mantener {c['mantener']}, reducir {c['reducir']})")
            for g in [x for x in r["grupos"] if x["decide"]]:
                print(f"    {g['operador']} - {g['tipo_bus']}: {g['n_servicios']} servicios, "
                      f"{g['ocupacion_predicha_pct']}% -> {g['delta_buses']:+d} buses ({g['etiqueta']}) "
                      f"| regla fija {g['delta_regla']:+d}")
        print(f"\nGuardado en {SALIDA_JSON} y {SALIDA_WEB}")