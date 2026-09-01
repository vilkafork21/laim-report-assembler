"""Тесты сборки готового HTML-отчёта в формате laim_feedback_template.

Нода принимает записи детектора аномалий портом `anomalies` (+ опциональный
`metadata`) и отдаёт единственный выход report_html: шаблон обратной связи
со встроенным состоянием в контейнере laim-embedded-state.
"""

import importlib.util
import json
import sys
from pathlib import Path

NODE = Path(__file__).resolve().parents[1]


def _load_main():
    sys.path.insert(0, str(NODE))
    try:
        spec = importlib.util.spec_from_file_location("report_assembler", NODE / "main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


node = _load_main()

EMBED_OPEN = '<script id="laim-embedded-state" type="application/json">'


def _anomaly(**overrides):
    record = {
        "trace_id": "trace-1",
        "starttime": "2026-08-20T10:00:00Z",
        "endtime": "2026-08-20T10:00:05Z",
        "anomaly_type": "dpi",
        "confidence": 90,
        "business_description": "инъекция",
        "user_query": "вопрос",
        "agent_response": "ответ",
        "tech_details": "",
        "rca_results": "",
    }
    record.update(overrides)
    return record


def _embedded_state(html: str) -> dict:
    start = html.index(EMBED_OPEN) + len(EMBED_OPEN)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


def test_single_output_is_filled_template():
    result = node.main(anomalies=json.dumps({"anomalies": [_anomaly()]}))

    assert set(result) == {"report_html"}
    html = result["report_html"]
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "hydrateFromEmbeddedState" in html

    state = _embedded_state(html)
    assert set(state) == {"schema_version", "metadata", "general_comment", "anomalies"}
    assert state["anomalies"][0]["trace_id"] == "trace-1"


def test_report_contains_only_detector_anomalies():
    result = node.main(anomalies=[_anomaly(), _anomaly(trace_id="trace-2", anomaly_type="halluc")])

    state = _embedded_state(result["report_html"])
    assert [a["anomaly_type"] for a in state["anomalies"]] == [
        "prompt_injection_dpi", "hallucination",
    ]


def test_detector_types_map_to_template_slots():
    types = ["ipi", "bias", "mp", "mojibake", "", "dpi+drift"]
    result = node.main(anomalies=[_anomaly(anomaly_type=t) for t in types])

    state = _embedded_state(result["report_html"])
    assert [a["anomaly_type"] for a in state["anomalies"]] == [
        "prompt_injection_ipi", "bias", "memory_poisoning",
        "anomaly", "anomaly", "prompt_injection_dpi",
    ]


def test_confidence_is_percent_scale():
    result = node.main(anomalies=[
        _anomaly(confidence=90),      # ARS: целый процент
        _anomaly(confidence=0.9),     # legacy: вероятность
        _anomaly(confidence="нет"),   # мусор → пусто, а не ложный 0
    ])

    state = _embedded_state(result["report_html"])
    assert [a["confidence"] for a in state["anomalies"]] == [90, 90.0, ""]


def test_structured_rca_is_flattened_to_text():
    result = node.main(anomalies=[
        _anomaly(rca_results={"quote": "22,5%/12", "correct_value": "0,01875"})
    ])

    state = _embedded_state(result["report_html"])
    assert state["anomalies"][0]["rca_results"] == "quote: 22,5%/12\ncorrect value: 0,01875"


def test_empty_detector_input_yields_report_with_note():
    result = node.main(anomalies=json.dumps({"anomalies": []}))

    state = _embedded_state(result["report_html"])
    assert state["anomalies"] == []
    assert "не выявил аномалий" in state["general_comment"]


def test_embedded_json_escapes_closing_tag():
    result = node.main(anomalies=[_anomaly(agent_response="ответ со </script> внутри")])

    state = _embedded_state(result["report_html"])
    assert state["anomalies"][0]["agent_response"] == "ответ со </script> внутри"


def test_metadata_reaches_embedded_state():
    result = node.main(
        anomalies=[_anomaly()],
        metadata={"agent_id": "agent-1", "agent_name": "Агент"},
    )

    state = _embedded_state(result["report_html"])
    assert state["metadata"]["agent_id"] == "agent-1"
    assert state["metadata"]["agent_name"] == "Агент"
    assert state["metadata"]["pilot_stage"] == "Pilot"


def test_garbage_inputs_do_not_crash_the_node():
    # цель — отчёт без падений: любой мусор на входах даёт HTML с деградацией
    result = node.main(anomalies="это не json {", metadata="не объект")

    state = _embedded_state(result["report_html"])
    assert state["anomalies"] == []
    assert state["metadata"]["agent_id"] == ""


def test_non_object_records_are_skipped():
    result = node.main(anomalies={"anomalies": [_anomaly(), "мусор", 42]})

    state = _embedded_state(result["report_html"])
    assert len(state["anomalies"]) == 1
