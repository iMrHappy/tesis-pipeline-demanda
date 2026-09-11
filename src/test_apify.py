import os
from dotenv import load_dotenv
from apify_client import ApifyClient

# 1. Cargar el token desde el archivo .env
load_dotenv()
apify_token = os.getenv("APIFY_API_TOKEN")

try:
    client = ApifyClient(apify_token)
    print("\nConectando a Apify de forma automatizada...")
    
    run_input = {
        "country": "peru",
        "dateOfJourney": "2026-09-07",
        "destination": "Chiclayo",
        "source": "Lima",
        "maxItems": 5, 
        "proxyConfiguration": {
            "useApifyProxy": True
        }
    }
    
    print("Extrayendo datos... esto puede tardar un par de minutos.")
    run = client.actor("rl1987/redbus-api-scraper").call(run_input=run_input)
    
    # 2. Extraer atributos adaptándonos a la nueva versión de la librería (como Objeto)
    estado = getattr(run, "status", None)
    id_dataset = getattr(run, "default_dataset_id", getattr(run, "defaultDatasetId", None))
    
    # 3. Validación de estado
    if estado != "SUCCEEDED":
        print("\n[ADVERTENCIA] La extracción no fue exitosa.")
        print("Estado final:", estado)
    else:
        print("\n====================================================")
        print("¡Extracción terminada! Aquí están los primeros resultados:")
        
        # 4. Leer e imprimir los resultados
        for item in client.dataset(id_dataset).iterate_items():
            empresa = item.get("travelsName", "Desconocido")
            asientos_libres = item.get("availableSeats", "N/A")
            capacidad = item.get("totalSeats", "N/A")
            
            print(f"- Empresa: {empresa} | Asientos: {asientos_libres} libres de {capacidad} totales.")
            
        print("====================================================\n")

except Exception as e:
    print("\n[ERROR] Ocurrió un problema en la ejecución de Python:")
    print(type(e).__name__, e)