import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Cargar variables de entorno desde el archivo .env
load_dotenv()

# 2. Obtener la URL de conexión segura
db_url = os.getenv("DATABASE_URL")

try:
    # 3. Crear el "motor" de conexión usando SQLAlchemy
    engine = create_engine(db_url)
    
    # 4. Intentar conectarse y hacer una consulta básica de prueba
    with engine.connect() as connection:
        result = connection.execute(text("SELECT version();"))
        version = result.fetchone()
        
        print("\n====================================================")
        print("¡Conexión exitosa, Jair!")
        print("Lograste conectarte a Supabase.")
        print("Versión del motor:", version[0])
        print("====================================================\n")
        
except Exception as e:
    print("\n[ERROR] No se pudo conectar a la base de datos.")
    print("Detalle del error:", e)
    print("\nRevisa que tu contraseña en el archivo .env sea correcta y no tenga el símbolo @.")