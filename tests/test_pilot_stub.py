"""Пилотный режим report-assembler без задеплоенного детектора."""

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest


MODULE_DIR = Path(__file__).resolve().parents[1]


def _load_module(name: str, filename: str):
    sys.path.insert(0, str(MODULE_DIR))
    try:
        spec = importlib.util.spec_from_file_location(name, MODULE_DIR / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


core = _load_module("report_assembler_core_pilot", "_assemble_core.py")
node = _load_module("report_assembler_main_pilot", "main.py")


def _scored_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "query_id": ["trace-middle", "trace-good", "trace-worst"],
            "question": ["вопрос 1", "вопрос 2", "вопрос 3"],
            "answer": ["ответ 1", "ответ 2", "ответ 3"],
            "agent_target": [0.2, 0.9, 0.1],
        }
    )


def _monitoring_result() -> dict:
    def common(test_name, color="green", status="ok"):
        return {
            "test_name": test_name,
            "color": color,
            "status": status,
            "calculated_traffic_lights": {
                "test_light": color,
                "semaphore_title": f"Результат {test_name}: {color}",
            },
        }

    tests = {
        "km_test": {
            **common("km_test"),
            "reason": "КМ в норме",
            "km_name": "target",
            "km_baseline": 0.8,
            "km_monitoring": 0.7,
            "km_delta": 0.125,
            "n_scored": 3,
            "n_valid": 3,
            "invalid_share": 0.0,
            "thresholds": {"green": 0.15, "red": 0.25},
            "min_valid_rows": 1,
        },
        "local_drift": {
            **common("local_drift"),
            "metric_value": 0.8,
            "metric_value_estimate": 0.78,
            "drop_estimate": 0.02,
            "reliability_mean": 0.9,
            "share_uncovered": 0.0,
            "n_oos": 100,
            "n_oot": 100,
            "n_closest": 5,
        },
        "global_drift": {
            **common("global_drift"),
            "reason": "дрифт не обнаружен",
            "metric_value": 0.8,
            "metric_value_estimate": 0.79,
            "estimate_source": "regression",
            "n_selected_features": 2,
            "selected_features": ["f1", "f2"],
            "n_chunks": 10,
        },
        "oos_oot": {
            **common("oos_oot"),
            "reason": "выборки неразличимы",
            "gini_mean": 0.1,
            "gini_std": 0.02,
            "gini_spread_lower": 0.08,
            "gini_spread_upper": 0.12,
            "resampling_iterations": 10,
            "n_oos": 100,
            "n_oot": 100,
        },
    }
    return {
        "schema_version": "monitoring-result/v1",
        "expected_tests": list(tests),
        "missing_tests": [],
        "test_results": tests,
        "color": "green",
        "assessor_accuracy": 0.8,
    }


def test_missing_detector_builds_deterministic_markup_sample():
    report = core.assemble_laim_report(
        scored_data=_scored_data(),
        main_metric="target",
        perv_validation_km={"value": 0.8},
        metadata={"period_to": "2026-07-31"},
        detector_anomalies=None,
        stub_sample_size=2,
    )

    candidates = [
        item for item in report["anomalies"]
        if item["trace_id"].startswith("trace-")
    ]
    assert [item["trace_id"] for item in candidates] == [
        "trace-worst", "trace-middle"
    ]
    assert [item["user_query"] for item in candidates] == ["вопрос 3", "вопрос 1"]
    assert all(item["confidence"] == "" for item in candidates)
    assert all("временной выборки" in item["tech_details"] for item in candidates)
    assert "Детектор аномалий не подключён" in report["general_comment"]
    assert report["timeline"] == [{"date": "2026-07-31", "zone": "gray"}]
    assert report["km_dynamics"]["series"][0]["date"] == "2026-07-31"


def test_explicit_empty_detector_result_is_not_replaced_by_stub():
    report = core.assemble_laim_report(
        scored_data=_scored_data(),
        main_metric="target",
        perv_validation_km={"value": 0.8},
        detector_anomalies=[],
    )

    assert report["anomalies"] == []
    assert report["general_comment"] == ""


def test_stub_fails_when_selected_metric_is_missing():
    with pytest.raises(ValueError, match="agent_unknown"):
        core.assemble_laim_report(
            scored_data=_scored_data(),
            main_metric="unknown",
            perv_validation_km={"value": 0.8},
            detector_anomalies=None,
            strict_stub_sample=True,
        )


def test_connected_malformed_detector_payload_fails_loudly():
    with pytest.raises(ValueError, match="detector_anomalies"):
        node._as_anomaly_list('{"unexpected": []}')


def test_real_ars_test_anomalies_replaces_stub_without_other_changes(tmp_path):
    detector_payload = json.dumps(
        {
            "anomalies": [
                {
                    "_comment": "",
                    "trace_id": "ars-trace-1",
                    "starttime": "2026-07-31T10:00:00Z",
                    "endtime": "2026-07-31T10:00:05Z",
                    "anomaly_type": "dpi",
                    "confidence": 1,
                    "business_description": "ARS detector result",
                    "user_query": "реальный запрос",
                    "agent_response": "реальный ответ",
                    "tech_details": "detector details",
                    "rca_results": "rca details",
                }
            ]
        },
        ensure_ascii=False,
    )

    result = node.main(
        scored_data=_scored_data(),
        metric_selector_res={"main_metric": "target"},
        aggregator_result=_monitoring_result(),
        detector_anomalies=detector_payload,
        output_dir=str(tmp_path),
    )["report_json"]

    assert result["general_comment"] == ""
    assert len(result["anomalies"]) == 5
    assert not any(
        item["trace_id"].startswith("trace-") for item in result["anomalies"]
    )
    assert result["anomalies"][0] == {
        "trace_id": "ars-trace-1",
        "starttime": "2026-07-31T10:00:00Z",
        "endtime": "2026-07-31T10:00:05Z",
        "anomaly_type": "prompt_injection_dpi",
        "confidence": 1,
        "business_description": "ARS detector result",
        "user_query": "реальный запрос",
        "agent_response": "реальный ответ",
        "tech_details": "detector details",
        "rca_results": "rca details",
        "is_anomaly": "",
        "severity": "",
        "comments": "",
    }


def test_main_reads_parquet_path_and_writes_distinct_reports(tmp_path):
    source = tmp_path / "scored.parquet"
    _scored_data().to_parquet(source, index=False)
    kwargs = {
        "scored_data": str(source),
        "metric_selector_res": {"main_metric": "target"},
        "aggregator_result": _monitoring_result(),
        "detector_anomalies": None,
        "output_dir": str(tmp_path),
        "stub_sample_size": 1,
    }

    first = node.main(**kwargs)
    second = node.main(**kwargs)

    assert Path(first["report_path"]).is_file()
    assert Path(second["report_path"]).is_file()
    assert first["report_path"] != second["report_path"]
    candidates = [
        item for item in first["report_json"]["anomalies"]
        if item["trace_id"].startswith("trace-")
    ]
    assert [item["trace_id"] for item in candidates] == ["trace-worst"]


def test_old_aggregator_contract_is_rejected_with_deploy_hint():
    with pytest.raises(ValueError, match="согласованную версию laim-agg"):
        node._as_monitoring_result({"color": "green"})


def test_test_cards_use_machine_results_not_test_description(tmp_path):
    report = node.main(
        scored_data=_scored_data(),
        metric_selector_res={"main_metric": "target"},
        aggregator_result=_monitoring_result(),
        detector_anomalies=[],
        output_dir=str(tmp_path),
    )["report_json"]

    km_card = next(
        item for item in report["anomalies"]
        if item["anomaly_type"] == "quality_degradation"
    )
    details = json.loads(km_card["tech_details"])
    assert details["status"] == "ok"
    assert details["km_baseline"] == 0.8
    assert details["km_monitoring"] == 0.7
