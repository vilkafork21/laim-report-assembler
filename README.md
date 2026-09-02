# laim-report-assembler

Замыкающая нода детекторной линии LAIM. Принимает **записи детектора аномалий**
(`test_anomalies` ноды `laim-andes-sds`) и **метаданные пилота**, а отдаёт один
готовый HTML — отчёт обратной связи Владельца агента со встроенным состоянием,
который передаётся в Data Saver и открывается уже заполненным.

## Зачем нода нужна

Владелец агента получает не сырой JSON детектора, а документ, в котором можно
разметить каждую аномалию и сохранить тот же файл обратно. Нода снимает разрыв
между контрактом детектора и словарём шаблона: коды типов (`dpi`, `halluc`, `mp`,
`mojibake`, составные `dpi+drift`) сводятся к шести слотам шаблона, структурный
RCA от LLM-узла сплющивается в текст, `confidence` приводится к процентам.

Ключевое решение — **деградация вместо падения**: непригодный вход (невалидный
JSON, не тот тип, мусорные записи) пропускается с `logger.warning`, отчёт
собирается из разобранного. Падение одно — в шаблоне нет контейнера состояния.

## Место в контуре

```text
laim-andes-sds (INFERENCE) ── test_anomalies ──► anomalies ──┐
                                                             ├─ laim-report-assembler ──► report_html ──► Data Saver
метаданные пилота (источник в wiring не задан) ──► metadata ──┘
```

В `monitoring/shared/port_wiring.json` (`laim-sberds-wiring.v7`) нода числится
в списке нод, но **соединений не имеет**: `anomalies`, `metadata` и
`report_html` внутри мониторингового контура не подключены. Аномалии приходят
из детекторной линии; `metadata` в `descriptor.json` описан как выход
prevalidation-context, но такого поставщика в wiring нет.

## Порты и настройки

### Входы

| Порт | Обязательный | Что приходит с платформы |
|---|---|---|
| `anomalies` | да | JSON-строка `{"anomalies": [...]}` (контракт `test_anomalies` детектора); также принимаются `bytes`/`bytearray` в UTF-8, `dict` с ключом `anomalies` и готовый `list` записей |
| `metadata` | нет | `dict` (или его JSON-строка/`bytes`) с ключами `agent_id`, `agent_name`, `agent_version`, `business_line`, `owner_name`, `report_date`, `period_from`, `period_to`, `pilot_stage`; лишние ключи проходят в состояние как есть |

### Выходы

| Порт | Тип | Что отдаёт |
|---|---|---|
| `report_html` | default / `shape_model` | Полный HTML `laim_feedback_template.html`, в контейнере `laim-embedded-state` — JSON состояния `schema_version` `"1.0"` |

### Настройки ноды

Не применимо: `descriptor.json` параметров не объявляет.

## Как проходит прогон

```text
1. Разбор anomalies   строка/bytes → JSON → список; не-объекты отброшены
2. Разбор metadata    строка/bytes → JSON → dict; иначе None
3. Сборка состояния   дефолты метаданных, нормализация каждой записи, general_comment
4. Встраивание        шаблон с диска → проверка контейнера → JSON в <script> → report_html
```

**1–2. Разбор входов** (`_as_anomaly_list`, `_as_metadata` в `main.py`).
`None` — пустой результат без предупреждения; невалидный JSON, не-список в
`anomalies`, не-объект в `metadata` — warning и пустой результат; элементы
списка не-`dict` отбрасываются со счётчиком.

**3. Сборка состояния** (`assemble_laim_report` в `_assemble_core.py`).
Дефолты метаданных перекрываются пришедшими: без порта `metadata` в отчёте
пустые `agent_id`, `agent_name`, `agent_version`, `business_line`, `owner_name`,
`report_date` = `period_from` = `period_to` = дата сборки, `pilot_stage` =
`Pilot`. Записи приводятся к схеме шаблона (см. «Форматы выхода»); без записей
`general_comment` = «Детектор не выявил аномалий за период.», иначе пусто.

**4. Встраивание** (`_fill_template`). Шаблон читается по `_TEMPLATE_PATH`
рядом с `main.py`. Состояние сериализуется `json.dumps(ensure_ascii=False,
default=str)`, `<` заменяется на `\u003c` (как в `saveHtml` самого шаблона),
чтобы `</script>` внутри данных не оборвал контейнер; `JSON.parse` возвращает
`<`. Замена — одна, только для пустого контейнера
`<script id="laim-embedded-state" type="application/json"></script>`.

### Пример лога прогона

Успешный прогон **не пишет ни одной строки** — INFO-логов нет, только
предупреждения о деградации. Формат строк — из кода; значения условные:

```text
WARNING anomalies: невалидный JSON — записи пропущены
WARNING anomalies: пропущено 2 записей не-объектов
WARNING metadata: невалидный JSON — шапка отчёта останется пустой
WARNING metadata: ожидался объект, получен list — шапка отчёта останется пустой
WARNING report-assembler: confidence детектора не число ('нет') — в отчёте будет пусто
```

Префиксы `anomalies:`/`metadata:` — логгер `__name__` в `main.py`;
`report-assembler:` — `_assemble_core.py` пишет в корневой логгер.

## Форматы выхода и контракты

Единица наблюдения — **одна запись детектора = одна карточка отчёта**; записи
не дедуплицируются по `trace_id` и не сортируются. Встроенное состояние:

```json
{
  "schema_version": "1.0",
  "metadata": {"agent_id": "", "agent_name": "", "agent_version": "", "business_line": "",
               "owner_name": "", "report_date": "2026-09-02", "period_from": "2026-09-02",
               "period_to": "2026-09-02", "pilot_stage": "Pilot"},
  "general_comment": "",
  "anomalies": [{"trace_id": "...", "starttime": "...", "endtime": "...",
                 "anomaly_type": "prompt_injection_dpi", "confidence": 90,
                 "business_description": "...", "user_query": "...", "agent_response": "...",
                 "tech_details": "...", "rca_results": "...",
                 "is_anomaly": "", "severity": "", "comments": ""}]
}
```

Схема записи — 10 полей детектора (`_ANOMALY_SCHEMA`, перечислены в JSON
выше; отсутствующее поле — пустая строка) плюс три поля разметки Владельца
`is_anomaly`, `severity`, `comments` (из записи, если уже размечена).

**`anomaly_type`** всегда из словаря шаблона `_OS_ANOMALY_TYPES`:
`hallucination`, `bias`, `prompt_injection_dpi`, `prompt_injection_ipi`,
`memory_poisoning`, `anomaly` (generic — «Аномалия без классификации»).
Маппинг `_DETECTOR_TYPE_MAP`: `dpi`/`prompt_injection`/`pi` →
`prompt_injection_dpi`; `ipi` → `prompt_injection_ipi`; `halluc` →
`hallucination`; `mp` → `memory_poisoning`; `chars`, `loop`, `foreign`,
`mojibake`, `drift`, `residual_inflate`, `coupling_break_edge`,
`conditional_shift`, `marginal_break`, `nonanomaly`, пустое значение и любой
неизвестный код → `anomaly`. Составная метка `a+b` разбирается по `+` и
сводится к самому критичному слоту в порядке `_DETECTOR_TYPE_PRIORITY`:
`prompt_injection_dpi` → `prompt_injection_ipi` → `hallucination` →
`memory_poisoning` → `bias` → `anomaly`. Регистр и пробелы игнорируются.

**`confidence`** — процентная шкала `0..100`: целое остаётся как есть (`90`),
дробное `<= 1` умножается на 100 (`0.9` → `90.0`), дробное `> 1` округляется до
десятых; не число, `bool`, `NaN`/`inf` или значение вне `0..100` → пустая строка.

**Текстовые поля** (`business_description`, `user_query`, `agent_response`,
`tech_details`, `rca_results`), пришедшие `dict`/`list`, сплющиваются
`_flatten_text` в текст «ключ: значение» (подчёркивания → пробелы; единственный
ключ `text`/`value`/`description`/`anomaly_description`/`summary`/`message` —
без имени; элементы списка через `— `, вложенные через `; `; `bool` → «да»/«нет»).

## Падение против деградации

Единственное падение ноды — отсутствие контейнера в шаблоне; `reason_code`
не применимо, исключение стандартное:

| Причина | Исключение |
|---|---|
| В `laim_feedback_template.html` нет строки `<script id="laim-embedded-state" type="application/json"></script>` | `ValueError("laim_feedback_template.html: контейнер laim-embedded-state не найден")` |

Всё остальное — деградация с `logger.warning`, HTML отдаётся всегда:

| Событие | Реакция |
|---|---|
| `anomalies` — невалидный JSON или не список/не объект с `anomalies` | `anomalies: []`, `general_comment` «Детектор не выявил аномалий за период.» |
| Элемент списка не `dict` | запись отброшена, warning со счётчиком |
| `metadata` — невалидный JSON или не объект | шапка с дефолтами (пустой `agent_id`, период = дата сборки) |
| `confidence` не число или вне `0..100` | пустая строка, warning `report-assembler:` |

## Внешние сервисы

Не применимо: нода не обращается к сети, LLM-шлюзу, HDFS и переменным окружения.

## Наблюдаемость

Порта журнала нет: только лог платформы и сам HTML. Триаж на сотне прогонов —
поиск в логе префиксов `anomalies:`, `metadata:`, `report-assembler:`; прогон
без предупреждений разобрал входы целиком. Пустой `anomalies` в HTML неотличим
от честно пустого выхода детектора — различает их только лог.

## Карта кода

```text
descriptor.json              порты anomalies/metadata/report_html, py312-simple, sourceFiles
main.py                      разбор входов best-effort, встраивание состояния в шаблон, main()
_assemble_core.py            схема записи, словари типов и маппинг, confidence, сплющивание текста
laim_feedback_template.html  шаблон обратной связи Владельца с пустым контейнером laim-embedded-state
requirements.txt             пустой — только stdlib
tests/test_report_assembler.py  10 тестов: формы входов, маппинг типов, confidence, экранирование, мусор
```

## Что делать, если

- **В отчёте нет аномалий, хотя детектор их нашёл** — в логе прогона искать
  `anomalies:`: чаще всего на порт пришёл не JSON `{"anomalies": [...]}`
  (двойная сериализация, другой ключ) и записи пропущены целиком.
- **Шапка отчёта пустая, период равен дате сборки** — порт `metadata` не
  подключён или пришёл не объект (`metadata:` в логе); это штатное поведение.
- **Все типы показаны как «Аномалия без классификации»** — детектор отдаёт коды
  вне `_DETECTOR_TYPE_MAP` или пустой `anomaly_type`; сверить словарь с детектором.
- **Нода упала с `ValueError` про `laim-embedded-state`** — в ZIP попал шаблон
  с заполненным или удалённым контейнером; пересобрать из `dev`.

## Деплой

Нода самодостаточна: импорт только `_assemble_core` из того же каталога.
База — `py312-simple`; точка входа — функция `main` в `main.py`;
`script.runConfiguration.sourceFiles` = `main.py`, `_assemble_core.py`,
`laim_feedback_template.html`. Шаблон грузится по `_TEMPLATE_PATH` относительно
`main.py`, поэтому обязан лежать в том же каталоге ZIP. `requirements.txt`
пуст — зависимостей нет. Теста соответствия `sourceFiles` диску в `tests/` нет.

CI (`.github/workflows/ci.yml`, Python 3.12): `ruff check .` и
`python -m pytest -q` (10 тестов). ZIP — `descriptor.json`, `requirements.txt`
и три `sourceFiles` с коммита ветки `dev`; тот же коммит переносится снимком в
## Глоссарий

- **Отчёт обратной связи** — HTML `laim_feedback_template.html` с карточками
  аномалий и полями разметки Владельца; сохраняется тем же файлом обратно.
- **Владелец** — владелец GenAI-агента, который размечает аномалии в отчёте.
- **Встроенное состояние** — JSON в контейнере `laim-embedded-state`, из
  которого `hydrateFromEmbeddedState` восстанавливает отчёт при открытии.
- **`test_anomalies`** — выходной порт детектора `laim-andes-sds`,
  JSON `{"anomalies": [...]}`; контракт входа `anomalies` этой ноды.
- **RCA** — анализ первопричины (`rca_results`) от LLM-узла, текст или структура.
- **Data Saver** — нода платформы, сохраняющая `report_html` как файл.
