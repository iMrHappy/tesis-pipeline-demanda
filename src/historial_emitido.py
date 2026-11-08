"""
historial_emitido.py
Guarda las predicciones EMITIDAS (congeladas) para reconstruir despues un historial honesto.

Regla: la primera prediccion emitida de un servicio gana y no se vuelve a cambiar, aunque
despues se reentrene el modelo. Asi el historial muestra lo que el sistema dijo en su momento.

Ubicacion: src/historial_emitido.py (import plano desde predict_and_recommend.py)
Solo escribe archivos JSON en docs/data/emitidas/. No toca Supabase ni Apify.
"""

import json
import os
from datetime import date

DIR_EMITIDAS = os.getenv("DIR_EMITIDAS", "docs/data/emitidas")


def _clave(fecha, hora, operador, tipo):
    return f"{fecha}|{hora}|{operador}|{tipo}"


def _ruta(fecha):
    return os.path.join(DIR_EMITIDAS, f"{fecha}.json")


def guardar_emitidas(resultados, modelo, entrenado_en, hoy=None):
    """Anade al archivo de cada fecha los servicios que aun no estaban guardados."""
    hoy = hoy or date.today().isoformat()
    os.makedirs(DIR_EMITIDAS, exist_ok=True)
    nuevos_total = 0
    for r in resultados:
        fecha = r["fecha_viaje"]
        ruta = _ruta(fecha)
        previo = {"fecha_viaje": fecha, "servicios": []}
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                previo = json.load(f)
        existentes = {_clave(fecha, s["hora_salida"], s["operador"], s["tipo_bus"]) for s in previo["servicios"]}
        nuevos = 0
        for s in r["servicios"]:
            k = _clave(fecha, s["hora_salida"], s["operador"], s["tipo_bus"])
            if k in existentes:
                continue
            previo["servicios"].append({
                "hora_salida": s["hora_salida"], "operador": s["operador"], "tipo_bus": s["tipo_bus"],
                "asientos_totales": s["asientos_totales"], "ocupacion_d3": s["ocupacion_d3"],
                "ocupacion_predicha": s["ocupacion_predicha"],
                "emitido_en": hoy, "modelo": modelo, "entrenado_en": entrenado_en,
            })
            nuevos += 1
        if nuevos:
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(previo, f, ensure_ascii=False, indent=2)
        nuevos_total += nuevos
    return nuevos_total


def cargar_emitidas():
    """Devuelve {(fecha, hora, operador, tipo): ocupacion_predicha} con todo lo emitido."""
    out = {}
    if not os.path.isdir(DIR_EMITIDAS):
        return out
    for nombre in os.listdir(DIR_EMITIDAS):
        if not nombre.endswith(".json"):
            continue
        with open(os.path.join(DIR_EMITIDAS, nombre), encoding="utf-8") as f:
            d = json.load(f)
        for s in d.get("servicios", []):
            out[(d["fecha_viaje"], s["hora_salida"], s["operador"], s["tipo_bus"])] = float(s["ocupacion_predicha"])
    return out


if __name__ == "__main__":
    print(f"{len(cargar_emitidas())} servicios emitidos guardados en {DIR_EMITIDAS}")
