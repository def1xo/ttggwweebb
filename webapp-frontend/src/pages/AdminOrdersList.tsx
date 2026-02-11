// webapp-frontend/src/pages/AdminOrdersList.tsx
import React, { useEffect, useState } from "react";
import api from "../services/api"; // axios instance: api.get/post(...)
import dayjs from "dayjs";

type OrderRow = {
  id: number;
  user_id: number;
  total: string;
  status: string;
  created_at: string;
};

function normStatus(s: any): string {
  if (!s) return "";
  const raw = String(s);
  return (raw.split(".").pop() || raw).trim();
}

const STATUSES = ["awaiting_payment", "paid", "processing", "sent", "received", "delivered", "cancelled"];

export default function AdminOrdersList(): JSX.Element {
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | "">("");
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    load();
  }, [statusFilter]);

  async function load() {
    setLoading(true);
    setMessage("");
    try {
      const params: any = {};
      if (statusFilter) params.status = statusFilter;
      const res = await api.get("/api/admin/orders", { params });
      const arr: any[] = (res as any).data || [];
      const mapped = arr.map((o: any) => ({
        id: Number(o.id),
        user_id: Number(o.user_id ?? o.user?.id ?? 0),
        total: String(o.total_amount ?? o.total ?? o.totalAmount ?? 0),
        status: normStatus(o.status),
        created_at: String(o.created_at ?? o.createdAt ?? ""),
      }));
      setOrders(statusFilter ? mapped : mapped.filter((o) => o.status !== "received"));
    } catch (err: any) {
      console.error(err);
      setMessage(err?.response?.data?.detail || "Ошибка при загрузке заказов");
    } finally {
      setLoading(false);
    }
  }

  async function changeStatus(orderId: number, newStatus: string) {
    if (!confirm(`Поменять статус заказа #${orderId} на "${newStatus}"?`)) return;
    try {
      await api.post(`/api/admin/orders/${orderId}/status`, { status: newStatus });
      setMessage(`Статус заказа ${orderId} обновлён: ${newStatus}`);
      load();
    } catch (err: any) {
      console.error(err);
      setMessage(err?.response?.data?.detail || "Не удалось изменить статус");
    }
  }

  async function confirmPayment(orderId: number) {
    if (!confirm(`Подтвердить оплату заказа #${orderId}?`)) return;
    try {
      await api.post(`/api/admin/orders/${orderId}/confirm_payment`, {});
      setMessage(`Оплата подтверждена для заказа ${orderId}`);
      load();
    } catch (err: any) {
      console.error(err);
      setMessage(err?.response?.data?.detail || "Не удалось подтвердить оплату");
    }
  }

  return (
    <div className="max-w-6xl mx-auto p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">Заказы — админ</h1>
        <button onClick={() => window.history.back()} className="px-3 py-2 border rounded">Назад</button>
      </div>

      <div className="flex items-center gap-4 mb-4">
        <div>
          <label className="block text-sm text-gray-600">Фильтр по статусу</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="mt-1 p-2 border rounded bg-white"
          >
            <option value="">Все статусы</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div>
          <button onClick={load} className="px-3 py-2 bg-black text-white rounded">
            Обновить
          </button>
        </div>
      </div>

      {message && <div className="mb-4 p-3 bg-gray-50 border rounded text-sm">{message}</div>}

      {loading ? (
        <div>Загрузка...</div>
      ) : (
        <div className="bg-white shadow rounded overflow-hidden">
          <table className="min-w-full table-auto">
            <thead className="bg-gray-100">
              <tr>
                <th className="px-4 py-2 text-left text-sm">#</th>
                <th className="px-4 py-2 text-left text-sm">Клиент</th>
                <th className="px-4 py-2 text-left text-sm">Сумма</th>
                <th className="px-4 py-2 text-left text-sm">Статус</th>
                <th className="px-4 py-2 text-left text-sm">Создан</th>
                <th className="px-4 py-2 text-left text-sm">Действия</th>
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-sm text-gray-500">
                    Пусто
                  </td>
                </tr>
              )}
              {orders.map((o) => (
                <tr key={o.id} className="border-t">
                  <td className="px-4 py-3 text-sm font-medium">#{o.id}</td>
                  <td className="px-4 py-3 text-sm">{o.user_id}</td>
                  <td className="px-4 py-3 text-sm">{o.total} ₽</td>
                  <td className="px-4 py-3 text-sm">
                    <span className="inline-block px-2 py-1 rounded text-xs bg-gray-100">{o.status}</span>
                  </td>
                  <td className="px-4 py-3 text-sm">{dayjs(o.created_at).format("YYYY-MM-DD HH:mm")}</td>
                  <td className="px-4 py-3 text-sm flex gap-2">
                    {o.status === "paid" ? (
                      <button
                        onClick={() => confirmPayment(o.id)}
                        className="px-2 py-1 border rounded text-sm bg-black text-white"
                        title="Подтвердить оплату"
                      >
                        Подтвердить оплату
                      </button>
                    ) : null}

                    <button
                      onClick={() => changeStatus(o.id, "processing")}
                      className="px-2 py-1 border rounded text-sm hover:bg-gray-50"
                      title="Отметить как в работе"
                    >
                      В работе
                    </button>
                    <button
                      onClick={() => changeStatus(o.id, "sent")}
                      className="px-2 py-1 border rounded text-sm hover:bg-gray-50"
                      title="Отправить"
                    >
                      Отправлено
                    </button>
                    <button
                      onClick={() => changeStatus(o.id, "delivered")}
                      className="px-2 py-1 border rounded text-sm hover:bg-gray-50"
                      title="Доставлено в пункт выдачи"
                    >
                      Доставлено
                    </button>
                    <button
                      onClick={() => changeStatus(o.id, "received")}
                      className="px-2 py-1 border rounded text-sm hover:bg-gray-50"
                      title="Клиент получил"
                    >
                      Получено
                    </button>
                    <button
                      onClick={() => changeStatus(o.id, "cancelled")}
                      className="px-2 py-1 border rounded text-sm text-red-600 hover:bg-gray-50"
                      title="Отменить"
                    >
                      Отменить
                    </button>
                    <a
                      href={`/api/admin/orders/${o.id}`}
                      className="px-2 py-1 border rounded text-sm"
                      title="Открыть"
                    >
                      Открыть
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
