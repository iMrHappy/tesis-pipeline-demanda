"""
evaluar_pronostico.py  (T6)
Prueba pareada de la mejora del modelo sobre las predicciones de validacion por servicio.

Para cada comparacion A vs B calcula:
  - diferencia de MAE (MAE de B menos MAE de A; positiva = A tiene menos error) con intervalo del 95 %
    por bootstrap por bloques de fecha (se remuestrean FECHAS, no filas; 2000 replicas; semilla 42);
  - cuantas fechas favorecen a A y prueba de signos exacta;
  - prueba de Diebold-Mariano (opcional, aproximada) sobre el error absoluto diario.

Entrada: models/predicciones_cv.csv (la genera train_xgboost.py)
Salida:  models/prueba_pareada.csv y resumen en consola. Solo NumPy y pandas.
No sirve para elegir el modelo principal: ese se fijo antes de ver resultados.

Ubicacion: src/evaluar_pronostico.py
Ejecucion (desde la raiz del repo): python src/evaluar_pronostico.py
"""

import math
import os

import numpy as np
import pandas as pd

RUTA_ENTRADA = "models/predicciones_cv.csv"
RUTA_SALIDA = "models/prueba_pareada.csv"
REFERENCIA = "Persistencia + incremento mediano"
COMPARACIONES = [
    ("XGBoost", REFERENCIA),
    ("Random Forest", REFERENCIA),
    ("XGBoost", "Random Forest"),
]
REPLICAS = 2000
SEMILLA = 42
HORIZONTE_DIAS = 3


def por_fecha(pred, modelo):
    """Suma del error absoluto y numero de predicciones, por fecha, para un modelo."""
    d = pred[pred["modelo"] == modelo].copy()
    d["err"] = (d["y"] - d["pred"]).abs()
    return d.groupby("fecha")["err"].agg(suma="sum", n="count")


def p_signos(a_favor, en_contra):
    """Prueba de signos exacta, dos colas (los empates se descartan)."""
    n = a_favor + en_contra
    if n == 0:
        return 1.0
    k = min(a_favor, en_contra)
    cola = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return float(min(1.0, 2 * cola))


def diebold_mariano(d, lags=HORIZONTE_DIAS - 1):
    """DM con varianza HAC (Bartlett) y correccion de Harvey; p-valor con normal (aproximado)."""
    d = np.asarray(d, dtype=float)
    n, h = len(d), lags + 1
    dc = d - d.mean()
    v = np.mean(dc * dc)
    for k in range(1, lags + 1):
        v += 2 * (1 - k / (lags + 1)) * np.mean(dc[k:] * dc[:-k])
    v = max(v, 1e-12)
    stat = d.mean() / math.sqrt(v / n)
    ajuste = (n + 1 - 2 * h + h * (h - 1) / n) / n
    stat *= math.sqrt(max(ajuste, 0.0))
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(stat) / math.sqrt(2))))
    return stat, p


def comparar(pred, a, b):
    sa, sb = por_fecha(pred, a), por_fecha(pred, b)
    fechas = sa.index.intersection(sb.index)
    if len(fechas) < 3:
        raise SystemExit(f"Pocas fechas comunes entre {a} y {b}.")
    sa, sb = sa.loc[fechas], sb.loc[fechas]
    n = sa["n"].values.astype(float)
    mae_a, mae_b = sa["suma"].sum() / n.sum(), sb["suma"].sum() / n.sum()

    rng = np.random.default_rng(SEMILLA)
    idx = rng.integers(0, len(fechas), size=(REPLICAS, len(fechas)))
    tot = n[idx].sum(axis=1)
    dif = sb["suma"].values[idx].sum(axis=1) / tot - sa["suma"].values[idx].sum(axis=1) / tot
    lo, hi = np.percentile(dif, [2.5, 97.5])

    d_dia = sb["suma"].values / n - sa["suma"].values / n  # positivo = A mejor ese dia
    a_favor, en_contra = int((d_dia > 0).sum()), int((d_dia < 0).sum())
    dm, p_dm = diebold_mariano(d_dia)

    if lo > 0:
        lectura = f"{a} supera a {b}: el intervalo del 95 % no incluye 0."
    elif hi < 0:
        lectura = f"{a} es peor que {b}: el intervalo del 95 % no incluye 0."
    else:
        lectura = f"Sin evidencia de diferencia entre {a} y {b}: el intervalo del 95 % incluye 0."
    return {
        "A": a, "B": b, "MAE_A": round(mae_a, 3), "MAE_B": round(mae_b, 3),
        "dif_MAE_(B-A)": round(mae_b - mae_a, 3), "IC95_inf": round(lo, 3), "IC95_sup": round(hi, 3),
        "fechas_a_favor_de_A": a_favor, "fechas_en_contra": en_contra, "fechas_total": len(fechas),
        "p_signos": round(p_signos(a_favor, en_contra), 3),
        "DM_estadistico": round(dm, 3), "DM_p_aprox": round(p_dm, 3), "lectura": lectura,
    }


def main(ruta=RUTA_ENTRADA):
    pred = pd.read_csv(ruta)
    filas = [comparar(pred, a, b) for a, b in COMPARACIONES]
    tabla = pd.DataFrame(filas)
    print(f"Prueba pareada | {pred['fecha'].nunique()} fechas | {REPLICAS} replicas bootstrap por bloques de fecha "
          f"(semilla {SEMILLA})\n")
    for f in filas:
        print(f"{f['A']} vs {f['B']}")
        print(f"  MAE {f['MAE_A']} vs {f['MAE_B']} | diferencia {f['dif_MAE_(B-A)']} "
              f"[IC95 {f['IC95_inf']}; {f['IC95_sup']}]")
        print(f"  Fechas a favor: {f['fechas_a_favor_de_A']} de {f['fechas_total']} | prueba de signos p={f['p_signos']}"
              f" | Diebold-Mariano p~{f['DM_p_aprox']} (aprox.)")
        print(f"  -> {f['lectura']}\n")
    print("Nota: este resultado no se usa para cambiar el modelo principal (se fijo antes de ver resultados).")
    os.makedirs(os.path.dirname(RUTA_SALIDA), exist_ok=True)
    tabla.to_csv(RUTA_SALIDA, index=False)
    print(f"Guardado en {RUTA_SALIDA}")


if __name__ == "__main__":
    main()
