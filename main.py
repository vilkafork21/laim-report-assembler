"""
Нода laim-report-assembler.

Принимает записи детектора аномалий (порт `anomalies`) и опциональные
метаданные пилота, собирает состояние отчёта (логика — в `_assemble_core.py`)
и встраивает его в HTML-шаблон обратной связи `laim_feedback_template.html`.
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

logger = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).resolve().parent / "laim_feedback_template.html"
_EMBED_MARKER = '<script id="laim-embedded-state" type="application/json"></script>'


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
    anomalies: list | str | dict | None = None,
    metadata: dict | None = None,
):
    """Собирает готовый HTML отчёта обратной связи для Data Saver."""
    report = assemble_laim_report(
        anomalies=_as_anomaly_list(anomalies),
        metadata=_as_metadata(metadata),
    )
    return {"report_html": _fill_template(report)}
