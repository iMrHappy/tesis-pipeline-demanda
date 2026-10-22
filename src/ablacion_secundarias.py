"""
ablacion_secundarias.py
Mide cuanto aportan las variables secundarias (tendencias, trafico, dolar, petroleo) al modelo.
Entrena y evalua con la MISMA validacion temporal, una vez con ellas y otra sin ellas, y compara.

Ubicacion: src/ablacion_secundarias.py   (requiere train_xgboost.py y features.py)
Ejecucion (desde la raiz del repo): python src/ablacion_secundarias.py
Salida: consola y models/ablacion_secundarias.csv
"""

import os

import pandas as pd

from features import TARGET, construir_X
from train_xgboost import cargar_datos, evaluar, modelo_xgb, preparar, resumen

SECUNDARIAS = ["indice_busqueda", "retraso_trafico_min", "dolar_compra", "precio_petroleo"]
MODELOS = ["Ridge", "Random Forest", "XGBoost", "XGBoost (objetivo incremento)"]


def mae_por_fecha(res, modelo):
    r = res[res["modelo"] == modelo]
    return (r["y"] - r["pred"]).abs().groupby(r["fecha"]).mean()


def main():
    df = preparar(cargar_datos())
    X = construir_X(df)
    X = X.drop(columns=[c for c in X.columns if X[c].nunique(dropna=True) <= 1])
    presentes = [c for c in SECUNDARIAS if c in X.columns]
    X_sin = X.drop(columns=presentes)

    print(f"Filas: {len(df)} | Fechas: {df['fecha_viaje'].nunique()}")
    print(f"Variables secundarias en el modelo actual: {presentes}")
    print(f"Variables restantes sin ellas: {X_sin.shape[1]} (con ellas: {X.shape[1]})")

    # 1) Importancia de las variables secundarias en el modelo entrenado con todos los datos
    imp = pd.Series(modelo_xgb().fit(X, df[TARGET].values).feature_importances_, index=X.columns)
    imp_sec = imp[imp.index.isin(presentes)].sort_values(ascending=False)
    print("\nImportancia (ganancia) de las secundarias, sobre un total de 1.0:")
    print(imp_sec.round(4).to_string() if len(imp_sec) else "  (ninguna presente)")
    print(f"Suma de las secundarias: {imp_sec.sum():.3f}  |  puesto medio entre {len(imp)} variables: "
          f"{int(imp.rank(ascending=False)[imp_sec.index].mean()) if len(imp_sec) else '-'}")

    # 2) Efecto real sobre el error, con la misma validacion temporal
    res_con, n_folds = evaluar(df, X)
    res_sin, _ = evaluar(df, X_sin)
    t_con = resumen(res_con).set_index("modelo")
    t_sin = resumen(res_sin).set_index("modelo")

    filas = []
    for m in MODELOS:
        filas.append({
            "modelo": m,
            "MAE_con": t_con.loc[m, "MAE"], "MAE_sin": t_sin.loc[m, "MAE"],
            "cambio_MAE": round(t_sin.loc[m, "MAE"] - t_con.loc[m, "MAE"], 3),
            "RMSE_con": t_con.loc[m, "RMSE"], "RMSE_sin": t_sin.loc[m, "RMSE"],
        })
    tabla = pd.DataFrame(filas)
    print(f"\nValidacion temporal ({n_folds} evaluaciones). cambio_MAE < 0 significa que SIN ellas el error baja:\n")
    print(tabla.to_string(index=False))

    d = mae_por_fecha(res_sin, "XGBoost") - mae_por_fecha(res_con, "XGBoost")
    print(f"\nXGBoost sin las secundarias mejora en {int((d < 0).sum())} de {len(d)} fechas "
          f"y empeora en {int((d > 0).sum())}.")

    cambio = float(tabla.loc[tabla["modelo"] == "XGBoost", "cambio_MAE"].iloc[0])
    if cambio <= 0.15:
        print("\nLECTURA: quitarlas no empeora de forma apreciable el error. Se pueden retirar del modelo.")
    else:
        print("\nLECTURA: sin ellas el error sube. Antes de conservarlas, revisa con que fecha se unen en la vista: "
              "si es la fecha de viaje, la mejora puede venir de una fuga de informacion.")

    os.makedirs("models", exist_ok=True)
    tabla.to_csv("models/ablacion_secundarias.csv", index=False)
    print("\nGuardado en models/ablacion_secundarias.csv")


if __name__ == "__main__":
    main()
