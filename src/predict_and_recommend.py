"""
predict_and_recommend.py
Script de integracion end-to-end:

    1. Carga el modelo XGBoost ya entrenado (demand_model.joblib).
    2. Consulta la vista staging.vw_demand_features en Supabase
       para obtener las variables de una ruta/fecha especifica.
    3. Genera la prediccion de demanda con XGBoost.
    4. Pasa la prediccion + variables de contexto al Sistema de
       Inferencia Difusa (DispatchFuzzySystem) para obtener la
       recomendacion operativa de despacho.
    5. Devuelve un JSON listo para consumir en el dashboard Streamlit.

Ubicacion: src/predict_and_recommend.py
Ejecucion: python src/predict_and_recommend.py

Requiere las variables de entorno (.env):
    DATABASE_URL

Requiere las librerias (ya deben estar en requirements.txt):
    xgboost, sqlalchemy, psycopg2-binary, joblib, pandas, python-dotenv
"""

import os
import joblib
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

from dispatch_fis import DispatchFuzzySystem

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
MODEL_PATH = os.getenv("MODEL_PATH", "models/demand_model.joblib")


def obtener_features_desde_supabase(fecha_viaje: str, route_id: int) -> pd.DataFrame:
    """
    Consulta la vista maestra staging.vw_demand_features para una
    fecha y ruta especifica.
    """
    engine = create_engine(DATABASE_URL)
    query = text("""
        SELECT *
        FROM staging.vw_demand_features
        WHERE fecha = :fecha_viaje
          AND route_id = :route_id
        LIMIT 1
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"fecha_viaje": fecha_viaje, "route_id": route_id})
    return df


def predecir_demanda(df_features: pd.DataFrame, feature_columns: list[str]) -> float:
    """
    Carga el modelo XGBoost entrenado y genera la prediccion numerica
    de demanda (0-100, normalizada como % de ocupacion estimada).
    """
    modelo = joblib.load(MODEL_PATH)
    X = df_features[feature_columns]
    prediccion = modelo.predict(X)[0]
    prediccion = max(0.0, min(100.0, float(prediccion)))
    return prediccion


def generar_recomendacion(fecha_viaje: str, route_id: int, feature_columns: list[str]) -> dict:
    """
    Orquesta el flujo completo: obtiene features -> predice con XGBoost
    -> genera recomendacion con el sistema difuso.
    """
    df = obtener_features_desde_supabase(fecha_viaje, route_id)

    if df.empty:
        return {"error": "No se encontraron features para la fecha/ruta indicada."}

    demanda_predicha = predecir_demanda(df, feature_columns)

    dias_a_feriado_normalizado = int(df["holiday_proximity"].iloc[0] * -5) if "holiday_proximity" in df.columns else 0
    indice_clima = float(df.get("clima_score", pd.Series([50])).iloc[0])

    fis = DispatchFuzzySystem()
    resultado_fis = fis.recomendar(
        demanda_predicha=demanda_predicha,
        dias_a_feriado=dias_a_feriado_normalizado,
        indice_clima=indice_clima,
    )

    return {
        "fecha_viaje": fecha_viaje,
        "route_id": route_id,
        "demanda_predicha_pct": round(demanda_predicha, 2),
        "unidades_recomendadas": resultado_fis["unidades_recomendadas"],
        "recomendacion": resultado_fis["etiqueta"],
        "detalle_reglas_activadas": resultado_fis["activaciones"],
    }


if __name__ == "__main__":
    FEATURE_COLUMNS = [
        "holiday_proximity", "is_weekend", "temp_max", "precipitation",
        "google_trends_score", "traffic_delay_min", "available_seats_sum",
        "min_fare", "usd_pen", "wti_price",
    ]

    resultado = generar_recomendacion(
        fecha_viaje="2026-10-08",
        route_id=1,
        feature_columns=FEATURE_COLUMNS,
    )
    print(resultado)