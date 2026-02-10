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
