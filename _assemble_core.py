"""
Сборка состояния отчёта обратной связи LAIM из записей детектора аномалий.

Этот файл — единственный источник логики. Лежит внутри модуля
`laim-report-assembler`, чтобы платформа Omega видела его рядом с `main.py`.
Итоговое состояние встраивает в HTML-шаблон `main.py`.
"""

from __future__ import annotations

import logging
from datetime import date
from math import isfinite
from numbers import Integral, Real
from typing import Any


_ANOMALY_SCHEMA = [
    "trace_id", "starttime", "endtime", "anomaly_type", "confidence",
    "business_description", "user_query", "agent_response", "tech_details", "rca_results",
]

# Типы аномалий, которые умеет показывать шаблон обратной связи.
_OS_ANOMALY_TYPES = {
    "hallucination", "bias", "prompt_injection_dpi", "prompt_injection_ipi",
    "memory_poisoning",
    "anomaly",   # generic: аномалия детектора без классификации типа
}
# Дефолт для типонеразмеченных аномалий детектора (end2end s1+s2 детектит по
# confidence, но НЕ классифицирует тип — это делал бы классификатор s3).
_DEFAULT_DETECTOR_ANOMALY_TYPE = "anomaly"

# Полный словарь кодов типов детектора ARS end2end (src/specification/injection.py):
#   SEM (anchor pools): dpi, ipi, mp, hallucination, bias
#   EPI (шум текста):   chars, loop, foreign, mojibake
#   CMB (геометрия):    drift, residual_inflate, coupling_break_edge
#   норма:              NonAnomaly
# Коды без собственного слота в шаблоне → generic 'anomaly'.
_DETECTOR_TYPE_MAP = {
    "dpi": "prompt_injection_dpi",
    "prompt_injection": "prompt_injection_dpi",
    "pi": "prompt_injection_dpi",
    "ipi": "prompt_injection_ipi",
    "hallucination": "hallucination",
    "halluc": "hallucination",
    "bias": "bias",
    "mp": "memory_poisoning",
    "memory_poisoning": "memory_poisoning",
    # остальной словарь детектора → generic 'anomaly' (нет слота в шаблоне)
    "chars": "anomaly",
    "loop": "anomaly",
    "foreign": "anomaly",
    "mojibake": "anomaly",
    "drift": "anomaly",
    "residual_inflate": "anomaly",
    "coupling_break_edge": "anomaly",
    "conditional_shift": "anomaly",
    "marginal_break": "anomaly",
    "nonanomaly": "anomaly",
}

# Приоритет слотов для составных меток детектора ('dpi+drift'): берём самый
# критичный из присутствующих.
_DETECTOR_TYPE_PRIORITY = (
    "prompt_injection_dpi", "prompt_injection_ipi", "hallucination",
    "memory_poisoning", "bias", "anomaly",
)


def _map_detector_anomaly_type(raw: Any) -> str:
    """Любой код типа детектора → валидный тип шаблона обратной связи.

    Покрывает весь словарь injection.py разом (не «по одной»): уже валидный тип
    остаётся как есть; составная метка 'a+b' разбирается по '+' и сводится к
    самому критичному слоту; неизвестный код → generic 'anomaly'. Гарантирует,
    что на выходе всегда тип из _OS_ANOMALY_TYPES.
    """
    t = str(raw or "").strip().lower()
    if not t:
        return _DEFAULT_DETECTOR_ANOMALY_TYPE
    mapped = set()
    for part in (p.strip() for p in t.split("+") if p.strip()):
        if part in _OS_ANOMALY_TYPES:
            mapped.add(part)
        else:
            mapped.add(_DETECTOR_TYPE_MAP.get(part, _DEFAULT_DETECTOR_ANOMALY_TYPE))
    for os_type in _DETECTOR_TYPE_PRIORITY:
        if os_type in mapped:
            return os_type
    return _DEFAULT_DETECTOR_ANOMALY_TYPE


# Текстовые поля записи: шаблон рендерит их как строку (escapeHtml(r.field)).
# LLM-узел RCA может вернуть их объектом/списком — сплющиваем в читаемый текст.
_ANOMALY_TEXT_FIELDS = (
    "business_description", "user_query", "agent_response", "tech_details", "rca_results",
)

# Ключи, которые в структурном RCA означают «сам текст» — выводим без имени ключа.
_TEXT_LIKE_KEYS = ("text", "value", "description", "anomaly_description", "summary", "message")


def _humanize_key(key: str) -> str:
    return str(key).replace("_", " ").strip()


def _flatten_text(value: Any, depth: int = 0) -> str:
    """dict/list/скаляр → многострочный текст «ключ: значение»; строка — как есть.

    Пример: {"quote": "22,5%/12 = 0,1875", "correct_value": "0,01875"} →
    "quote: 22,5%/12 = 0,1875\ncorrect value: 0,01875". Ключи-«тексты»
    (text/value/description/…) выводятся без имени ключа.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, Real):
        return str(value)
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            flat = _flatten_text(item, depth + 1)
            if not flat:
                continue
            if str(key) in _TEXT_LIKE_KEYS and len(value) == 1:
                lines.append(flat)
            elif "\n" in flat:
                lines.append(f"{_humanize_key(key)}:\n" + "\n".join("  " + ln for ln in flat.split("\n")))
            else:
                lines.append(f"{_humanize_key(key)}: {flat}")
        return "\n".join(lines)
    if isinstance(value, (list, tuple, set)):
        items = [_flatten_text(item, depth + 1) for item in value]
        items = [i for i in items if i]
        if all("\n" not in i for i in items):
            return "; ".join(items) if depth else "\n".join(f"— {i}" for i in items)
        return "\n".join(f"— {i}" for i in items)
    return str(value)


def _normalize_detector_confidence(value: Any) -> int | float | str:
    """Приводит confidence детектора к процентной шкале шаблона ``0..100``.

    Актуальный ARS ``test_anomalies`` сериализует confidence как целый процент.
    Legacy-источники могли отдавать вероятность как float ``0..1``. Тип числа
    позволяет не перепутать реальный ARS ``1`` (один процент) с ``1.0``
    (вероятность 100%).
    """
    if value in (None, ""):
        return ""
    if isinstance(value, bool) or not isinstance(value, Real):
        logging.warning(
            "report-assembler: confidence детектора не число (%r) — в отчёте "
            "будет пусто", value,
        )
        return ""

    numeric = float(value)
    if not isfinite(numeric) or not 0 <= numeric <= 100:
        logging.warning(
            "report-assembler: confidence детектора вне 0..100 (%r) — в отчёте "
            "будет пусто", value,
        )
        return ""
    if isinstance(value, Integral):
        return int(value)
    if numeric <= 1:
        return round(numeric * 100, 1)
    return round(numeric, 1)


def _normalize_detector_anomaly(a: dict) -> dict:
    """Приводит запись детектора к схеме шаблона обратной связи.

    Заполняет недостающие поля пустыми значениями и добавляет markup-поля
    (is_anomaly/severity/comments), чтобы Владелец мог разметить запись.
    anomaly_type приводится к схеме шаблона через _map_detector_anomaly_type.
    Текстовые поля (rca_results и др.), пришедшие объектом/списком от LLM-узла,
    сплющиваются в строку — шаблон рендерит только строки.
    """
    out = {k: a.get(k, "") for k in _ANOMALY_SCHEMA}
    for field in _ANOMALY_TEXT_FIELDS:
        out[field] = _flatten_text(out.get(field))
    out["anomaly_type"] = _map_detector_anomaly_type(out.get("anomaly_type"))
    out["confidence"] = _normalize_detector_confidence(out.get("confidence"))
    out["is_anomaly"] = a.get("is_anomaly", "")
    out["severity"] = a.get("severity", "")
    out["comments"] = a.get("comments", "")
    return out


def assemble_laim_report(
    anomalies: list | None = None,
    metadata: dict[str, str] | None = None,
) -> dict:
    """Собирает состояние отчёта обратной связи: метаданные + записи детектора."""
    today = date.today().isoformat()

    meta = {
        "agent_id": "",
        "agent_name": "",
        "agent_version": "",
        "business_line": "",
        "owner_name": "",
        "report_date": today,
        "period_from": today,
        "period_to": today,
        "pilot_stage": "Pilot",
    }
    if metadata:
        meta.update(metadata)

    records = [
        _normalize_detector_anomaly(a)
        for a in (anomalies or [])
        if isinstance(a, dict)
    ]

    return {
        "schema_version": "1.0",
        "metadata": meta,
        "general_comment": (
            "" if records else "Детектор не выявил аномалий за период."
        ),
        "anomalies": records,
    }
