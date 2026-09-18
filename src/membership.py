"""
membership.py
Funciones de pertenencia (membership functions) para el Sistema de
Inferencia Difusa (FIS) del proyecto de tesis.

Implementadas desde cero con NumPy para no depender de librerias
externas (scikit-fuzzy) y poder explicar cada paso matematico
en la sustentacion.

Ubicacion: src/membership.py
"""

import numpy as np


def trimf(x, params):
    """
    Funcion de pertenencia triangular.

    Args:
        x: array de valores del universo de discurso.
        params: lista [a, b, c] con los vertices del triangulo.
                a = inicio (pertenencia 0)
                b = pico (pertenencia 1)
                c = fin (pertenencia 0)

    Returns:
        array con el grado de pertenencia para cada valor de x.
    """
    a, b, c = params
    x = np.asarray(x, dtype=float)
    left = (x - a) / (b - a) if b != a else np.ones_like(x)
    right = (c - x) / (c - b) if c != b else np.ones_like(x)
    y = np.clip(np.minimum(left, right), 0, 1)
    y = np.where((x < a) | (x > c), 0, y)
    return y


def trapmf(x, params):
    """
    Funcion de pertenencia trapezoidal.

    Args:
        x: array de valores del universo de discurso.
        params: lista [a, b, c, d] con los vertices del trapecio.

    Returns:
        array con el grado de pertenencia para cada valor de x.
    """
    a, b, c, d = params
    x = np.asarray(x, dtype=float)
    left = (x - a) / (b - a) if b != a else np.ones_like(x)
    right = (d - x) / (d - c) if d != c else np.ones_like(x)
    y = np.clip(np.minimum(np.minimum(left, right), 1), 0, 1)
    y = np.where((x < a) | (x > d), 0, y)
    return y


def interp_membership(universe, mf_values, x_value):
    """
    Interpola el grado de pertenencia para un valor puntual x_value,
    dado un universo de discurso discretizado y su funcion de
    pertenencia evaluada en ese universo.
    """
    return float(np.interp(x_value, universe, mf_values))