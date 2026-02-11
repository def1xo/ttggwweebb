# Supplier automation MVP (free-first)

Этот MVP добавляет базовые блоки под вашу идею:

1. Анализ ссылок поставщиков (Google Sheets / HTML / MoySklad-like страницы).
2. Авто-маппинг названий товаров в категории (например, худи/зипки -> `Кофты`).
3. Выбор лучшего оффера поставщика по цвету/размеру и дроп-цене.
4. Оценка рыночной цены по списку цен с отбрасыванием мусора (`1₽`, `1_000_000₽`).

## Что уже есть в API

Admin endpoints:

- `GET /api/admin/supplier-intelligence/sources`
- `POST /api/admin/supplier-intelligence/sources`
- `POST /api/admin/supplier-intelligence/sources/bulk-upsert`
- `PATCH /api/admin/supplier-intelligence/sources/{source_id}`
- `DELETE /api/admin/supplier-intelligence/sources/{source_id}`
- `POST /api/admin/supplier-intelligence/analyze-links`
- `POST /api/admin/supplier-intelligence/analyze-sources`
- `POST /api/admin/supplier-intelligence/import-products`
- `POST /api/admin/supplier-intelligence/avito-market-scan`
- `POST /api/admin/supplier-intelligence/telegram-media-preview`
- `POST /api/admin/supplier-intelligence/analyze-images`
- `POST /api/admin/supplier-intelligence/best-offer`
- `POST /api/admin/supplier-intelligence/estimate-market-price`

## Как подключать AI бесплатно

- **Без затрат**: rule-based (как в MVP) + регулярные выражения/словари.
- **Локально и бесплатно**: `Ollama` + open-weight модель (например, `qwen2.5:7b-instruct`) для генерации описаний.
- **Гибрид**: если LLM недоступна — fallback на шаблонные описания.

## Что делать следующим шагом (по порядку, чтобы без сбоев)

1. **База и идемпотентность**: добавить/проконтролировать уникальные ограничения на варианты (`product_id + size_id + color_id`), чтобы повторный импорт не плодил дубли.
2. **Фоновый импорт**: вынести `import-products` в celery job + статус выполнения в БД (долгие источники не должны держать HTTP-запрос).
3. **Устойчивый HTTP-слой**: retries + backoff + ограничение частоты на Avito/TG и image-download.
4. **Планировщик (Celery beat)** для авто-синка по расписанию.
5. **Улучшенный dedupe**: multi-image consensus и хранение сигнатур, чтобы одинаковые принты из разных источников матчились стабильнее.

## Важный момент про Avito

Публичного официального open API для массового бесплатного парсинга нет. Для устойчивой работы нужно:

- legal-safe сбор,
- ротация/ограничение запросов,
- фильтры по состоянию товара (только новые),
- отбрасывание мусорных значений.

В MVP уже заложен шаг 4 как отдельный модуль, чтобы можно было подключить без ломки текущей архитектуры.
