# Import enhancement report

## Done
- Добавлены модели и связи для `ColorImage`, `SupplierCategoryMap`, `ImportJob/ImportItem/ImportLog`.
- Добавлены флаги ревью у `Product` (`requires_color_review`, `requires_category_review`).
- Реализован CSV bulk importer с приоритетным распознаванием цвета, supplier category mapping, idempotency по `supplier_sku+slug`, транзакционным выполнением и JSONL-логом ошибок.
- Добавлены admin API для истории импорта, очередей ревью, dashboard, bulk apply mapping, retry-hint.
- Добавлены API для привязки фото к цветам и просмотра фото по цвету.
- Добавлены миграция Alembic, sample CSV, скрипты `run_sample_import.sh` и `rollback_import.sh`.
- Добавлены unit/integration тесты для цвета/маппинга/привязки фото/поведения ревью.
- Обновлён `README_START.md` и `.env.production`.

## Undone
- Полноценная визуальная страница админки (frontend UI) для массового редактирования не реализована, добавлены backend endpoints.
- Повторный запуск импорта по `import_id` реализован как endpoint-подсказка для ре-аплоада, а не прямое хранение бинарного пакета файла.
- Продвинутый fuzzy matching через external library (rapidfuzz) не добавлен, используется token-overlap.

## Tests
- `cd backend && pytest -q backend/tests/test_bulk_import_pipeline.py`

## Rollback migrations
- `cd backend && alembic downgrade 0001_initial`
