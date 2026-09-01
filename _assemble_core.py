"""
Единая логика сборки состояния отчёта LAIM в формат шаблона обратной связи.

Этот файл — единственный источник логики. Лежит внутри модуля
`laim-report-assembler`, чтобы платформа Omega видела его рядом с `main.py`.
Итоговое состояние встраивает в HTML-шаблон `main.py`.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from math import isfinite
from numbers import Integral, Real
from typing import Any


_COLOR_TO_ZONE = {
    "green": "green",
    "yellow": "yellow",
    "amber": "yellow",
    "red": "red",
    "gray": "gray",
    "grey": "gray",
}

_DRIFT_ANOMALY_TYPE = {
    "local_drift": "drift_local",
    "global_drift": "drift_global",
    "oos_oot": "drift_oos_oot",
    "km_test": "quality_degradation",
}

_TEST_TECHNICAL_FIELDS = {
    "km_test": (
        "status", "reason", "km_name", "km_baseline", "km_monitoring",
        "km_delta", "n_scored", "n_valid", "invalid_share", "thresholds",
        "min_valid_rows",
    ),
    "local_drift": (
        "status", "metric_value", "metric_value_estimate", "drop_estimate",
        "reliability_mean", "share_uncovered", "n_oos", "n_oot", "n_closest",
    ),
    "global_drift": (
        "status", "reason", "metric_value", "metric_value_estimate",
        "estimate_source", "n_selected_features", "selected_features", "n_chunks",
    ),
    "oos_oot": (
        "status", "reason", "gini_mean", "gini_std", "gini_spread_lower",
        "gini_spread_upper", "resampling_iterations", "n_oos", "n_oot",
    ),
}


def _safe_float(value: Any, label: str) -> float | None:
    """Число best-effort: непригодное значение → None с warning, не исключение."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logging.warning(
            "report-assembler: %s не число (%r) — в отчёте будет null", label, value
        )
        return None


def _normalize_color(color: Any) -> str:
    """Нормализует legacy-цвета светофора к green|yellow|red|gray."""
    if color is None:
        return "gray"
    return _COLOR_TO_ZONE.get(str(color).strip().lower(), "gray")


def _extract_all_results(result: dict[str, Any] | None) -> dict[str, Any]:
    """Поддерживает и wrapped dict, и значение output-порта all_results."""
    if not result:
        return {}
    if "all_results" in result and isinstance(result["all_results"], dict):
        return result["all_results"]
    return result


def _technical_summary(all_results: dict[str, Any], test_name: str) -> str:
    """Компактное машинное доказательство теста без отдельного HTML-порта."""
    fields = _TEST_TECHNICAL_FIELDS.get(test_name, ("status", "reason"))
    details = {name: all_results[name] for name in fields if name in all_results}
    return json.dumps(details, ensure_ascii=False, separators=(",", ":"))[:500]


def _make_anomaly_from_test(test_result: dict, test_name: str,
                            assessor_accuracy: float | None = None) -> dict | None:
    """Карточка отчёта из результата теста — для ВСЕХ тестов (red/amber/green/gray),
    чтобы Владелец видел в отчёте каждый тест, а не только проблемные.

    confidence:
    - для КАРТОЧКИ АВТОАССЕССОРА (km_test) — это РЕАЛЬНАЯ точность автоассессора
      (assessor_accuracy * 100), а не кодировка цвета. Так бейдж показывает
      осмысленное число (напр. 95%), а не синтетические 15%.
    - для дрифт-тестов confidence — НЕ вероятность (тест даёт светофор), поэтому
      кодируем им цвет светофора, чтобы бейдж в шаблоне (>75 зел., 25-75 жёлт.,
      <25 красн.) совпал с цветом теста. Вердикт — в business_description."""
    all_results = test_result.get("all_results", {})
    color = _normalize_color(all_results.get("color", "gray"))

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    # цвет светофора → confidence так, чтобы ЦВЕТ БЕЙДЖА в шаблоне совпал со светофором
    confidence_map = {"red": 15, "yellow": 55, "amber": 55, "green": 90, "gray": 50}
    if test_name == "km_test" and assessor_accuracy is not None:
        # карточка автоассессора: confidence = его точность (accuracy), 0..100
        confidence = int(round(max(0.0, min(1.0, float(assessor_accuracy))) * 100))
    elif test_name in ("local_drift", "global_drift", "oos_oot"):
        # дрифт-тесты: confidence НЕприменим (тест даёт светофор, не вероятность).
        # Пусто → шаблон покажет «—». Вердикт виден по тексту/цвету (semaphore_title).
        confidence = ""
    else:
        confidence = confidence_map.get(color, 50)
    lights = all_results.get("calculated_traffic_lights")
    semaphore_title = lights.get("semaphore_title", "") if isinstance(lights, dict) else ""
    if not semaphore_title:
        _ru = {"red": "красному", "yellow": "жёлтому", "amber": "жёлтому",
               "green": "зелёному", "gray": "серому"}
        semaphore_title = f"Тест соответствует {_ru.get(color, color)} светофору"

    return {
        "trace_id": "",
        "starttime": now,
        "endtime": now,
        "anomaly_type": _DRIFT_ANOMALY_TYPE.get(test_name, test_name),
        "confidence": confidence,
        "business_description": semaphore_title,
        "user_query": "",
        "agent_response": "",
        "tech_details": _technical_summary(all_results, test_name),
        "rca_results": "",
        "is_anomaly": "",
        "severity": "",
        "comments": "",
    }


_ANOMALY_SCHEMA = [
    "trace_id", "starttime", "endtime", "anomaly_type", "confidence",
    "business_description", "user_query", "agent_response", "tech_details", "rca_results",
]

# Допустимые типы аномалий в схеме ОС-шаблона.
_OS_ANOMALY_TYPES = {
    "drift_global", "drift_local", "drift_oos_oot",
    "hallucination", "prompt_injection_dpi", "quality_degradation",
    "anomaly",   # generic: аномалия детектора без классификации типа
}
# Дефолт для типонеразмеченных аномалий детектора (end2end s1+s2 детектит по
# confidence, но НЕ классифицирует тип — это делал бы классификатор s3).
# ВАЖНО: НЕ 'quality_degradation' — он в шаблоне группа «Автоасессор/Деградация КМ»,
# туда детектор-аномалии улетали и сваливались в один блок с КМ (без trace_id).
# 'anomaly' попадает в блок «Детектор аномалий» и рендерится с trace_id.
_DEFAULT_DETECTOR_ANOMALY_TYPE = "anomaly"

# Полный словарь кодов типов детектора ARS end2end (src/specification/injection.py):
#   SEM (anchor pools): dpi, ipi, mp, hallucination, bias
#   EPI (шум текста):   chars, loop, foreign, mojibake
#   CMB (геометрия):    drift, residual_inflate, coupling_break_edge
#   норма:              NonAnomaly
# В схеме ОС детектор-аномалии могут лечь только в ДВА типизированных слота —
# prompt_injection_dpi и hallucination (рендерятся с trace_id в блоке «Детектор
# аномалий»). Остальные коды отдельного слота в шаблоне ОС не имеют → generic
# 'anomaly' (тоже с trace_id). drift_*/quality_degradation сюда НЕ маппим: это
# слоты наших тест-модулей и блока деградации КМ (без trace_id).
_DETECTOR_TYPE_MAP = {
    # prompt injection → prompt_injection_dpi
    "dpi": "prompt_injection_dpi",
    "ipi": "prompt_injection_dpi",
    "prompt_injection": "prompt_injection_dpi",
    "pi": "prompt_injection_dpi",
    # галлюцинации → hallucination
    "hallucination": "hallucination",
    "halluc": "hallucination",
    # остальной словарь детектора → generic 'anomaly' (нет слота в ОС)
    "bias": "anomaly",
    "mp": "anomaly",
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
_DETECTOR_TYPE_PRIORITY = ("prompt_injection_dpi", "hallucination", "anomaly")


def _map_detector_anomaly_type(raw: Any) -> str:
    """Любой код типа детектора → валидный тип схемы ОС.

    Покрывает весь словарь injection.py разом (не «по одной»): уже валидный тип
    ОС остаётся как есть; составная метка 'a+b' разбирается по '+' и сводится к
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
    return sorted(mapped)[0] if mapped else _DEFAULT_DETECTOR_ANOMALY_TYPE


# Текстовые поля записи: шаблон ОС рендерит их как строку (escapeHtml(r.field)).
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
        return value.strip() if depth == 0 else value.strip()
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


def _normalize_detector_anomaly(a: dict) -> dict:
    """Приводит запись детектора (заглушки/реального) к схеме шаблона ОС.

    Заполняет недостающие поля пустыми значениями и добавляет markup-поля
    (is_anomaly/severity/comments) — как у аномалий из тестов, чтобы Владелец
    мог их разметить в шаблоне ОС. anomaly_type приводится к схеме ОС через
    _map_detector_anomaly_type (весь словарь детектора + составные + fallback).
    Текстовые поля (rca_results и др.), пришедшие объектом/списком от LLM-узла,
    сплющиваются в строку — шаблон ОС рендерит только строки.
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


def _normalize_detector_confidence(value: Any) -> int | float | str:
    """Приводит confidence детектора к процентной шкале ОС ``0..100``.

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


def assemble_laim_report(
    assessor_accuracy: float | None = None,
    km_result: dict[str, Any] | None = None,
    local_drift_result: dict[str, Any] | None = None,
    global_drift_result: dict[str, Any] | None = None,
    oos_oot_result: dict[str, Any] | None = None,
    aggregator_result: dict[str, Any] | None = None,
    perv_validation_km: dict[str, Any] | None = None,
    metadata: dict[str, str] | None = None,
    detector_anomalies: list | None = None,
) -> dict:
    """Собирает итоговый JSON-отчёт в формате laim_import_sample."""
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
    report_day = str(meta.get("period_to") or meta.get("report_date") or today)

    agg_color = "gray"
    if aggregator_result:
        agg_color = _extract_all_results(aggregator_result).get("color", "gray")
    agg_color = _normalize_color(agg_color)

    # NB_km может прислать значение и обёрнутым ({"perv_validation_km": {...}});
    # молча брать 0 нельзя — в отчёт уезжал нулевой baseline без следа.
    km_payload = perv_validation_km or {}
    if "value" not in km_payload and isinstance(km_payload.get("perv_validation_km"), dict):
        km_payload = km_payload["perv_validation_km"]
    km_all = km_result.get("all_results", {}) if km_result else {}
    km_status = km_all.get("status")
    baseline_value = km_all.get("km_baseline")
    if baseline_value is None:
        baseline_value = km_payload.get("value")
    if baseline_value is None:
        logging.warning(
            "report-assembler: baseline отсутствует (%r) — в отчёте будет null",
            perv_validation_km,
        )
    baseline = _safe_float(baseline_value, "km_baseline")

    km_monitoring = _safe_float(km_all.get("km_monitoring"), "km_monitoring")
    if km_monitoring is None:
        logging.warning(
            "report-assembler: КМ мониторинга отсутствует (status=%r, %s) — "
            "в отчёте будет null", km_status, km_all.get("reason"),
        )

    raw_thresholds = km_all.get("thresholds")
    report_thresholds = {"yellow_pp": None, "red_pp": None}
    if isinstance(raw_thresholds, dict):
        green = raw_thresholds.get("green")
        red = raw_thresholds.get("red")
        try:
            report_thresholds = {
                "yellow_pp": round(float(green) * 100, 6),
                "red_pp": round(float(red) * 100, 6),
            }
        except (TypeError, ValueError):
            logging.warning(
                "report-assembler: некорректные thresholds km_test=%r — "
                "в отчёте будут null",
                raw_thresholds,
            )

    anomalies = []
    for test_name, result in {
        "km_test": km_result,
        "local_drift": local_drift_result,
        "global_drift": global_drift_result,
        "oos_oot": oos_oot_result,
    }.items():
        if result is None:
            continue
        # km_test (карточка автоассессора): confidence = его точность (accuracy)
        anomaly = _make_anomaly_from_test(result, test_name, assessor_accuracy=assessor_accuracy)
        if anomaly is not None:
            anomalies.append(anomaly)
    # None означает именно отсутствие detector-порта; [] означает, что
    # подключённый детектор отработал и событий не нашёл.
    detector_connected = detector_anomalies is not None

    # Аномалии от детектора (реальный детектор ИЛИ detector-test с trace-level):
    # (hallucination / prompt_injection_dpi / ...). Кладём в начало списка.
    detector = [
        _normalize_detector_anomaly(a)
        for a in (detector_anomalies or [])
        if isinstance(a, dict)
    ]
    anomalies = detector + anomalies

    comments = []
    if not detector_connected:
        comments.append(
            "Детектор аномалий не подключён: точечные записи по трейсам "
            "в отчёте отсутствуют."
        )
    aggregator_payload = _extract_all_results(aggregator_result)
    if aggregator_payload:
        meta["monitoring_evidence"] = {
            key: aggregator_payload.get(key)
            for key in (
                "schema_version", "expected_tests", "missing_tests",
                "coverage_gate_applied", "assessor_accuracy_gate_applied",
                "assessment_gate_applied", "key_metric_gate_applied",
                "gate_reasons", "assessor_accuracy", "assessment_result",
                "test_results",
            )
        }
    missing_tests = aggregator_payload.get("missing_tests") or []
    if missing_tests:
        comments.append(
            "Не получены результаты обязательных тестов: "
            + ", ".join(map(str, missing_tests)) + ". Итог не является полным."
        )
    not_computable = [
        name for name, result in (
            ("km_test", km_result),
            ("local_drift", local_drift_result),
            ("global_drift", global_drift_result),
            ("oos_oot", oos_oot_result),
        )
        if result is not None
        and _extract_all_results(result).get("status") == "not_computable"
    ]
    if not_computable:
        comments.append(
            "Не вычислены тесты: " + ", ".join(not_computable) +
            ". Причины сохранены в карточках тестов."
        )

    return {
        "schema_version": "1.0",
        "metadata": meta,
        "general_comment": " ".join(comments),
        "timeline": [{"date": report_day, "zone": agg_color}],
        "km_dynamics": {
            "baseline": (None if baseline is None else round(float(baseline), 4)),
            "thresholds": report_thresholds,
            "series": [
                {
                    "date": report_day,
                    # округление: иначе в отчёт уезжает 0.6385542168674698 — мусор в UI
                    "km": (None if km_monitoring is None
                           else round(float(km_monitoring), 4)),
                    "assessor_accuracy": (
                        None if assessor_accuracy is None
                        else round(float(assessor_accuracy), 4)
                    ),
                }
            ],
        },
        "anomalies": anomalies,
    }
