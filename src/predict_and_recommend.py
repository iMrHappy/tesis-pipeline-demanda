import argparse
import json
import os
import math
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

from historial_emitido import cargar_emitidas, guardar_emitidas

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
    d = transformar(df.copy())
    if d.empty:
        return d
    X = construir_X(d)
    for c in bundle["features"]:
        if c not in X.columns:
            es_dummy = c.startswith("operador_") or c.startswith("tipo_bus_")
            X[c] = 0.0 if es_dummy else np.nan
    X = X[bundle["features"]]
    pred = bundle["model"].predict(X)
    d["ocupacion_predicha"] = np.clip(pred, d["ocupacion_d3"].values, d["asientos_totales"].values)
    d["ocupacion_predicha_pct"] = d["ocupacion_predicha"] / d["asientos_totales"] * 100
    return d


def decisiones_por_grupo(d, fecha, feriados, fis):
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
    mayor = max(g["delta_buses"] for g in decisorios)
    menor = min(g["delta_buses"] for g in decisorios)
    if mayor >= 2:
        return "Aumentar (urgente)", conteo
    if mayor >= 1:
        return "Aumentar", conteo
    if menor <= -1:
        if conteo["mantener"] == 0:
            return "Reducir", conteo
        return f"Mixto: reducir en {conteo['reducir']} de {len(decisorios)} grupos", conteo
    return "Mantener", conteo


def _registros(df):
    return json.loads(df.to_json(orient="records"))


def cargar_evaluacion():
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


def calcular_delta_regla_historial(pasajeros: float, asientos_totales: int, n_servicios: int, ocupacion_obj: float = 0.85) -> int:
    if n_servicios <= 0 or asientos_totales <= 0: return 0
    k_medio = asientos_totales / n_servicios
    buses_necesarios = math.ceil(pasajeros / (k_medio * ocupacion_obj))
    return int(np.clip(buses_necesarios - n_servicios, -2, 2))


def construir_historial(engine, paquete_modelo, ocupacion_obj=0.85, min_servicios=3):
    query = "SELECT * FROM staging.vw_training_d3 ORDER BY departure_time DESC;"
    try:
        df = pd.read_sql(text(query), engine)
    except Exception as e:
        print(f"[AVISO] No se pudo cargar vw_training_d3 para el historial: {e}")
        return []

    if df.empty:
        return []

    df["fecha_viaje_str"] = pd.to_datetime(df["fecha_viaje"]).dt.strftime("%Y-%m-%d")
    modelo = paquete_modelo["model"]
    cols_features = paquete_modelo["features"]

    d = transformar(df.copy())
    if d.empty: return []
    X = construir_X(d)
    for c in cols_features:
        if c not in X.columns:
            es_dummy = c.startswith("operador_") or c.startswith("tipo_bus_")
            X[c] = 0.0 if es_dummy else np.nan
    X = X[cols_features]
    pred_base = modelo.predict(X)

    df["ocupacion_predicha"] = np.clip(
        np.round(pred_base), df["ocupacion_d3"], df["asientos_totales"]
    ).astype(int)
    df["origen_pred"] = "en_muestra"

    ruta_cv = "models/predicciones_cv.csv"
    if os.path.exists(ruta_cv):
        try:
            df_cv = pd.read_csv(ruta_cv)
            col_xgb = next((c for c in ["pred_XGBoost", "ocupacion_predicha", "y_pred"] if c in df_cv.columns), None)
            llaves = ["departure_time", "operador", "tipo_bus"]
            if col_xgb and all(k in df_cv.columns for k in llaves):
                df["departure_time_key"] = pd.to_datetime(df["departure_time"]).astype(str)
                df_cv["departure_time_key"] = pd.to_datetime(df_cv["departure_time"]).astype(str)
                mapa_cv = df_cv.set_index(["departure_time_key", "operador", "tipo_bus"])[col_xgb].to_dict()

                def obtener_pred(row):
                    k = (row["departure_time_key"], row["operador"], row["tipo_bus"])
                    if k in mapa_cv and pd.notna(mapa_cv[k]):
                        return int(np.clip(round(mapa_cv[k]), row["ocupacion_d3"], row["asientos_totales"]))
                    return row["ocupacion_predicha"]

                df["ocupacion_predicha"] = df.apply(obtener_pred, axis=1)
                claves_cv = {k for k, v in mapa_cv.items() if pd.notna(v)}
                en_cv = df.apply(lambda r: (r["departure_time_key"], r["operador"], r["tipo_bus"]) in claves_cv, axis=1)
                df.loc[en_cv, "origen_pred"] = "validacion_cruzada"
        except Exception as e:
            print(f"[AVISO] No se pudo cruzar predicciones_cv.csv: {e}")

    emitidas = cargar_emitidas()
    if emitidas:
        horas = pd.to_datetime(df["departure_time"]).dt.strftime("%H:%M")
        for i in df.index:
            k = (df.at[i, "fecha_viaje_str"], horas[i], df.at[i, "operador"], df.at[i, "tipo_bus"])
            if k in emitidas:
                df.at[i, "ocupacion_predicha"] = int(np.clip(round(emitidas[k]),
                    df.at[i, "ocupacion_d3"], df.at[i, "asientos_totales"]))
                df.at[i, "origen_pred"] = "emitida"

    anclas = anclas_objetivo(ocupacion_obj)
    fis = DispatchFuzzySystemV2(*anclas)

    historial_fechas = []
    for fecha_str, df_dia in df.groupby("fecha_viaje_str", sort=False):
        n_serv_dia = int(len(df_dia))
        asientos_dia = int(df_dia["asientos_totales"].sum())
        pasajeros_pred_dia = int(df_dia["ocupacion_predicha"].sum())
        pasajeros_real_dia = int(df_dia["ocupacion_final"].sum())
        ocup_pred_pct_dia = round((pasajeros_pred_dia / asientos_dia) * 100, 1) if asientos_dia else 0.0
        ocup_real_pct_dia = round((pasajeros_real_dia / asientos_dia) * 100, 1) if asientos_dia else 0.0
        mae_dia = round(float(np.abs(df_dia["ocupacion_predicha"] - df_dia["ocupacion_final"]).mean()), 2)

        prox_max = float(df_dia["proximidad_feriado"].max()) if "proximidad_feriado" in df_dia.columns else 0.0
        es_feriado = bool(df_dia["es_feriado"].any()) if "es_feriado" in df_dia.columns else False
        dias_a_fer = 0 if es_feriado else (round(-4 * (1.0 - prox_max), 1) if prox_max > 0 else -5)

        grupos_lista = []
        aciertos_decisorios = 0
        total_decisorios = 0

        for (operador, tipo_bus), df_grp in df_dia.groupby(["operador", "tipo_bus"]):
            n_grp = int(len(df_grp))
            asientos_grp = int(df_grp["asientos_totales"].sum())
            pred_grp = int(df_grp["ocupacion_predicha"].sum())
            real_grp = int(df_grp["ocupacion_final"].sum())
            ocup_pred_grp_pct = round((pred_grp / asientos_grp) * 100, 1) if asientos_grp else 0.0
            ocup_real_grp_pct = round((real_grp / asientos_grp) * 100, 1) if asientos_grp else 0.0

            res_fis = fis.recomendar(ocup_pred_grp_pct, dias_a_fer)
            delta_difuso = int(res_fis["delta_buses"])
            delta_r = calcular_delta_regla_historial(pred_grp, asientos_grp, n_grp, ocupacion_obj)
            delta_correcto = calcular_delta_regla_historial(real_grp, asientos_grp, n_grp, ocupacion_obj)
            decide = n_grp >= min_servicios

            error_dec = delta_difuso - delta_correcto
            if decide:
                total_decisorios += 1
                if error_dec == 0:
                    aciertos_decisorios += 1

            grupos_lista.append({
                "operador": str(operador),
                "tipo_bus": str(tipo_bus),
                "n_servicios": n_grp,
                "asientos_totales": asientos_grp,
                "pasajeros_previstos": pred_grp,
                "pasajeros_reales": real_grp,
                "ocupacion_predicha_pct": ocup_pred_grp_pct,
                "ocupacion_real_pct": ocup_real_grp_pct,
                "delta_buses": delta_difuso,
                "delta_regla": delta_r,
                "delta_correcto": delta_correcto,
                "error_decision": error_dec,
                "etiqueta": res_fis.get("etiqueta", ""),
                "decide": decide
            })

        grupos_lista.sort(key=lambda g: (not g["decide"], -g["n_servicios"], g["operador"]))

        servicios_lista = []
        for _, row in df_dia.sort_values("departure_time").iterrows():
            dt_hora = pd.to_datetime(row["departure_time"]).strftime("%H:%M")
            asientos_s = int(row["asientos_totales"])
            pred_s = int(row["ocupacion_predicha"])
            real_s = int(row["ocupacion_final"])
            servicios_lista.append({
                "hora_salida": dt_hora,
                "operador": str(row["operador"]),
                "tipo_bus": str(row["tipo_bus"]),
                "asientos_totales": asientos_s,
                "ocupacion_d3": int(row["ocupacion_d3"]),
                "ocupacion_predicha": pred_s,
                "ocupacion_predicha_pct": round((pred_s / asientos_s) * 100, 1) if asientos_s else 0.0,
                "ocupacion_real": real_s,
                "ocupacion_real_pct": round((real_s / asientos_s) * 100, 1) if asientos_s else 0.0,
                "error_abs": int(abs(pred_s - real_s))
            })

        historial_fechas.append({
            "fecha_viaje": fecha_str,
            "n_servicios": n_serv_dia,
            "asientos_totales": asientos_dia,
            "pasajeros_previstos": pasajeros_pred_dia,
            "pasajeros_reales": pasajeros_real_dia,
            "ocupacion_predicha_pct": ocup_pred_pct_dia,
            "ocupacion_real_pct": ocup_real_pct_dia,
            "mae_dia": mae_dia,
            "grupos_decisorios": total_decisorios,
            "aciertos_decisorios": aciertos_decisorios,
            "origen_pred": df_dia["origen_pred"].value_counts().to_dict(),
            "grupos": grupos_lista,
            "servicios": servicios_lista
        })

    return historial_fechas


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

    historial_data = []
    try:
        with _engine().connect() as conn:
            historial_data = construir_historial(conn, bundle, OCUPACION_OBJETIVO, MIN_SERVICIOS)
    except Exception as e:
        print(f"[AVISO] Error al construir el historial: {e}")

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
        "historial": historial_data,
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
        print(salida["error"])
    else:
        guardar(salida)
        guardar_emitidas(salida["resultados"], salida["modelo"], salida["entrenado_en"])
        for r in salida["resultados"]:
            c = r["resumen"]
            print(f"{r['fecha_viaje']} | {r['n_servicios']} servicios | ocupacion {r['ocupacion_predicha_pct']}% | "
                  f"{r['recomendacion']} | grupos que deciden: {c['grupos_decisorios']} "
                  f"(aumentar {c['aumentar']}, mantener {c['mantener']}, reducir {c['reducir']})")
            for g in [x for x in r["grupos"] if x["decide"]]:
                print(f"    {g['operador']} | {g['tipo_bus']}: {g['n_servicios']} servicios, "
                      f"{g['ocupacion_predicha_pct']}% -> {g['delta_buses']:+d} buses ({g['etiqueta']}) "
                      f"| regla fija {g['delta_regla']:+d}")
        print(f"\nGuardado en {SALIDA_JSON} y {SALIDA_WEB}")