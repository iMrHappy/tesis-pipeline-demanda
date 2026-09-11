import os
import calendar
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Cargar conexión
load_dotenv()
db_url = os.getenv("DATABASE_URL")

try:
    engine = create_engine(db_url)
    print("\n[1/3] Descargando el calendario actual...")
    
    # 2. Traer el calendario a un DataFrame de Pandas
    query_select = "SELECT date_id, is_holiday FROM staging.dim_calendar ORDER BY date_id"
    df = pd.read_sql(query_select, engine)
    df['date_id'] = pd.to_datetime(df['date_id'])
    
    print("[2/3] Calculando Lógica Difusa y Días de Pago...")
    
    # 3. Lógica para los Días de Pago
    def calc_days_to_payday(date):
        day = date.day
        if day <= 15:
            return 15 - day
        else:
            last_day = calendar.monthrange(date.year, date.month)[1]
            return last_day - day
            
    df['days_to_payday'] = df['date_id'].apply(calc_days_to_payday)
    
    # 4. Lógica Difusa (Fuzzy Logic) para los Feriados
    df['holiday_proximity'] = 0.0
    holiday_indices = df[df['is_holiday'] == True].index
    
    for idx in holiday_indices:
        df.loc[idx, 'holiday_proximity'] = 1.0
        # Onda expansiva: 1 día antes/después (0.75)
        if idx - 1 >= 0: df.loc[idx - 1, 'holiday_proximity'] = max(df.loc[idx - 1, 'holiday_proximity'], 0.75)
        if idx + 1 < len(df): df.loc[idx + 1, 'holiday_proximity'] = max(df.loc[idx + 1, 'holiday_proximity'], 0.75)
        # Onda expansiva: 2 días antes/después (0.50)
        if idx - 2 >= 0: df.loc[idx - 2, 'holiday_proximity'] = max(df.loc[idx - 2, 'holiday_proximity'], 0.50)
        if idx + 2 < len(df): df.loc[idx + 2, 'holiday_proximity'] = max(df.loc[idx + 2, 'holiday_proximity'], 0.50)
        # Onda expansiva: 3 días antes/después (0.25)
        if idx - 3 >= 0: df.loc[idx - 3, 'holiday_proximity'] = max(df.loc[idx - 3, 'holiday_proximity'], 0.25)
        if idx + 3 < len(df): df.loc[idx + 3, 'holiday_proximity'] = max(df.loc[idx + 3, 'holiday_proximity'], 0.25)
        
    print("[3/3] Inyectando los nuevos cálculos en Supabase (puede tardar unos segundos)...")
    
    # 5. Actualizar la base de datos
    with engine.connect() as connection:
        update_query = text("""
            UPDATE staging.dim_calendar 
            SET holiday_proximity = :prox, days_to_payday = :payday
            WHERE date_id = :date
        """)
        
        for _, row in df.iterrows():
            connection.execute(update_query, {
                "prox": float(row['holiday_proximity']), 
                "payday": int(row['days_to_payday']), 
                "date": str(row['date_id'].date())
            })
            
        connection.commit()
        
    print("\n====================================================")
    print("¡Golazo! Se aplicó la lógica difusa y variables financieras exitosamente.")
    print("====================================================\n")

except Exception as e:
    print("\n[ERROR] Ocurrió un problema en el procesamiento:", e)