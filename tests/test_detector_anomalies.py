"""Порт detector_anomalies: невалидный вход — ошибка, а не молчаливый пропуск;
текстовые поля от LLM-узла RCA (dict/list) сплющиваются в строку для шаблона ОС."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as assembler  # noqa: E402
from _assemble_core import _normalize_detector_anomaly  # noqa: E402


def test_fenced_or_invalid_json_raises():
    with pytest.raises(ValueError, match="невалидный JSON"):
        assembler._as_anomaly_list('```json\n{"anomalies": []}\n```')


def test_object_without_anomalies_key_raises():
    with pytest.raises(ValueError, match="anomalies"):
        assembler._as_anomaly_list({"result": []})
    with pytest.raises(ValueError, match="anomalies"):
        assembler._as_anomaly_list('{"result": []}')


def test_non_dict_records_raise():
    with pytest.raises(ValueError, match="не-объекты"):
        assembler._as_anomaly_list('{"anomalies": [{"trace_id": "t1"}, "мусор"]}')


def test_valid_shapes_pass_through():
    records = [{"trace_id": "t1", "confidence": 90}]
    assert assembler._as_anomaly_list(records) == records
    assert assembler._as_anomaly_list({"anomalies": records}) == records
    assert assembler._as_anomaly_list('{"anomalies": [{"trace_id": "t1", "confidence": 90}]}') == records
    assert assembler._as_anomaly_list(None) is None


def test_dict_rca_results_is_flattened_to_text():
    out = _normalize_detector_anomaly({
        "trace_id": "t1",
        "rca_results": {"quote_with_error": "22,5%/12 = 0,1875", "correct_value": "0,01875"},
        "tech_details": ["шаг 1", "шаг 2"],
        "business_description": "как есть",
    })

    assert out["rca_results"] == "quote with error: 22,5%/12 = 0,1875\ncorrect value: 0,01875"
    assert out["tech_details"] == "— шаг 1\n— шаг 2"
    assert out["business_description"] == "как есть"
    assert isinstance(out["agent_response"], str)
