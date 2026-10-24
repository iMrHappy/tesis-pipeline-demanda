import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Cargar la conexión a la base de datos
load_dotenv()
db_url = os.getenv("DATABASE_URL")

# 2. Diccionario de feriados nacionales peruanos para 2026
feriados_peru_2026 = {
    "2026-01-01": "Año Nuevo",
    "2026-04-02": "Jueves Santo",
    "2026-04-03": "Viernes Santo",
    "2026-05-01": "Día del Trabajo",
    "2026-06-29": "San Pedro y San Pablo",
    "2026-07-28": "Fiestas Patrias",
    "2026-07-29": "Fiestas Patrias",
    "2026-08-30": "Santa Rosa de Lima",
    "2026-10-08": "Combate de Angamos",
    "2026-11-01": "Día de Todos los Santos",
    "2026-12-08": "Inmaculada Concepción",
    "2026-12-09": "Batalla de Ayacucho",
    "2026-12-25": "Navidad"
}

try:
    engine = create_engine(db_url)
    print("\nIniciando la actualización de feriados en la dimensión de calendario...")
    
    with engine.connect() as connection:
        # 3. Consulta SQL para actualizar cada fecha
        query = text("""
            UPDATE staging.dim_calendar 
            SET is_holiday = TRUE, holiday_name = :nombre
            WHERE date_id = :fecha
        """)
        
        contador = 0
        for fecha, nombre in feriados_peru_2026.items():
            connection.execute(query, {"nombre": nombre, "fecha": fecha})
            contador += 1
            
        connection.commit()
        
        print(f"¡Éxito! Se actualizaron {contador} feriados nacionales en la base de datos.")
        print("====================================================\n")
        
except Exception as e:
    print("\n[ERROR] Ocurrió un problema al actualizar los feriados:")
    print(e)