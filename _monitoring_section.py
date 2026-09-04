"""Раздел «Итог автомониторинга за период» из monitoring-result/v3 (выход laim-agg).

Статичная HTML-вставка в шаблон обратной связи: Владелец видит светофор
итерации, статус оценки качества, основания и реестр тестов методики этапа 4
(таблица 15). JS-состояние шаблона не затрагивается, при сохранении
Владельцем раздел остаётся в HTML как часть страницы.
"""

from __future__ import annotations

from html import escape

_LIGHTS = {"green": "зелёный", "amber": "жёлтый", "red": "красный", "gray": "серый"}
_QUALITY = {"assessed": "качество оценено", "not_assessed": "качество не оценено"}
_TESTS = {
    "data_readiness": "6.3.2 Пригодность данных периода",
    "assessor": "6.3.3 Допуск автоассессора",
    "km_test": "6.3.4 Уровень и динамика КМ",
    "oos_oot": "6.3.6 Различимость выборок (oos-oot)",
    "local_drift": "6.3.7 Покрытие потока эталоном (local drift)",
    "global_drift": "6.3.8 Прогноз по признакам (global drift)",
}
_STYLE = """<style>
.mon-light{display:inline-block;padding:3px 12px;border-radius:999px;font-weight:600;color:#fff}
.mon-green{background:#2e7d32}.mon-amber{background:#ef8f00}.mon-red{background:#c62828}.mon-gray{background:#757575}
.mon-table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
.mon-table th,.mon-table td{border-bottom:1px solid var(--border,#e0e0e0);padding:8px 6px;text-align:left;vertical-align:top}
.mon-muted{color:#757575}
</style>"""


def _light_badge(light: object) -> str:
    key = light if light in _LIGHTS else "gray"
    return f'<span class="mon-light mon-{key}">{escape(_LIGHTS.get(light, "не оценено"))}</span>'


def _registry_row(name: str, entry: dict) -> str:
    if not entry.get("received"):
        state = "не получен"
    elif entry.get("status") == "computed":
        state = _light_badge(entry.get("light"))
    else:
        state = "не оценено"
    role = "информативный" if entry.get("informative") else "светофорный"
    reason = entry.get("reason") or ""
    return (
        f"<tr><td>{escape(_TESTS.get(name, name))}</td><td>{role}</td>"
        f"<td>{state}</td><td>{escape(str(reason))}</td></tr>"
    )


def _provenance(provenance: dict) -> str:
    lines = []
    sample = provenance.get("sample")
    if isinstance(sample, dict):
        lines.append(
            f"Выборка: {sample.get('sampled_units')} из {sample.get('population_units')} "
            f"(единица — {sample.get('unit')})"
        )
    data = provenance.get("data_readiness")
    if isinstance(data, dict):
        lines.append(f"Данные периода: {data.get('state')} ({data.get('reason') or 'без ограничений'})")
    return "".join(f'<p class="mon-muted">{escape(line)}</p>' for line in lines)


def render_monitoring_section(result: dict) -> str:
    """monitoring-result/v3 → HTML-раздел в стиле секций шаблона."""
    quality = result.get("quality_status")
    reasons = result.get("reasons") or []
    registry = result.get("registry") or {}
    if reasons:
        reasons_html = "<ul>" + "".join(f"<li>{escape(str(r))}</li>" for r in reasons) + "</ul>"
    else:
        reasons_html = '<p class="mon-muted">Ограничений нет: полный реестр, зелёные результаты.</p>'
    rows = "".join(
        _registry_row(name, entry if isinstance(entry, dict) else {})
        for name, entry in registry.items()
    )
    return f"""{_STYLE}
<section class="section" id="laim-monitoring-section">
  <div class="section-head">
    <h2>Итог автомониторинга за период</h2>
    <span class="section-num">AM</span>
  </div>
  <p>Светофор итерации: {_light_badge(result.get("color"))}
    &middot; {escape(_QUALITY.get(quality, str(quality)))}</p>
  <h3>Основания</h3>
  {reasons_html}
  <h3>Реестр тестов методики (таблица 15)</h3>
  <table class="mon-table">
    <thead><tr><th>Тест</th><th>Роль</th><th>Результат</th><th>Причина / ограничение</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  {_provenance(result.get("provenance") or {})}
</section>
"""
