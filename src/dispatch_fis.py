"""
dispatch_fis.py
Sistema de Inferencia Difusa (FIS) tipo Mamdani para la recomendacion
de despacho de unidades de transporte interprovincial.

Este modulo NO reemplaza al modelo XGBoost. Se ejecuta DESPUES de que
XGBoost genera la prediccion numerica de demanda. El FIS traduce esa
prediccion, junto con variables de contexto (proximidad a feriado y
condicion climatica), en una recomendacion operativa interpretable
para el area de despacho logistico.

Componentes implementados:
    1. Fuzzificacion       -> membership.py (trimf)
    2. Variables de entrada -> demanda_predicha, proximidad_feriado, condicion_climatica
    3. Variable de salida   -> recomendacion_despacho (unidades adicionales)
    4. Base de reglas       -> metodo _evaluar_reglas()
    5. Motor de inferencia  -> Mamdani (operador AND = min, agregacion = max)
    6. Defuzzificacion      -> metodo del centroide

Ubicacion: src/dispatch_fis.py
Ejecucion: python src/dispatch_fis.py
"""

import numpy as np
from membership import trimf, interp_membership


class DispatchFuzzySystem:
    """
    Sistema de inferencia difusa para recomendar el numero de unidades
    adicionales a despachar en una ruta y fecha determinadas.
    """

    def __init__(self):
        # ---------------------------------------------------
        # Universos de discurso
        # ---------------------------------------------------
        self.u_demanda = np.arange(0, 101, 1)     # % de ocupacion o pasajeros normalizados 0-100
        self.u_feriado = np.arange(-5, 6, 1)      # dias respecto al feriado (negativo = dias antes)
        self.u_clima = np.arange(0, 101, 1)       # 0 = clima muy adverso, 100 = clima favorable
        self.u_salida = np.arange(0, 21, 1)       # 0 a 20 unidades adicionales recomendadas

        # ---------------------------------------------------
        # Fuzzificacion de entradas (funciones de pertenencia)
        # ---------------------------------------------------
        self.demanda_baja  = trimf(self.u_demanda, [0, 0, 45])
        self.demanda_media = trimf(self.u_demanda, [25, 50, 75])
        self.demanda_alta  = trimf(self.u_demanda, [55, 100, 100])

        self.feriado_lejos      = trimf(self.u_feriado, [-5, -5, -2])
        self.feriado_cercano     = trimf(self.u_feriado, [-3, -1, 0])
        self.feriado_muy_cercano = trimf(self.u_feriado, [-1, 0, 1])

        self.clima_adverso   = trimf(self.u_clima, [0, 0, 50])
        self.clima_favorable = trimf(self.u_clima, [40, 100, 100])

        # ---------------------------------------------------
        # Fuzzificacion de la salida
        # ---------------------------------------------------
        self.salida_reducir          = trimf(self.u_salida, [0, 0, 6])
        self.salida_mantener         = trimf(self.u_salida, [4, 9, 13])
        self.salida_aumentar         = trimf(self.u_salida, [11, 15, 19])
        self.salida_aumentar_urgente = trimf(self.u_salida, [16, 20, 20])

    # ---------------------------------------------------
    # Fuzzificacion puntual
    # ---------------------------------------------------
    def _fuzzificar(self, valor, universo, mf):
        return interp_membership(universo, mf, valor)

    # ---------------------------------------------------
    # Base de reglas (Mamdani, operador AND = minimo)
    # ---------------------------------------------------
    def _evaluar_reglas(self, demanda_val, feriado_val, clima_val):
        d_baja  = self._fuzzificar(demanda_val, self.u_demanda, self.demanda_baja)
        d_media = self._fuzzificar(demanda_val, self.u_demanda, self.demanda_media)
        d_alta  = self._fuzzificar(demanda_val, self.u_demanda, self.demanda_alta)

        f_lejos       = self._fuzzificar(feriado_val, self.u_feriado, self.feriado_lejos)
        f_cercano     = self._fuzzificar(feriado_val, self.u_feriado, self.feriado_cercano)
        f_muy_cercano = self._fuzzificar(feriado_val, self.u_feriado, self.feriado_muy_cercano)

        c_adverso   = self._fuzzificar(clima_val, self.u_clima, self.clima_adverso)
        c_favorable = self._fuzzificar(clima_val, self.u_clima, self.clima_favorable)

        reglas = {
            # Regla 1: demanda alta + feriado muy cercano -> aumentar urgente
            "R1_aumentar_urgente": min(d_alta, f_muy_cercano),
            # Regla 2: demanda alta + clima favorable -> aumentar
            "R2_aumentar": min(d_alta, c_favorable),
            # Regla 3: demanda alta + feriado cercano -> aumentar
            "R3_aumentar": min(d_alta, f_cercano),
            # Regla 4: demanda media + lejos de feriado -> mantener
            "R4_mantener": min(d_media, f_lejos),
            # Regla 5: demanda media (regla general) -> mantener
            "R5_mantener": d_media,
            # Regla 6: demanda baja + clima adverso -> reducir
            "R6_reducir": min(d_baja, c_adverso),
            # Regla 7: demanda baja (regla general) -> reducir
            "R7_reducir": d_baja,
        }
        return reglas

    # ---------------------------------------------------
    # Inferencia + Defuzzificacion (centroide)
    # ---------------------------------------------------
    def recomendar(self, demanda_predicha, dias_a_feriado, indice_clima):
        """
        Args:
            demanda_predicha: valor 0-100 (ocupacion % o demanda normalizada,
                              proveniente de la salida del modelo XGBoost).
            dias_a_feriado: entero -5 a 5 (0 = es feriado, negativo = dias antes).
            indice_clima: valor 0-100 (0 = clima muy adverso, 100 = clima favorable).

        Returns:
            dict con:
                - unidades_recomendadas (float): salida defuzzificada (centroide)
                - etiqueta (str): categoria interpretativa de la recomendacion
                - activaciones (dict): grado de activacion de cada regla (trazabilidad)
        """
        reglas = self._evaluar_reglas(demanda_predicha, dias_a_feriado, indice_clima)

        agregado = np.zeros_like(self.u_salida, dtype=float)
        agregado = np.maximum(agregado, np.minimum(reglas["R1_aumentar_urgente"], self.salida_aumentar_urgente))
        agregado = np.maximum(agregado, np.minimum(reglas["R2_aumentar"], self.salida_aumentar))
        agregado = np.maximum(agregado, np.minimum(reglas["R3_aumentar"], self.salida_aumentar))
        agregado = np.maximum(agregado, np.minimum(reglas["R4_mantener"], self.salida_mantener))
        agregado = np.maximum(agregado, np.minimum(reglas["R5_mantener"], self.salida_mantener))
        agregado = np.maximum(agregado, np.minimum(reglas["R6_reducir"], self.salida_reducir))
        agregado = np.maximum(agregado, np.minimum(reglas["R7_reducir"], self.salida_reducir))

        if agregado.sum() == 0:
            unidades = 0.0
        else:
            unidades = float(np.sum(self.u_salida * agregado) / np.sum(agregado))

        if unidades <= 6:
            etiqueta = "Reducir unidades"
        elif unidades <= 13:
            etiqueta = "Mantener programacion"
        elif unidades <= 17:
            etiqueta = "Aumentar unidades"
        else:
            etiqueta = "Aumentar unidades (urgente)"

        return {
            "unidades_recomendadas": round(unidades, 2),
            "etiqueta": etiqueta,
            "activaciones": reglas,
        }


if __name__ == "__main__":
    fis = DispatchFuzzySystem()

    casos_prueba = [
        {"demanda_predicha": 82, "dias_a_feriado": 0, "indice_clima": 90},
        {"demanda_predicha": 20, "dias_a_feriado": -5, "indice_clima": 20},
        {"demanda_predicha": 50, "dias_a_feriado": -4, "indice_clima": 60},
        {"demanda_predicha": 75, "dias_a_feriado": -1, "indice_clima": 85},
    ]

    for caso in casos_prueba:
        resultado = fis.recomendar(**caso)
        print(f"Entrada: {caso}")
        print(f"  -> Unidades recomendadas: {resultado['unidades_recomendadas']}")
        print(f"  -> Recomendacion: {resultado['etiqueta']}")
        print()