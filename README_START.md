# Быстрый старт (docker-compose)

## 1) Заполни переменные окружения
Файл: `.env.production` в корне.

Минимум:
- `TELEGRAM_BOT_TOKEN=...`
- `JWT_SECRET=...`
- `ADMIN_PASSWORD=...`
- `ADMIN_CHAT_ID=...` (куда слать уведомления о чеках)

## 2) Запуск
```bash
docker-compose up --build
```

## 3) Открыть
- Frontend: `http://localhost:3000`
- Backend health: `http://localhost:8000/health`

## Флоу оплаты
1) Пользователь оформляет заказ: корзина -> `POST /api/orders` (без файла)
2) На странице успеха грузит чек: `POST /api/orders/{id}/payment-proof` (jpg/png/webp/pdf)
3) Админу приходит сообщение в Telegram **только после загрузки чека**.
4) Админ подтверждает: `POST /api/admin/orders/{id}/confirm_payment` -> статус `processing` + начисления.

## Админка
Открыть: `/#/admin`
- Заказы: подтвердить оплату, менять статусы
- Реквизиты: редактирование payment settings
- Спец‑промокоды: CRUD (type=special)

## Проверка статуса задачи импорта поставщиков
Если запускаете ручной импорт через админ API, не используйте значения в угловых скобках буквально.
Сначала подставьте реальные параметры в переменные:

```bash
BACKEND_URL="http://localhost:8000"
TASK_ID="<uuid_задачи>"
ADMIN_TOKEN="<jwt_админа>"

curl -sS "${BACKEND_URL}/api/admin/supplier-intelligence/tasks/${TASK_ID}" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}"
```

Полезные проверки:
- `GET /health` — что backend доступен.
- `GET /api/auth/me` с тем же Bearer токеном — что токен действителен.

## Импорт поставщиков (новый pipeline)

ENV-переменные:
- `CATEGORY_MATCH_THRESHOLD` (по умолчанию `0.8`)
- `AUTO_CONFIRM_CATEGORY_THRESHOLD` (по умолчанию `0.9`)
- `IMPORTER_DRY_RUN` (`1/0`)

Миграции и тесты:
```bash
cd backend
alembic upgrade head
pytest -q
```

Локальный запуск тестового импорта CSV:
```bash
TOKEN=<admin_jwt> SUPPLIER_ID=1 ./backend/scripts/run_sample_import.sh backend/sample_data/test_import.csv
```

Откат импорта:
```bash
./backend/scripts/rollback_import.sh <import_id>
```
