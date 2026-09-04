"""
Нода laim-report-assembler.

Принимает записи детектора аномалий (порт `anomalies`), опциональные
метаданные пилота и итог автомониторинга (`monitoring_result`,
monitoring-result/v3 из laim-agg), собирает состояние отчёта (логика — в
`_assemble_core.py`), встраивает его в HTML-шаблон обратной связи
`laim_feedback_template.html` и вставляет раздел автомониторинга
(`_monitoring_section.py`).
Единственный выход — готовый HTML для передачи в Data Saver.

Входы принимаются best-effort: расхождение контракта не роняет ноду —
непригодные данные пропускаются с logger.warning, отчёт собирается из того,
что удалось разобрать.
"""

import json
import logging
from pathlib import Path
from typing import Any

from _assemble_core import assemble_laim_report
from _monitoring_section import render_monitoring_section

logger = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).resolve().parent / "laim_feedback_template.html"
_EMBED_MARKER = '<script id="laim-embedded-state" type="application/json"></script>'
_SECTION_MARKER = "<!-- laim-monitoring-section -->"
_MONITORING_SCHEMA = "monitoring-result/v3"


def _as_anomaly_list(value: Any) -> list[dict]:
    """Вход `anomalies` → list[dict] best-effort.

    Принимает JSON-строку ARS test_anomalies {"anomalies":[...]}, dict с этим
    ключом и готовый список; любой непригодный вход → [] с warning.
    """
    if value is None:
        return []
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            logger.warning("anomalies: невалидный JSON — записи пропущены")
            return []
    if isinstance(value, dict):
        value = value.get("anomalies", [])
    if not isinstance(value, list):
        logger.warning(
            "anomalies: ожидался список, получен %s — записи пропущены",
            type(value).__name__,
        )
        return []
    records = [item for item in value if isinstance(item, dict)]
    if len(records) != len(value):
        logger.warning(
            "anomalies: пропущено %d записей не-объектов", len(value) - len(records)
        )
    return records


def _as_metadata(value: Any) -> dict | None:
    """Вход `metadata` → dict best-effort; непригодный вход → None с warning."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            logger.warning("metadata: невалидный JSON — шапка отчёта останется пустой")
            return None
    if not isinstance(value, dict):
        logger.warning(
            "metadata: ожидался объект, получен %s — шапка отчёта останется пустой",
            type(value).__name__,
        )
        return None
    return value


def _as_monitoring_result(value: Any) -> dict | None:
    """Вход `monitoring_result` → dict monitoring-result/v3; иной вход → None с warning."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            logger.warning("monitoring_result: невалидный JSON — раздел автомониторинга пропущен")
            return None
    if not isinstance(value, dict):
        logger.warning(
            "monitoring_result: ожидался объект, получен %s — раздел автомониторинга пропущен",
            type(value).__name__,
        )
        return None
    if value.get("schema_version") != _MONITORING_SCHEMA:
        logger.warning(
            "monitoring_result: schema_version=%r, ожидается %s — раздел автомониторинга пропущен",
            value.get("schema_version"), _MONITORING_SCHEMA,
        )
        return None
    return value


def _fill_template(report: dict, monitoring_result: dict | None) -> str:
    """Встраивает состояние отчёта в контейнер laim-embedded-state шаблона
    и раздел автомониторинга на место маркера laim-monitoring-section.

    '<' экранируется как '\\u003c' (как в saveHtml самого шаблона), чтобы
    '</script>' внутри данных не оборвал контейнер; JSON.parse вернёт обратно.
    """
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    if _EMBED_MARKER not in template:
        raise ValueError(
            "laim_feedback_template.html: контейнер laim-embedded-state не найден"
        )
    if _SECTION_MARKER not in template:
        raise ValueError(
            "laim_feedback_template.html: маркер laim-monitoring-section не найден"
        )
    section = render_monitoring_section(monitoring_result) if monitoring_result else ""
    template = template.replace(_SECTION_MARKER, section, 1)
    # default=str: несериализуемое значение из входов не должно ронять сборку
    state_json = json.dumps(report, ensure_ascii=False, default=str).replace("<", "\\u003c")
    filled = _EMBED_MARKER.replace("</script>", state_json + "</script>")
    return template.replace(_EMBED_MARKER, filled, 1)


def main(
    anomalies: list | str | dict | None = None,
    metadata: dict | None = None,
    monitoring_result: dict | str | None = None,
):
    """Собирает готовый HTML отчёта обратной связи для Data Saver."""
    report = assemble_laim_report(
        anomalies=_as_anomaly_list(anomalies),
        metadata=_as_metadata(metadata),
    )
    return {"report_html": _fill_template(report, _as_monitoring_result(monitoring_result))}
