import os
import holidays
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Cargar la conexión
load_dotenv()
db_url = os.getenv("DATABASE_URL")

try:
    engine = create_engine(db_url)
    print("\nCalculando feriados de Perú automáticamente...")
    
    # 2. Generar dinámicamente los feriados de Perú para 2026 y 2027
    feriados_peru = holidays.Peru(years=[2026, 2027])
    
    with engine.connect() as connection:
        # 3. Limpiar la tabla (resetear lo que hicimos manualmente)
        connection.execute(text("UPDATE staging.dim_calendar SET is_holiday = FALSE, holiday_name = NULL;"))
        
        # 4. Consulta de actualización dinámica
        query = text("""
            UPDATE staging.dim_calendar 
            SET is_holiday = TRUE, holiday_name = :nombre
            WHERE date_id = :fecha
        """)
        
        contador = 0
        for fecha, nombre in feriados_peru.items():
            # La librería devuelve objetos de fecha, los pasamos a string para asegurar compatibilidad
            connection.execute(query, {"nombre": nombre, "fecha": str(fecha)})
            contador += 1
            
        connection.commit()
        
        print(f"¡Éxito! El sistema automatizó {contador} feriados para 2026 y 2027.")
        print("====================================================\n")
        
except Exception as e:
    print("\n[ERROR] Ocurrió un problema al automatizar los feriados:")
    print(e)