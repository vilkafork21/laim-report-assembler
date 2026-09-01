"""
Тесты исчерпывающего маппинга типов аномалий детектора → схема ОС в ассемблере.

Ассемблер — финальный гейт: любой код типа от детектора (атомарный/составной/
неизвестный) обязан стать валидным типом из _OS_ANOMALY_TYPES.
"""
import importlib.util
import os

import pytest

_CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_assemble_core.py")
_spec = importlib.util.spec_from_file_location("_assemble_core", _CORE)
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)


@pytest.mark.parametrize("detector_type, os_type", [
    ("dpi", "prompt_injection_dpi"), ("ipi", "prompt_injection_dpi"),
    ("prompt_injection", "prompt_injection_dpi"), ("pi", "prompt_injection_dpi"),
    ("hallucination", "hallucination"), ("halluc", "hallucination"),
    ("bias", "anomaly"), ("mp", "anomaly"), ("chars", "anomaly"),
    ("loop", "anomaly"), ("foreign", "anomaly"), ("mojibake", "anomaly"),
    ("drift", "anomaly"), ("residual_inflate", "anomaly"),
    ("coupling_break_edge", "anomaly"), ("conditional_shift", "anomaly"),
    ("marginal_break", "anomaly"), ("NonAnomaly", "anomaly"),
    ("anomaly", "anomaly"), ("prompt_injection_dpi", "prompt_injection_dpi"),
    ("DPI", "prompt_injection_dpi"), ("  ", "anomaly"), ("totally_unknown", "anomaly"),
    # составные метки injection.py 'a+b' → самый критичный слот
    ("dpi+drift", "prompt_injection_dpi"), ("bias+hallucination", "hallucination"),
    ("bias+mp", "anomaly"), ("loop+ipi", "prompt_injection_dpi"),
    # валидный тип ОС, переданный напрямую, сохраняется
    ("drift_global", "drift_global"),
])
def test_map_detector_anomaly_type(detector_type, os_type):
    assert core._map_detector_anomaly_type(detector_type) == os_type


def test_invariant_always_valid_os_type():
    for code in list(core._DETECTOR_TYPE_MAP) + ["junk", "", None, "a+b+c", "DPI+Drift", 123]:
        assert core._map_detector_anomaly_type(code) in core._OS_ANOMALY_TYPES


def test_normalize_uses_mapping():
    out = core._normalize_detector_anomaly({"trace_id": "t", "anomaly_type": "dpi", "confidence": 100})
    assert out["anomaly_type"] == "prompt_injection_dpi"
    assert out["anomaly_type"] in core._OS_ANOMALY_TYPES


@pytest.mark.parametrize("raw, expected", [
    (1, 1),       # актуальный ARS: целые проценты
    (84, 84),
    (0.84, 84.0), # legacy: вероятность float 0..1
    (84.5, 84.5),
    ("", ""),
])
def test_detector_confidence_contract(raw, expected):
    assert core._normalize_detector_confidence(raw) == expected


@pytest.mark.parametrize("raw", [-1, 101, float("nan"), True, "84"])
def test_detector_confidence_rejects_invalid_values(raw):
    with pytest.raises(ValueError, match="confidence"):
        core._normalize_detector_confidence(raw)
