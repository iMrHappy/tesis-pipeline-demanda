import os
from pytrends.request import TrendReq
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Configuración inicial
load_dotenv()
db_url = os.getenv("DATABASE_URL")

try:
    engine = create_engine(db_url)
    print("\n[1/3] Conectando a Google Trends (Filtro de Marcas y Plataformas)...")
    
    pytrends = TrendReq(hl='es-PE', tz=300)
    
    # Filtro masivo: Plataformas y marcas de tu directorio
    kw_list = ["redbus", "transportes chiclayo", "ittsa", "transportes linea", "pasajes"]
    
    # Sin categoría restrictiva para capturar todo el tráfico
    pytrends.build_payload(kw_list, cat=203, timeframe='today 1-m', geo='PE-LIM')
    df_trends = pytrends.interest_over_time()
    
    if not df_trends.empty:
        if 'isPartial' in df_trends.columns:
            df_trends = df_trends.drop(columns=['isPartial'])
            
        # Técnica de suavizado: Promedio de todas las marcas en los últimos 3 días
        # Esto elimina el error de días incompletos o desfases horarios de Google
        ultimos_3_dias = df_trends.tail(3).mean(axis=1)
        indice_real = int(ultimos_3_dias.mean())
        
        # Tomamos la fecha del último día válido
        latest_date = df_trends.index[-2].date() 
        
        print(f"[2/3] Índice de Demanda calculado exitosamente:")
        print(f"      - Fecha de corte : {latest_date}")
        print(f"      - Índice Suavizado (0-100): {indice_real}")
        
        # 3. Guardar en Supabase
        with engine.connect() as connection:
            query = text("""
                INSERT INTO staging.fact_google_trends (target_date, search_intent_index)
                VALUES (:date, :idx)
                ON CONFLICT (target_date) DO UPDATE 
                SET search_intent_index = EXCLUDED.search_intent_index;
            """)
            connection.execute(query, {"date": str(latest_date), "idx": indice_real})
            connection.commit()
            
        print("\n[3/3] ¡Éxito! Intención de viaje inyectada en la base de datos.")
        print("====================================================\n")
    else:
        print("Google no reportó datos suficientes hoy.")

except Exception as e:
    print("\n[ERROR] Ocurrió un problema en la extracción:", e)
    raise