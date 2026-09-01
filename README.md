# laim-report-assembler

Финальная нода-сборщик пайплайна LAIM. Собирает из результатов всех тестов итоговый
JSON строго в формате шаблона ОС (`data/laim_import_sample.json`) и сохраняет файл.
Это тот артефакт, ради которого работает весь пайплайн.

Платформенная обёртка над логикой `assemble_report.py`. На платформе финальный JSON
формирует отдельная Docker-нода (а не локальный скрипт) → результат идёт в Data Saver.

## Что делает

1. **timeline** — зона светофора по дате из цвета агрегатора
   (нормализация: `amber→yellow`, `grey→gray` → строго `green|yellow|red|gray`).
2. **km_dynamics** — baseline КМ, пороги (yellow 15пп / red 25пп), точка мониторинга КМ
   и точность ассессора.
3. **anomalies** двух типов:
   - **статистические** — каждый **не-зелёный** тест (drift/km) → запись аномалии с типом
     (`drift_local` / `drift_global` / `drift_oos_oot` / `quality_degradation`) и confidence по цвету;
   - **trace-level** — строки `scored_data`, где метрика ниже порога (`agent_<metric> < bad_threshold`),
     → аномалии с реальным вопросом/ответом агента (для разметки владельцем).
4. **Сохраняет** JSON в `output_dir` под уникальным именем `<prefix>_<timestamp>.json`.

Поля `is_anomaly` / `severity` / `comments` оставляются пустыми — их заполняет владелец
агента при разметке.

## Входы (порты)

| Порт | Тип | Источник |
|---|---|---|
| `scored_data` * | dataframe | assessor-agent `scored_data` |
| `Acc_auto` * | float | assessor-agent `Acc_auto` |
| `metric_selector_res` * | dict | kriteria-selector (нужен `main_metric`) |
| `perv_validation_km` * | dict | synthetic-generator / Jupyter baseline |
| `km_all_results` / `km_test_description` | dict / str | km-dynamic-test |
| `local_drift_all_results` / `local_drift_test_description` | dict / str | local-drift-test |
| `global_drift_all_results` / `global_drift_test_description` | dict / str | global-drift-test |
| `oos_oot_all_results` / `oos_oot_test_description` | dict / str | oos-oot-test |
| `aggregator_result` * | dict | semaphore-aggregator `all_results` |
| `metadata` | dict | synthetic-generator / владелец |
| `detector_anomalies` | JSON-строка / list / dict | детектор `test_anomalies`; в отчёт попадают только записи с **`confidence >= min_confidence`** |

`*` — обязательный. Если `metric_selector_res.main_metric` пуст → нода падает с ошибкой
(это намеренно — без основной метрики отчёт собрать нельзя).

## Выходы (порты)

| Порт | Тип | Назначение |
|---|---|---|
| `report_json` | dict | сам объект отчёта (формат ОС) |
| `report_path` | str | путь к сохранённому файлу |

## Параметры (UI ноды)

| Параметр | По умолчанию | Смысл |
|---|---|---|
| `output_dir` | /tmp/laim/results | куда писать JSON |
| `output_prefix` | laim_report | префикс имени файла |
| `bad_threshold` | 0.5 | порог метрики для trace-level аномалий |
| `min_confidence` | 75 | минимальный confidence (0..100) аномалии детектора; ниже — не попадает в отчёт. Аномалии тестов (drift/km) фильтр не затрагивает |

## Структура итогового JSON (контракт ОС)

```
schema_version, metadata, general_comment,
timeline[],      ← зоны светофора по датам
km_dynamics{},   ← baseline + пороги + динамика КМ
anomalies[]      ← статистические (drift/km) + trace-level (плохие ответы)
```

## Подключение на канвасе

**Последняя** нода. Принимает результаты ассессора, 4 тестов и агрегатора; выход — в Data Saver.

```
assessor-agent      ─ scored_data / Acc_auto ──┐
kriteria-selector   ─ metric_selector_res ─────┤
4 теста             ─ all_results / test_description ─┤→ [report-assembler] ─ report_json / report_path → Data Saver
semaphore-aggregator─ all_results (aggregator_result)┤                                                    (team_valid_autovalid/laim/results)
synthetic-generator ─ perv_validation_km / metadata ─┘
```

> ⚠️ **Data Saver:** писать в `team_valid_autovalid/laim/results` **уникальным именем**,
> режим **НЕ Replace** — иначе затрёт чужие результаты.

## Зависимости

`pandas` (см. `requirements.txt`). LLM не требуется.

## Локальная проверка

```bash
pip install -r requirements.txt
python3 -c "
import pandas as pd
from main import main
sd = pd.DataFrame({'query_id':['1'],'question':['q'],'answer':['a'],'agent_quality_metric':[0.2]})
r = main(scored_data=sd, Acc_auto=0.8,
         metric_selector_res={'main_metric':'quality_metric','other_metrics':[]},
         perv_validation_km={'name':'quality_metric','value':0.85},
         aggregator_result={'all_results':{'color':'yellow'}})
print('keys:', list(r['report_json'].keys()))
print('anomalies:', len(r['report_json']['anomalies']))
print('saved:', r['report_path'])
"
```
