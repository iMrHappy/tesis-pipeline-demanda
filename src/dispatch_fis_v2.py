"""
dispatch_fis_v2.py  (v2.1)  -  sistema difuso v2 para OE2
Sistema de inferencia difusa tipo Mamdani que recomienda el CAMBIO de buses (delta) sobre lo programado,
en un grupo (operador + tipo de servicio) y una fecha.

Entradas:
  - ocupacion_pct: ocupacion prevista del grupo (%), ponderada por asientos.
  - dias_a_feriado: 0 = es feriado; negativo = dias que faltan para el proximo feriado (-5 = lejos).
Salida: delta de buses en [-2, +2]. Se devuelve el valor continuo (centroide, para trazabilidad) y el
        entero redondeado (la decision). Sin clima: el clima corresponde al modelo de ML.

Diferencias con la v1: base de reglas completa (nunca hay activacion cero), conjuntos de salida
simetricos en buses, y conjuntos de demanda definidos por tres anclas (P25, P50, P75).

Las funciones de pertenencia de la demanda forman una particion (suman 1 en todo el rango):
  baja  = trapecio [0, 0, P25, P50]      media = triangulo [P25, P50, P75]      alta = trapecio [P50, P75, 100, 100]

Base de reglas (cada nivel de demanda tiene una regla para "feriado lejos" y otra para "feriado cerca"):
  baja  y feriado lejos  -> reducir      baja  y feriado cerca -> mantener
  media y feriado lejos  -> mantener     media y feriado cerca -> aumentar
  alta  y feriado lejos  -> aumentar     alta  y feriado cerca -> urgente
  con "feriado lejos" = 1 - "feriado cerca". Nota de diseno: si las reglas sin feriado no excluyeran el
  feriado cercano, "alta -> aumentar" se activaria a la vez que "alta y feriado -> urgente" y, con
  agregacion por maximo y centroide, la salida quedaria en ~+1.2 y nunca llegaria a +2.

Ubicacion: src/dispatch_fis_v2.py   (autonomo: solo NumPy)
"""

import numpy as np

DELTA_MIN, DELTA_MAX = -2, 2
PERCENTILES_POR_DEFECTO = (25.0, 50.0, 75.0)
ETIQUETAS = {-2: "Reducir (fuerte)", -1: "Reducir", 0: "Mantener", 1: "Aumentar", 2: "Aumentar (urgente)"}


def trapecio(x, a, b, c, d):
    """Pertenencia trapezoidal; con a==b (o c==d) el borde es un hombro vertical."""
    x = np.asarray(x, dtype=float)
    subida = np.where(b > a, (x - a) / (b - a + 1e-12), 1.0)
    bajada = np.where(d > c, (d - x) / (d - c + 1e-12), 1.0)
    y = np.minimum(np.minimum(subida, 1.0), np.minimum(bajada, 1.0))
    y = np.where((x < a) | (x > d), 0.0, y)
    y = np.where((x >= b) & (x <= c), 1.0, y)  # meseta
    return np.clip(y, 0.0, 1.0)


def triangulo(x, a, b, c):
    return trapecio(x, a, b, b, c)


class DispatchFuzzySystemV2:
    def __init__(self, p25=PERCENTILES_POR_DEFECTO[0], p50=PERCENTILES_POR_DEFECTO[1],
                 p75=PERCENTILES_POR_DEFECTO[2], paso=0.01):
        if not (0 < p25 < p50 < p75 < 100):
            raise ValueError(f"Anclas invalidas: se exige 0 < P25 < P50 < P75 < 100 (recibido {p25}, {p50}, {p75})")
        self.p25, self.p50, self.p75 = float(p25), float(p50), float(p75)
        self.u = np.arange(DELTA_MIN, DELTA_MAX + paso / 2, paso)
        self.salida = {
            "reducir": triangulo(self.u, -2, -1, 0),
            "mantener": triangulo(self.u, -1, 0, 1),
            "aumentar": triangulo(self.u, 0, 1, 2),
            "urgente": triangulo(self.u, 1, 2, 2),
        }

    def demanda(self, x):
        x = float(np.clip(x, 0.0, 100.0))
        return {
            "baja": float(trapecio(x, 0, 0, self.p25, self.p50)),
            "media": float(triangulo(x, self.p25, self.p50, self.p75)),
            "alta": float(trapecio(x, self.p50, self.p75, 100, 100)),
        }

    @staticmethod
    def feriado_cercano(d):
        """Triangulo [-4, 0, 0]: 1 el dia del feriado, 0 a 4 o mas dias antes (= 1 - |d|/4)."""
        d = float(d)
        if d > 0:
            return 0.0
        return float(triangulo(max(d, -5.0), -4, 0, 0))

    def reglas(self, ocupacion_pct, dias_a_feriado):
        dm = self.demanda(ocupacion_pct)
        cerca = self.feriado_cercano(dias_a_feriado)
        lejos = 1.0 - cerca
        return {
            "R1_baja_lejos_reducir": (min(dm["baja"], lejos), "reducir"),
            "R2_media_lejos_mantener": (min(dm["media"], lejos), "mantener"),
            "R3_alta_lejos_aumentar": (min(dm["alta"], lejos), "aumentar"),
            "R4_baja_feriado_mantener": (min(dm["baja"], cerca), "mantener"),
            "R5_media_feriado_aumentar": (min(dm["media"], cerca), "aumentar"),
            "R6_alta_feriado_urgente": (min(dm["alta"], cerca), "urgente"),
        }

    def recomendar(self, ocupacion_pct, dias_a_feriado):
        reglas = self.reglas(ocupacion_pct, dias_a_feriado)
        agregado = np.zeros_like(self.u)
        for activacion, conjunto in reglas.values():
            agregado = np.maximum(agregado, np.minimum(activacion, self.salida[conjunto]))
        total = agregado.sum()
        continuo = float(np.sum(self.u * agregado) / total) if total > 0 else 0.0
        delta = int(np.clip(np.floor(continuo + 0.5), DELTA_MIN, DELTA_MAX))
        activaciones = {k: round(float(v[0]), 4) for k, v in reglas.items()}
        return {
            "delta_buses": delta,
            "delta_continuo": round(continuo, 3),
            "etiqueta": ETIQUETAS[delta],
            "activaciones": activaciones,
            "soporte": round(max(activaciones.values()), 4),
        }


if __name__ == "__main__":
    fis = DispatchFuzzySystemV2()
    for ocu, dias in [(20, -5), (50, -5), (90, -5), (20, 0), (50, 0), (90, 0), (90, -2)]:
        r = fis.recomendar(ocu, dias)
        print(f"ocupacion {ocu:>3}% | dias a feriado {dias:>2} -> delta {r['delta_buses']:+d} "
              f"(continuo {r['delta_continuo']:+.2f}) {r['etiqueta']}")