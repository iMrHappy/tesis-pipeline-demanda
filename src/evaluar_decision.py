"""
evaluar_decision.py  (v2.1)  -  T9, evaluacion del error de decision (configuraciones A / B / C)

Unidad de decision: un GRUPO = (fecha, operador, tipo de bus). Se consideran todas las empresas y todos
los tipos de servicio; las metricas principales usan los grupos con al menos MIN_SERVICIOS servicios
(con 1 o 2 buses una decision de -2 a +2 no es informativa); tambien se reporta el total.

Regla fija (escrita ANTES de evaluar; no se ajusta despues):
    delta = clip( ceil( P / (K_medio * OCUPACION_OBJETIVO) ) - n , -2, 2 )
  P: pasajeros (previstos o, para la decision correcta, observados) del grupo; K_medio: asientos medios
  de sus buses; n: buses programados (servicios del grupo capturados ese dia).
  OCUPACION_OBJETIVO = 0.85 es el margen de planificacion: se busca llenar cada bus al 85 % para dejar
  holgura ante variaciones de la demanda.

Configuraciones (cambia una pieza a la vez):
    A = referencia ("Persistencia + incremento mediano") + regla fija
    B = XGBoost + regla fija              OE1 = B frente a A
    C = XGBoost + sistema difuso v2       OE2 = C frente a B
    C' = igual que C, pero con los conjuntos difusos definidos por percentiles historicos (sensibilidad)
Decision correcta (delta*): la misma regla con los pasajeros OBSERVADOS.
Error: delta decidido - delta*  (positivo = exceso de buses; negativo = defecto).

Alineacion del sistema difuso (declarada el 22/10/2026, antes de ver resultados reales): la "decision correcta"
usa un objetivo de 85 % de ocupacion, asi que el difuso principal (C) ancla sus conjuntos a ese mismo objetivo
(P25, P50 y P75 equivalentes = 0.60, 0.87 y 1.13 veces el objetivo). Si el difuso usara percentiles historicos
(su "media" ronda la ocupacion tipica, ~55 %), estaria midiendo una nocion distinta de "decision correcta" y
perderia por construccion. La variante con percentiles se reporta como C'.

Limitaciones: n esta acotado por el tope de servicios de la captura; el sistema difuso no recibe n;
la demanda censurada subestima el defecto; el periodo tiene pocos feriados (solo el 8/10).

Entrada: models/predicciones_cv.csv (train_xgboost.py). Salidas: models/error_decision.csv y
models/decisiones_detalle.csv. No usa Apify ni Supabase.

Ubicacion: src/evaluar_decision.py   (requiere src/dispatch_fis_v2.py)
Ejecucion (desde la raiz del repo): python src/evaluar_decision.py
"""

import math
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

from dispatch_fis_v2 import PERCENTILES_POR_DEFECTO, DispatchFuzzySystemV2

RUTA_ENTRADA = "models/predicciones_cv.csv"
RUTA_SALIDA = "models/error_decision.csv"
RUTA_DETALLE = "models/decisiones_detalle.csv"

OCUPACION_OBJETIVO = 0.85            # fijada el 22/10/2026, antes de ver resultados
SENSIBILIDAD = [0.80, 0.85, 0.90]    # solo informativa; la cifra principal usa 0.85
MIN_SERVICIOS = 3
HORIZONTE_DIAS = 3
MIN_SERVICIOS_PERCENTILES = 30
ANCLAS_OBJETIVO = (0.60, 0.87, 1.13)  # multiplos del objetivo -> anclas (P25, P50, P75) del difuso principal
MODELO_REFERENCIA = "Persistencia + incremento mediano"
MODELO_ML = "XGBoost"
# Feriados nacionales (gob.pe/feriados). Ampliar si el periodo evaluado incluye otros.
FERIADOS = [date(2026, 10, 8), date(2026, 11, 1), date(2026, 12, 8), date(2026, 12, 9), date(2026, 12, 25)]


def delta_regla(pasajeros, capacidad_media, n_buses, objetivo=OCUPACION_OBJETIVO):
    necesarios = math.ceil(round(pasajeros / (capacidad_media * objetivo), 9))
    return int(np.clip(necesarios - n_buses, -2, 2))


def dias_a_feriado(fecha, feriados=FERIADOS):
    """0 = es feriado; negativo = dias hasta el proximo feriado; -5 si no hay uno en los proximos 5 dias."""
    proximos = [f for f in feriados if f >= fecha]
    if not proximos:
        return -5
    return max(-5, -(min(proximos) - fecha).days)


def p_signos(mejora, empeora):
    n = mejora + empeora
    if n == 0:
        return 1.0
    k = min(mejora, empeora)
    return float(min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n))


def percentiles_historicos(servicios, fecha):
    """P25, P50, P75 de la ocupacion final (%) usando solo servicios de fechas anteriores a fecha - HORIZONTE."""
    corte = fecha - timedelta(days=HORIZONTE_DIAS)
    previos = servicios[servicios["fecha"] < corte]
    if len(previos) < MIN_SERVICIOS_PERCENTILES:
        return PERCENTILES_POR_DEFECTO
    q = np.percentile(previos["y"] / previos["asientos"] * 100, [25, 50, 75])
    if not (0 < q[0] < q[1] < q[2] < 100):
        return PERCENTILES_POR_DEFECTO
    return tuple(float(v) for v in q)


def anclas_objetivo(objetivo):
    """Anclas del difuso principal, derivadas del objetivo de ocupacion (en %), siempre dentro de (0, 100)."""
    a = [min(99.0, m * objetivo * 100) for m in ANCLAS_OBJETIVO]
    return tuple(a) if a[0] < a[1] < a[2] else PERCENTILES_POR_DEFECTO


def construir_grupos(pred):
    pred = pred.copy()
    pred["fecha"] = pd.to_datetime(pred["fecha"]).dt.date
    llaves = ["fecha", "operador", "tipo_bus"]

    def agrupar(modelo, col):
        d = pred[pred["modelo"] == modelo]
        return d.groupby(llaves).agg(**{col: ("pred", "sum")}).reset_index()

    base = (pred[pred["modelo"] == MODELO_ML].groupby(llaves)
            .agg(n=("y", "size"), K=("asientos", "mean"), asientos_total=("asientos", "sum"), P_obs=("y", "sum"))
            .reset_index())
    base = base.merge(agrupar(MODELO_ML, "P_xgb"), on=llaves).merge(agrupar(MODELO_REFERENCIA, "P_ref"), on=llaves)
    servicios = pred[pred["modelo"] == MODELO_ML][["fecha", "y", "asientos"]]
    return base, servicios


def decidir(base, servicios, objetivo=OCUPACION_OBJETIVO):
    filas = []
    fis_objetivo = DispatchFuzzySystemV2(*anclas_objetivo(objetivo))
    sistemas_pct = {}
    for _, g in base.iterrows():
        f = g["fecha"]
        if f not in sistemas_pct:
            sistemas_pct[f] = DispatchFuzzySystemV2(*percentiles_historicos(servicios, f))
        ocu = g["P_xgb"] / g["asientos_total"] * 100
        fis = fis_objetivo.recomendar(ocu, dias_a_feriado(f))
        fis_p = sistemas_pct[f].recomendar(ocu, dias_a_feriado(f))
        filas.append({
            "fecha": f, "operador": g["operador"], "tipo_bus": g["tipo_bus"], "n_servicios": int(g["n"]),
            "pasajeros_obs": round(g["P_obs"], 1), "pasajeros_ref": round(g["P_ref"], 1),
            "pasajeros_xgb": round(g["P_xgb"], 1), "ocupacion_prevista_%": round(ocu, 1),
            "delta_correcto": delta_regla(g["P_obs"], g["K"], g["n"], objetivo),
            "delta_A": delta_regla(g["P_ref"], g["K"], g["n"], objetivo),
            "delta_B": delta_regla(g["P_xgb"], g["K"], g["n"], objetivo),
            "delta_C": fis["delta_buses"], "delta_C_continuo": fis["delta_continuo"], "soporte_C": fis["soporte"],
            "delta_Cp": fis_p["delta_buses"],
        })
    return pd.DataFrame(filas)


def metricas(det, config):
    err = det[f"delta_{config}"] - det["delta_correcto"]
    return {
        "n_grupos": len(det),
        "correctas_%": round((err == 0).mean() * 100, 1),
        "exceso_%": round((err > 0).mean() * 100, 1),
        "defecto_%": round((err < 0).mean() * 100, 1),
        "error_medio_abs_buses": round(err.abs().mean(), 3),
    }


def comparar(det, nueva, base):
    e_n = (det[f"delta_{nueva}"] - det["delta_correcto"]).abs()
    e_b = (det[f"delta_{base}"] - det["delta_correcto"]).abs()
    mejora, empeora = int((e_n < e_b).sum()), int((e_n > e_b).sum())
    return {"grupos_mejora": mejora, "grupos_empeora": empeora, "grupos_igual": int((e_n == e_b).sum()),
            "p_signos": round(p_signos(mejora, empeora), 3)}


def main(ruta=RUTA_ENTRADA):
    pred = pd.read_csv(ruta)
    base, servicios = construir_grupos(pred)
    filas, detalle_principal = [], None
    for objetivo in SENSIBILIDAD:
        det = decidir(base, servicios, objetivo)
        if objetivo == OCUPACION_OBJETIVO:
            detalle_principal = det
        for etiqueta, sub in [(f">= {MIN_SERVICIOS} servicios", det[det["n_servicios"] >= MIN_SERVICIOS]),
                              ("todos los grupos", det)]:
            if sub.empty:
                continue
            for config, nombre in [("A", "A referencia + regla"), ("B", "B XGBoost + regla"),
                                   ("C", "C XGBoost + difuso (anclado al objetivo)"),
                                   ("Cp", "C' XGBoost + difuso (percentiles)")]:
                filas.append({"ocupacion_objetivo": objetivo, "grupos": etiqueta, "configuracion": nombre,
                              **metricas(sub, config)})
    tabla = pd.DataFrame(filas)

    os.makedirs(os.path.dirname(RUTA_SALIDA), exist_ok=True)
    tabla.to_csv(RUTA_SALIDA, index=False)
    detalle_principal.to_csv(RUTA_DETALLE, index=False)

    det = detalle_principal
    sub = det[det["n_servicios"] >= MIN_SERVICIOS]
    print(f"Grupos (fecha, operador, tipo): {len(det)} | con >= {MIN_SERVICIOS} servicios: {len(sub)} | "
          f"ocupacion objetivo {OCUPACION_OBJETIVO}\n")
    principal = tabla[(tabla["ocupacion_objetivo"] == OCUPACION_OBJETIVO)]
    for etiqueta in principal["grupos"].unique():
        print(f"Grupos: {etiqueta}")
        print(principal[principal["grupos"] == etiqueta].drop(columns=["ocupacion_objetivo", "grupos"]).to_string(index=False))
        print()
    if len(sub):
        print("OE1 (B frente a A):", comparar(sub, "B", "A"))
        print("OE2 (C frente a B):", comparar(sub, "C", "B"))
        print("Sensibilidad (C' frente a B):", comparar(sub, "Cp", "B"))
    print("\nLimitaciones: n acotado por el tope de captura; el difuso no recibe n; demanda censurada; un solo feriado.")
    print(f"Guardado: {RUTA_SALIDA} y {RUTA_DETALLE}")


if __name__ == "__main__":
    main()