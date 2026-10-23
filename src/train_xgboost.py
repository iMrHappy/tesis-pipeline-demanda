"""
train_xgboost.py
Entrena y evalua modelos de ocupacion final (horizonte D+3) desde staging.vw_training_d3.

Cambios 22/10/2026 (MEJORAS_PROYECTO.md):
  T2: solo se entrena con viajes YA realizados (fecha_viaje < hoy en Lima).
  T4: la validacion respeta el horizonte: para predecir una fecha solo se usan viajes cuyo
      resultado ya se conocia 3 dias antes (sin fuga temporal).
  T5: se guardan las predicciones de validacion por servicio (models/predicciones_cv.csv).
  Rastro: antes de sobrescribir un resultado se archiva el anterior en models/archivo/.

Ubicacion: src/train_xgboost.py   (requiere src/features.py)
Ejecucion (desde la raiz del repo): python src/train_xgboost.py

Salida (carpeta models/): demand_model.joblib, metricas_cv.csv, mae_por_fecha.csv,
importancia_features.csv, predicciones_cv.csv
"""

import os
import shutil
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from features import CERO_ES_FALTANTE, TARGET, construir_X, transformar

VISTA = "staging.vw_training_d3"
MIN_FECHAS_TRAIN = 5
HORIZONTE_DIAS = 3
SEED = 42
MODELO_PRINCIPAL = "XGBoost"
ZONA = ZoneInfo("America/Lima")
ARCHIVOS_A_ARCHIVAR = [
    "models/demand_model.joblib", "models/metricas_cv.csv", "models/mae_por_fecha.csv",
    "models/importancia_features.csv", "models/predicciones_cv.csv",
]


def cargar_datos():
    load_dotenv()
    engine = create_engine(os.getenv("DATABASE_URL"))
    return pd.read_sql(f"SELECT * FROM {VISTA}", engine)


def preparar(df, hoy=None):
    """Solo viajes ya realizados: el objetivo del dia en curso se toma antes de las salidas y es incompleto."""
    hoy = hoy or datetime.now(ZONA).date()
    d = transformar(df).dropna(subset=[TARGET])
    return d[d["fecha_viaje"] < hoy].reset_index(drop=True)


def modelo_xgb():
    return XGBRegressor(
        n_estimators=300, learning_rate=0.05, max_depth=3, min_child_weight=5,
        subsample=0.7, colsample_bytree=0.7, reg_lambda=10.0, reg_alpha=0.0,
        objective="reg:squarederror", random_state=SEED, n_jobs=1,
    )


def modelo_rf():
    return make_pipeline(
        SimpleImputer(strategy="median"),
        RandomForestRegressor(n_estimators=300, max_depth=5, min_samples_leaf=3,
                              random_state=SEED, n_jobs=1),
    )


def modelo_ridge():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=10.0))


def acotar(pred, df):
    """La ocupacion final no baja de la observada a D+3 (incremento minimo observado = 0)
    ni supera la capacidad del bus."""
    return np.clip(pred, df["ocupacion_d3"].values, df["asientos_totales"].values)


def evaluar(df, X):
    """Validacion temporal sin fuga: para predecir la fecha f solo se entrena con viajes anteriores
    a f - HORIZONTE_DIAS, que son los que ya habian ocurrido cuando se emitio el pronostico."""
    fechas = sorted(df["fecha_viaje"].unique())
    registros, n_folds = [], 0
    for f_te in fechas:
        corte = f_te - timedelta(days=HORIZONTE_DIAS)
        tr = (df["fecha_viaje"] < corte).values
        if df.loc[tr, "fecha_viaje"].nunique() < MIN_FECHAS_TRAIN:
            continue
        te = (df["fecha_viaje"] == f_te).values
        n_folds += 1
        d_tr, d_te = df[tr], df[te]
        y_tr, y_te = d_tr[TARGET].values, d_te[TARGET].values
        inc_tr = y_tr - d_tr["ocupacion_d3"].values

        preds = {
            "Persistencia (final = D+3)": d_te["ocupacion_d3"].values,
            "Persistencia + incremento mediano": d_te["ocupacion_d3"].values + np.median(inc_tr),
        }
        for nombre, fab in [("Ridge", modelo_ridge), ("Random Forest", modelo_rf), ("XGBoost", modelo_xgb)]:
            preds[nombre] = fab().fit(X[tr], y_tr).predict(X[te])
        # Analisis de robustez (Opcion B): predecir el incremento y reconstruir
        mb = modelo_xgb().fit(X[tr], inc_tr)
        preds["XGBoost (objetivo incremento)"] = d_te["ocupacion_d3"].values + mb.predict(X[te])

        for nombre, p in preds.items():
            p = acotar(p, d_te)
            for (_, fila), yt, yp in zip(d_te.iterrows(), y_te, p):
                registros.append({
                    "modelo": nombre, "fecha": fila["fecha_viaje"], "operador": fila["operador"],
                    "tipo_bus": fila["tipo_bus"], "salida": fila["departure_time"],
                    "asientos": fila["asientos_totales"], "ocupacion_d3": fila["ocupacion_d3"],
                    "y": yt, "pred": float(yp),
                })
    if n_folds == 0:
        raise SystemExit(f"No hay evaluaciones posibles: se necesitan al menos {MIN_FECHAS_TRAIN} fechas de "
                         f"entrenamiento anteriores a cada fecha de prueba menos {HORIZONTE_DIAS} dias.")
    return pd.DataFrame(registros), n_folds


def resumen(res):
    filas = []
    for nombre, g in res.groupby("modelo", sort=False):
        filas.append({
            "modelo": nombre,
            "MAE": mean_absolute_error(g["y"], g["pred"]),
            "RMSE": float(np.sqrt(mean_squared_error(g["y"], g["pred"]))),
            "n_pred": len(g),
        })
    t = pd.DataFrame(filas)
    base = t.loc[t["modelo"] == "Persistencia (final = D+3)", "MAE"].iloc[0]
    base_inc = t.loc[t["modelo"] == "Persistencia + incremento mediano", "MAE"].iloc[0]
    t["mejora_vs_persistencia_%"] = (1 - t["MAE"] / base) * 100
    t["mejora_vs_pers+incremento_%"] = (1 - t["MAE"] / base_inc) * 100
    return t.round(3)


def mae_por_fecha(res):
    r = res.assign(err=(res["y"] - res["pred"]).abs())
    tabla = r.pivot_table(index="fecha", columns="modelo", values="err", aggfunc="mean")
    cols = ["Persistencia + incremento mediano", "Ridge", "Random Forest", "XGBoost"]
    return tabla[cols].round(2)


def archivar_anteriores(hoy):
    """Conserva los resultados previos con fecha antes de sobrescribirlos (no se pierde ninguna version)."""
    os.makedirs("models/archivo", exist_ok=True)
    for ruta in ARCHIVOS_A_ARCHIVAR:
        if not os.path.exists(ruta):
            continue
        base, ext = os.path.splitext(os.path.basename(ruta))
        destino, n = f"models/archivo/{base}_{hoy}{ext}", 2
        while os.path.exists(destino):
            destino, n = f"models/archivo/{base}_{hoy}_{n}{ext}", n + 1
        shutil.copy2(ruta, destino)
        print(f"  archivado: {destino}")


def main(df=None, hoy=None):
    hoy = hoy or datetime.now(ZONA).date()
    df = preparar(cargar_datos() if df is None else df, hoy=hoy)
    X = construir_X(df)
    constantes = [c for c in X.columns if X[c].nunique(dropna=True) <= 1]
    X = X.drop(columns=constantes)

    print(f"Filas: {len(df)} | Fechas de viaje: {df['fecha_viaje'].nunique()} "
          f"({df['fecha_viaje'].min()} a {df['fecha_viaje'].max()}) | solo viajes anteriores a {hoy}")
    print(f"Variables del modelo: {X.shape[1]} | constantes descartadas: {constantes}")
    faltantes = X.isna().sum()
    print(f"Faltantes por columna:\n{faltantes[faltantes > 0]}")
    print(f"Target: media={df[TARGET].mean():.1f} std={df[TARGET].std():.1f} "
          f"| incremento mediano={np.median(df[TARGET] - df['ocupacion_d3']):.1f}")

    res, n_folds = evaluar(df, X)
    tabla = resumen(res)
    print(f"\nValidacion temporal sin fuga (entrena con viajes anteriores a fecha - {HORIZONTE_DIAS} dias): "
          f"{n_folds} evaluaciones\n")
    print(tabla.to_string(index=False))

    por_fecha = mae_por_fecha(res)
    print("\nMAE por fecha de prueba (variabilidad entre dias):")
    print(por_fecha.to_string())

    candidatos = tabla[tabla["modelo"].isin(["Ridge", "Random Forest", "XGBoost"])].sort_values("MAE")
    mejor_mae = candidatos.iloc[0]["modelo"]
    base_inc = tabla.loc[tabla["modelo"] == "Persistencia + incremento mediano", "MAE"].iloc[0]
    mae_principal = tabla.loc[tabla["modelo"] == MODELO_PRINCIPAL, "MAE"].iloc[0]
    if mae_principal >= base_inc:
        print(f"\n[AVISO] {MODELO_PRINCIPAL} no supera a 'Persistencia + incremento mediano'. "
              "Reportalo asi: con pocos datos el ML aun no aporta.")
    print(f"\nMejor por MAE: {mejor_mae} | Modelo guardado (principal de la tesis): {MODELO_PRINCIPAL}")

    final = modelo_xgb().fit(X, df[TARGET].values)
    imp = pd.Series(final.feature_importances_, index=X.columns).sort_values(ascending=False)
    print("\nImportancia de features (XGBoost, ganancia):")
    print(imp.head(10).round(3).to_string())

    os.makedirs("models", exist_ok=True)
    print("\nArchivando resultados anteriores:")
    archivar_anteriores(hoy)
    joblib.dump({
        "model": final, "model_name": MODELO_PRINCIPAL, "mejor_por_mae": mejor_mae,
        "features": list(X.columns), "target": TARGET, "horizonte": "D+3",
        "cero_es_faltante": CERO_ES_FALTANTE,
        "validacion": {"horizonte_dias": HORIZONTE_DIAS, "min_fechas_train": MIN_FECHAS_TRAIN,
                       "n_evaluaciones": n_folds},
        "n_filas": int(len(df)), "fecha_min": str(df["fecha_viaje"].min()),
        "fecha_max": str(df["fecha_viaje"].max()),
        "entrenado_en": datetime.now(ZONA).isoformat(timespec="seconds"),
        "metricas_cv": tabla.to_dict(orient="records"),
    }, "models/demand_model.joblib")
    tabla.to_csv("models/metricas_cv.csv", index=False)
    por_fecha.to_csv("models/mae_por_fecha.csv")
    imp.to_csv("models/importancia_features.csv", header=["importancia"])
    res.to_csv("models/predicciones_cv.csv", index=False)
    print("\nGuardado en models/: demand_model.joblib, metricas_cv.csv, mae_por_fecha.csv, "
          "importancia_features.csv, predicciones_cv.csv")


if __name__ == "__main__":
    main()