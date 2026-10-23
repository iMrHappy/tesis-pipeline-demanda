"""
test_dispatch_fis_v2.py  (v2.1)  -  C6 / T8
Pruebas del sistema difuso v2. Se ejecutan con:  python src/test_dispatch_fis_v2.py   (o con pytest)
No usan Apify ni Supabase.
"""

import itertools

import numpy as np

from dispatch_fis_v2 import DispatchFuzzySystemV2

FIS = DispatchFuzzySystemV2()


def test_ocupacion_alta_sin_feriado_aumenta():
    for ocu in (80, 90, 100):
        assert FIS.recomendar(ocu, -5)["delta_buses"] >= 1


def test_ocupacion_alta_sin_feriado_no_reduce():
    # caso que fallaba en la v1: demanda alta sin feriado devolvia "Reducir"
    assert FIS.recomendar(95, -5)["delta_buses"] > 0


def test_ocupacion_media_sin_feriado_mantiene():
    assert FIS.recomendar(50, -5)["delta_buses"] == 0


def test_ocupacion_baja_sin_feriado_reduce():
    assert FIS.recomendar(10, -5)["delta_buses"] <= -1


def test_nunca_hay_activacion_total_cero():
    for ocu, dias in itertools.product(np.linspace(0, 100, 101), range(-5, 1)):
        assert FIS.recomendar(ocu, dias)["soporte"] > 0


def test_salida_siempre_entre_menos2_y_mas2():
    for ocu, dias in itertools.product(np.linspace(0, 100, 51), range(-5, 3)):
        r = FIS.recomendar(ocu, dias)
        assert -2 <= r["delta_buses"] <= 2 and -2 <= r["delta_continuo"] <= 2


def test_monotonia_respecto_de_la_demanda():
    for dias in (-5, -2, 0):
        valores = [FIS.recomendar(o, dias)["delta_continuo"] for o in np.linspace(0, 100, 101)]
        assert all(b >= a - 1e-9 for a, b in zip(valores, valores[1:])), f"no monotona con dias={dias}"


def test_feriado_cercano_nunca_reduce_la_recomendacion():
    for ocu in np.linspace(0, 100, 21):
        assert FIS.recomendar(ocu, 0)["delta_continuo"] >= FIS.recomendar(ocu, -5)["delta_continuo"] - 1e-9


def test_alta_con_feriado_es_urgente():
    assert FIS.recomendar(95, 0)["delta_buses"] == 2


def test_feriado_sube_un_nivel_cada_categoria():
    assert FIS.recomendar(10, 0)["delta_buses"] == 0    # baja + feriado -> mantener
    assert FIS.recomendar(50, 0)["delta_buses"] == 1    # media + feriado -> aumentar
    assert FIS.recomendar(95, 0)["delta_buses"] == 2    # alta + feriado -> urgente


def test_soporte_minimo_razonable():
    # con la base completa el soporte minimo nunca queda cerca de cero
    soportes = [FIS.recomendar(o, d)["soporte"] for o in np.linspace(0, 100, 101) for d in range(-5, 1)]
    assert min(soportes) >= 0.25


def test_anclas_invalidas_se_rechazan():
    try:
        DispatchFuzzySystemV2(60, 50, 75)
    except ValueError:
        return
    raise AssertionError("debio rechazar anclas desordenadas")


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for prueba in pruebas:
        prueba()
        print(f"OK  {prueba.__name__}")
    print(f"\n{len(pruebas)} pruebas pasaron.")