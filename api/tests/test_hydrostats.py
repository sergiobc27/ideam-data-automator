import math
import pytest
from app import hydrostats as hs


def test_l_moments_pocos_datos_none():
    assert hs.l_moments([1, 2, 3]) is None  # n<4


def test_l_moments_l1_es_media():
    lm = hs.l_moments([10, 20, 30, 40, 50])
    assert lm is not None
    l1, l2, t3, t4 = lm
    assert abs(l1 - 30.0) < 1e-9  # l1 = media


def test_l_moments_serie_simetrica_t3_cero():
    # Serie perfectamente simétrica -> L-asimetría ~ 0.
    lm = hs.l_moments([10, 20, 30, 40, 50])
    _l1, _l2, t3, _t4 = lm
    assert abs(t3) < 1e-9


def test_l_moments_l2_positivo():
    lm = hs.l_moments([12, 18, 25, 31, 40, 22, 28])
    assert lm is not None
    assert lm[1] > 0
