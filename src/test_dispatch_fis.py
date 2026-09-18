"""
test_dispatch_fis.py
Pruebas unitarias basicas para el Sistema de Inferencia Difusa (FIS)
de recomendacion de despacho.

Ubicacion: src/test_dispatch_fis.py
Ejecucion: pytest src/test_dispatch_fis.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from dispatch_fis import DispatchFuzzySystem


@pytest.fixture
def fis():
    return DispatchFuzzySystem()


def test_demanda_alta_feriado_cercano_recomienda_aumentar(fis):
    resultado = fis.recomendar(demanda_predicha=90, dias_a_feriado=0, indice_clima=90)
    assert resultado["unidades_recomendadas"] > 10
    assert "Aumentar" in resultado["etiqueta"]


def test_demanda_baja_clima_adverso_recomienda_reducir(fis):
    resultado = fis.recomendar(demanda_predicha=10, dias_a_feriado=-5, indice_clima=10)
    assert resultado["unidades_recomendadas"] < 6
    assert resultado["etiqueta"] == "Reducir unidades"


def test_demanda_media_lejos_feriado_recomienda_mantener(fis):
    resultado = fis.recomendar(demanda_predicha=50, dias_a_feriado=-5, indice_clima=50)
    assert 4 <= resultado["unidades_recomendadas"] <= 13


def test_salida_siempre_en_rango_valido(fis):
    for demanda in [0, 25, 50, 75, 100]:
        for feriado in [-5, -2, 0, 2, 5]:
            for clima in [0, 50, 100]:
                resultado = fis.recomendar(demanda, feriado, clima)
                assert 0 <= resultado["unidades_recomendadas"] <= 20