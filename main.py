"""
Omega-нода laim-report-assembler.

Собирает состояние отчёта из aggregator_result, all_results четырёх тестов
и detector_anomalies (логика — в `_assemble_core.py`) и встраивает его
в HTML-шаблон обратной связи `laim_feedback_template.html`. Единственный
выход — готовый HTML для передачи в Data Saver.

Входы принимаются best-effort: расхождение контракта не роняет ноду —
непригодные данные пропускаются с logger.warning, отчёт собирается из того,
что удалось разобрать (недостающее — серым/пустым).
"""

import json
import logging
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import Any

from _assemble_core import assemble_laim_report

logger = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).resolve().parent / "laim_feedback_template.html"
_EMBED_MARKER = '<script id="laim-embedded-state" type="application/json"></script>'


def _unwrap(value: Any, port: str) -> dict:
    """Любой вход порта → dict best-effort.

    JSON-строка разбирается, обёртка {'all_results': {...}} снимается;
    всё непригодное превращается в {} с warning, а не в исключение.
    """
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            logger.warning("%s: невалидный JSON — вход пропущен", port)
            return {}
    if not isinstance(value, dict):
        if value is not None:
            logger.warning(
                "%s: ожидался объект, получен %s — вход пропущен",
                port, type(value).__name__,
            )
        return {}
    inner = value.get("all_results", value)
    return inner if isinstance(inner, dict) else value


def _accuracy(value: Any) -> float | None:
    """assessor_accuracy → число 0..1; непригодное значение → None с warning
    (в шаблоне None рендерится как «—», а не как ложный 0.00)."""
    if isinstance(value, bool) or not isinstance(value, Real):
        if value is not None:
            logger.warning("assessor_accuracy: не число (%r) — в отчёте будет пусто", value)
        return None
    numeric = float(value)
    if not isfinite(numeric):
        logger.warning(
            "assessor_accuracy: не конечное число (%r) — в отчёте будет пусто", value
        )
        return None
    return min(max(numeric, 0.0), 1.0)


def _as_anomaly_list(value: Any) -> list[dict] | None:
    """Вход detector_anomalies → list[dict] best-effort.

    None означает «детектор не подключён» (в отчёте появится пояснение);
    любой подключённый, но непригодный вход → [] с warning.
    """
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            logger.warning("detector_anomalies: невалидный JSON — записи пропущены")
            return []
    if isinstance(value, dict):
        value = value.get("anomalies", [])
    if not isinstance(value, list):
        logger.warning(
            "detector_anomalies: ожидался список, получен %s — записи пропущены",
            type(value).__name__,
        )
        return []
    records = [item for item in value if isinstance(item, dict)]
    if len(records) != len(value):
        logger.warning(
            "detector_anomalies: пропущено %d записей не-объектов",
            len(value) - len(records),
        )
    return records


def _fill_template(report: dict) -> str:
    """Встраивает состояние отчёта в контейнер laim-embedded-state шаблона.

    '<' экранируется как '\\u003c' (как в saveHtml самого шаблона), чтобы
    '</script>' внутри данных не оборвал контейнер; JSON.parse вернёт обратно.
    """
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    if _EMBED_MARKER not in template:
        raise ValueError(
            "laim_feedback_template.html: контейнер laim-embedded-state не найден"
        )
    # default=str: несериализуемое значение из входов не должно ронять сборку
    state_json = json.dumps(report, ensure_ascii=False, default=str).replace("<", "\\u003c")
    filled = _EMBED_MARKER.replace("</script>", state_json + "</script>")
    return template.replace(_EMBED_MARKER, filled, 1)


def main(
    aggregator_result: dict | None = None,
    km_test_result: dict | None = None,
    local_drift_result: dict | None = None,
    global_drift_result: dict | None = None,
    oos_oot_result: dict | None = None,
    assessor_accuracy: float | None = None,
    metadata: dict | None = None,
    detector_anomalies: list | str | None = None,
):
    """Собирает готовый HTML отчёта обратной связи для Data Saver."""
    aggregator_payload = _unwrap(aggregator_result, "aggregator_result")
    # точность — прямой порт acc_auto ассессора; aggregator_result — fallback
    accuracy = _accuracy(assessor_accuracy)
    if accuracy is None:
        accuracy = _accuracy(aggregator_payload.get("assessor_accuracy"))
    km_all_results = _unwrap(km_test_result, "km_test_result")
    local_all_results = _unwrap(local_drift_result, "local_drift_result")
    global_all_results = _unwrap(global_drift_result, "global_drift_result")
    oos_all_results = _unwrap(oos_oot_result, "oos_oot_result")

    # ARS test_anomalies приходит JSON-строкой {"anomalies":[...]} — разворачиваем в list
    detector_anomalies = _as_anomaly_list(detector_anomalies)

    report = assemble_laim_report(
        assessor_accuracy=accuracy,
        km_result={"all_results": km_all_results},
        local_drift_result={"all_results": local_all_results},
        global_drift_result={"all_results": global_all_results},
        oos_oot_result={"all_results": oos_all_results},
        aggregator_result=aggregator_payload,
        perv_validation_km={
            "name": km_all_results.get("km_name"),
            "value": km_all_results.get("km_baseline"),
        },
        metadata=metadata if isinstance(metadata, dict) else None,
        detector_anomalies=detector_anomalies,
    )

    return {"report_html": _fill_template(report)}
