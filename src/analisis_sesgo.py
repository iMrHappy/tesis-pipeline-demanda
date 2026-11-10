"""
analisis_sesgo.py
Diagnostico de solo lectura sobre models/predicciones_cv.csv y models/decisiones_detalle.csv.
  1) ¿XGBoost subestima o sobreestima? (por dia, hora y nivel de ocupacion a D+3)
  2) ¿Por que pierde el difuso? (tabla de la decision correcta frente a la decision de cada configuracion)
No toca Supabase ni Apify. Ejecutar desde la raiz:  python src/analisis_sesgo.py
"""

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

DIAS = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]

pd.set_option("display.width", 160)

pred = pd.read_csv("models/predicciones_cv.csv", parse_dates=["salida"])
x = pred[pred["modelo"] == "XGBoost"].copy()
x["error"] = x["pred"] - x["y"]                      # > 0 sobreestima, < 0 subestima
x["pct_d3"] = x["ocupacion_d3"] / x["asientos"] * 100
x["pct_real"] = x["y"] / x["asientos"] * 100
x["pct_pred"] = x["pred"] / x["asientos"] * 100
x["dia"] = pd.to_datetime(x["fecha"]).dt.dayofweek.map(lambda i: DIAS[i])
x["hora"] = x["salida"].dt.hour


def resumen(g):
    return pd.Series({
        "n": len(g),
        "real_%": g["pct_real"].mean(),
        "prev_%": g["pct_pred"].mean(),
        "error_medio": g["error"].mean(),
        "mae": g["error"].abs().mean(),
    })


print("== XGBoost: sesgo global (error = prevista - real; negativo = subestima) ==")
print(resumen(x).round(2).to_string())

print("\n== Por dia de la semana ==")
print(x.groupby("dia").apply(resumen).reindex(DIAS).dropna().round(2).to_string())

print("\n== Por hora de salida ==")
print(x.groupby("hora").apply(resumen).round(2).to_string())

print("\n== Por ocupacion a D+3 (dato conocido al predecir) ==")
x["tramo_d3"] = pd.cut(x["pct_d3"], [-1, 20, 30, 40, 50, 101])
print(x.groupby("tramo_d3", observed=True).apply(resumen).round(2).to_string())

llenos = x[x["pct_real"] >= 90]
print(f"\nServicios que terminaron >= 90 % llenos: {len(llenos)} de {len(x)} "
      f"({len(llenos) / len(x) * 100:.1f} %). Error medio en ellos: {llenos['error'].mean():.1f} asientos "
      f"(prevista media {llenos['pct_pred'].mean():.1f} % frente a real {llenos['pct_real'].mean():.1f} %)")

d = pd.read_csv("models/decisiones_detalle.csv")
d = d[d["n_servicios"] >= 3]
print(f"\n== Decision (grupos con >= 3 servicios: {len(d)}) ==")
print("Distribucion de la decision correcta (delta_correcto):")
print(d["delta_correcto"].value_counts().sort_index().to_string())
print(f"\nDifuso C: minimo delta_C = {d['delta_C'].min()}, minimo delta_C_continuo = {d['delta_C_continuo'].min():.2f}")
for col, nombre in [("delta_B", "B (XGBoost + regla)"), ("delta_C", "C (difuso)")]:
    print(f"\nFilas = decision correcta, columnas = decision de {nombre}")
    print(pd.crosstab(d["delta_correcto"], d[col], margins=True).to_string())
