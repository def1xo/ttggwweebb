import React, { useEffect, useMemo, useState } from "react";
import api, { adminLogin, createAdminNews, createAdminSupplierSource, deleteAdminNews, deleteAdminSupplierSource, getAdminAnalyticsFunnel, getAdminAnalyticsTopProducts, getAdminNews, getAdminOpsNeedsAttention, getAdminStats, getAdminSupplierSources, patchAdminNews, patchAdminSupplierSource, sendAdminCatalogToTelegram, sendAdminSalesExportToTelegram, sendOrderProofToTelegram, triggerSupplierAutoImportNow } from "../services/api";
import SalesChart from "../components/SalesChart";
import AdminManagersView from "../components/AdminManagersView";
import AdminProductManager from "../components/AdminProductManager";
import AdminCategoryManager from "../components/AdminCategoryManager";

type RangeKey = "week" | "month" | "all";

type SeriesPoint = { date: string; amount: number; count?: number };

type MonthSummary = {
  orders_count: number;
  revenue_gross: number;
  cogs_estimated: number;
  profit_estimated: number;
  margin_percent: number;
};

type AdminStats = {
  range: RangeKey;
  series: SeriesPoint[];
  month: MonthSummary;
};

type AnalyticsFunnel = {
  days: number;
  counts: {
    view_product: number;
    add_to_cart: number;
    begin_checkout: number;
    purchase: number;
  };
  conversion: {
    view_to_cart_percent: number;
    cart_to_checkout_percent: number;
    checkout_to_purchase_percent: number;
    view_to_purchase_percent: number;
  };
};


type AnalyticsTopProduct = {
  product_id: number;
  title: string;
  view_product: number;
  add_to_cart: number;
  purchase: number;
  add_rate_percent: number;
  purchase_rate_percent: number;
};


type OpsNeedsAttention = {
  generated_at: string;
  thresholds: { low_stock_threshold: number; stale_order_hours: number; include_low_stock?: boolean };
  severity_score: number;
  counts: {
    stale_orders: number;
    stale_orders_without_proof: number;
    products_missing_data: number;
    low_stock_variants: number;
  };
  items: {
    stale_orders: Array<{ order_id: number; created_at?: string | null; hours_waiting: number; total_amount: number; fio?: string | null; has_payment_proof: boolean }>;
    products_missing_data: Array<{ product_id: number; title: string; visible: boolean; reasons: string[] }>;
    low_stock_variants: Array<{ variant_id: number; product_id: number; title: string; stock_quantity: number; is_out: boolean }>;
  };
  queue: Array<{
    type: "stale_order" | "product_card" | "low_stock" | string;
    priority: number;
    title: string;
    subtitle: string;
    recommended_action: string;
    meta?: Record<string, any>;
  }>;
};

const DEFAULT_SUPPLIER_SOURCE_LINKS = [
  "https://docs.google.com/spreadsheets/d/1Pv_iyCw5WCbBHXvhdH5w7pRjxfsjTbCm3SjHPElC_wA/edit?usp=sharing",
  "https://docs.google.com/spreadsheets/d/1JQ5p32JknAm34W42fiTXzAFKYOhb9QEcMFAwSernwI4/htmlview",
  "https://docs.google.com/spreadsheets/d/1Xfjpx1Bs9GDUlgKalrzzm3u2M6dpxwuHZQwCqihjw2Q/htmlview",
  "https://docs.google.com/spreadsheets/d/1wfZJPJMO34WfcbGNxP-IWl5w0V1vEDf6FHakAqoJsBw/htmlview",
  "https://docs.google.com/spreadsheets/d/1fvLjH86AAD2upGbQ9npo-mtUbFAsl3cmx8wDIczTCeE/htmlview",
  "https://b2b.moysklad.ru/public/oWXBoG49bkuB/catalog",
  "https://t.me/firmachdroppp",
  "https://t.me/optobaza",
  "https://t.me/venomopt12",
  "https://t.me/shop_vkus",
];

type ViewKey =
  | "dashboard"
  | "orders"
  | "withdraws"
  | "products"
  | "categories"
  | "managers"
  | "payment"
  | "promos"
  | "suppliers"
  | "news";

function formatRub(n: number) {
  const v = Number.isFinite(n) ? n : 0;
  return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 }).format(v);
}

function Segmented({ value, onChange }: { value: RangeKey; onChange: (v: RangeKey) => void }) {
  const items: Array<{ k: RangeKey; label: string }> = [
    { k: "week", label: "Неделя" },
    { k: "month", label: "Месяц" },
    { k: "all", label: "Все время" },
  ];
  return (
    <div className="card" style={{ padding: 6, display: "flex", gap: 6 }}>
      {items.map((it) => (
        <button
          key={it.k}
          className={"btn " + (value === it.k ? "btn-primary" : "btn-secondary")}
          style={{ flex: 1, padding: "10px 12px" }}
          onClick={() => onChange(it.k)}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

function AdminLoginGate({ onAuthed }: { onAuthed: () => void }) {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [me, setMe] = useState<any>(null);

  useEffect(() => {
    let mounted = true;
    api
      .getMyProfile()
      .then((d: any) => mounted && setMe(d))
      .catch(() => void 0);
    return () => {
      mounted = false;
    };
  }, []);

  const handleLogin = async () => {
    setError(null);
    setLoading(true);
    try {
      const userId = Number(me?.telegram_id ?? me?.id);
      if (!userId) {
        setError("Не удалось определить user_id (Telegram). Открой вебапп из Telegram.");
        setLoading(false);
        return;
      }
      const res: any = await adminLogin(userId, password);
      if (res?.access_token) {
        localStorage.setItem("admin_token", res.access_token);
        onAuthed();
        setLoading(false);
        return;
      }
      setError(res?.detail || "Не удалось войти");
    } catch (e: any) {
      setError(e?.message || "Ошибка входа");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container" style={{ paddingTop: 12, maxWidth: 540 }}>
      <div className="card" style={{ padding: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>Админ-панель</div>
          <div style={{ color: "var(--muted)", fontSize: 13 }}>
            Для входа введи пароль администратора.
            {me?.username ? ` (Вы: @${me.username})` : ""}
          </div>
          <input
            className="input"
            type="password"
            placeholder="Пароль"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleLogin();
            }}
          />
          {error ? <div className="card" style={{ padding: 10, borderColor: "#a33" }}>{error}</div> : null}
          <button className="btn btn-primary" disabled={loading || !password} onClick={handleLogin}>
            {loading ? "Входим…" : "Войти"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AdminOrdersPanel({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const STATUSES = ["", "awaiting_payment", "paid", "processing", "sent", "received", "delivered", "cancelled"];

  const normStatus = (s: any) => {
    if (!s) return "";
    const raw = String(s);
    return (raw.split(".").pop() || raw).trim();
  };

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const params: any = { limit: 50, offset: 0 };
      if (statusFilter) params.status = statusFilter;
      const res: any = await api.getAdminOrders(params);
      if (Array.isArray(res)) {
        const nextItems = statusFilter ? res : res.filter((o: any) => normStatus(o?.status) !== "received");
        setItems(nextItems);
        setLoading(false);
        return;
      }
      if (res?.status === 401) {
        localStorage.removeItem("admin_token");
        setError("Сессия истекла. Перезайди.");
        setLoading(false);
        return;
      }
      setError(res?.detail || "Не удалось загрузить заказы");
      setLoading(false);
    } catch (e: any) {
      setError(e?.message || "Ошибка загрузки заказов");
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  const sendProofToTelegram = async (orderId: number, proofUrl?: string) => {
    try {
      await sendOrderProofToTelegram(orderId, window.location.origin);
      if (proofUrl) {
        try { window.open(String(proofUrl), "_blank", "noopener,noreferrer"); } catch {}
      }
      setActionMsg(`Чек заказа #${orderId}: открыл и отправил ссылку в Telegram ✅`);
    } catch (e: any) {
      setActionMsg(e?.message || "Не удалось отправить чек в Telegram");
    }
  };

  const updateStatus = async (id: number, status: string) => {
    if (!confirm(`Поменять статус заказа #${id} на "${status}"?`)) return;
    try {
      await api.post(`/api/admin/orders/${id}/status`, { status });
      setActionMsg(`Статус заказа #${id} обновлён: ${status}`);
      load();
    } catch (e: any) {
      setActionMsg(e?.response?.data?.detail || e?.message || "Не удалось изменить статус");
    }
  };

  const confirmPayment = async (id: number) => {
    if (!confirm(`Подтвердить оплату заказа #${id}?`)) return;
    try {
      await api.post(`/api/admin/orders/${id}/confirm_payment`, {});
      setActionMsg(`Оплата подтверждена для заказа #${id}`);
      load();
    } catch (e: any) {
      setActionMsg(e?.response?.data?.detail || e?.message || "Не удалось подтвердить оплату");
    }
  };

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <button className="btn btn-secondary" onClick={onBack}>
          ← Назад
        </button>
        <div style={{ fontWeight: 700 }}>Заказы</div>
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", maxWidth: 520 }}>
          {STATUSES.map((s) => {
            const active = statusFilter === s;
            const label = s || "Все статусы";
            return (
              <button
                key={s || "all"}
                className="btn"
                style={{
                  padding: "8px 10px",
                  border: active ? "1px solid var(--ring)" : undefined,
                  background: active ? "rgba(255,255,255,0.08)" : undefined,
                }}
                onClick={() => setStatusFilter(s)}
                type="button"
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {actionMsg ? <div className="card" style={{ padding: 12, marginBottom: 12 }}>{actionMsg}</div> : null}
      {loading ? <div className="card" style={{ padding: 14 }}>Загрузка…</div> : null}
      {error ? <div className="card" style={{ padding: 14, borderColor: "#a33" }}>{error}</div> : null}

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="table" style={{ minWidth: 980 }}>
          <thead>
            <tr>
              <th>ID</th>
              <th>Статус</th>
              <th>Сумма</th>
              <th>ФИО</th>
              <th>Дата</th>
              <th>Чек</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ padding: 14, color: "var(--muted)" }}>Пусто</td>
              </tr>
            ) : null}
            {items.map((o) => {
              const st = normStatus(o.status);
              return (
                <tr key={o.id}>
                  <td>{o.id}</td>
                  <td>{st}</td>
                  <td>{o.total_amount ? formatRub(Number(o.total_amount)) : "—"}</td>
                  <td>{o.fio || "—"}</td>
                  <td>{o.created_at ? new Date(o.created_at).toLocaleString("ru-RU") : "—"}</td>
                  <td>
                    {o.payment_screenshot ? (
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        <a href={String(o.payment_screenshot)} target="_blank" rel="noreferrer" className="btn ghost">
                          Открыть
                        </a>
                        <button className="btn ghost" onClick={() => sendProofToTelegram(Number(o.id), String(o.payment_screenshot))}>
                          Скачать
                        </button>
                      </div>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {st === "paid" ? (
                      <button className="btn btn-primary" onClick={() => confirmPayment(o.id)}>
                        Подтвердить оплату
                      </button>
                    ) : null}
                    <button className="btn btn-secondary" onClick={() => updateStatus(o.id, "processing")}>В работе</button>
                    <button className="btn btn-secondary" onClick={() => updateStatus(o.id, "sent")}>Отправлено</button>
                    <button className="btn btn-secondary" onClick={() => updateStatus(o.id, "delivered")}>Доставлено</button>
                    <button className="btn btn-secondary" onClick={() => updateStatus(o.id, "received")}>Получено</button>
                    <button className="btn btn-secondary" onClick={() => updateStatus(o.id, "cancelled")}>Отмена</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AdminWithdrawsPanel({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res: any = await api.getAdminWithdraws();
      if (res?.items && Array.isArray(res.items)) {
        setItems(res.items);
        setLoading(false);
        return;
      }
      if (res?.status === 401) {
        localStorage.removeItem("admin_token");
        setError("Сессия истекла. Перезайди.");
        setLoading(false);
        return;
      }
      setError(res?.detail || "Не удалось загрузить выплаты");
      setLoading(false);
    } catch (e: any) {
      setError(e?.message || "Ошибка загрузки выплат");
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const act = async (id: number, approve: boolean) => {
    try {
      const res: any = await api.approveWithdraw(id, approve);
      if (res?.ok) {
        load();
        return;
      }
      alert(res?.detail || "Ошибка");
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  };

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <button className="btn btn-secondary" onClick={onBack}>
          ← Назад
        </button>
        <div style={{ fontWeight: 700 }}>Выплаты</div>
        <div style={{ flex: 1 }} />
        <button className="btn btn-secondary" onClick={load}>
          Обновить
        </button>
      </div>

      {loading ? <div className="card" style={{ padding: 14 }}>Загрузка…</div> : null}
      {error ? <div className="card" style={{ padding: 14, borderColor: "#a33" }}>{error}</div> : null}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map((w) => (
          <div key={w.id} className="card" style={{ padding: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
              <div>
                <div style={{ fontWeight: 700 }}>#{w.id} • {formatRub(Number(w.amount || 0))}</div>
                <div style={{ color: "var(--muted)", fontSize: 12 }}>
                  Статус: {w.status} • {w.created_at ? new Date(w.created_at).toLocaleString("ru-RU") : ""}
                </div>
                <div style={{ color: "var(--muted)", fontSize: 12 }}>User: {w.requester_user_id} • Manager: {w.manager_user_id}</div>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {w.status === "pending" ? (
                  <>
                    <button className="btn btn-primary" onClick={() => act(w.id, true)}>Одобрить</button>
                    <button className="btn btn-secondary" onClick={() => act(w.id, false)}>Отклонить</button>
                  </>
                ) : null}
              </div>
            </div>
            {w.target_details ? (
              <div style={{ marginTop: 8, fontSize: 12, whiteSpace: "pre-wrap", color: "var(--muted)" }}>
                {typeof w.target_details === "string" ? w.target_details : JSON.stringify(w.target_details, null, 2)}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function AdminPaymentSettingsPanel({ onBack }: { onBack: () => void }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [form, setForm] = useState<{ recipient_name: string; phone: string; card_number: string; bank_name: string; note: string; updated_at?: string | null }>(
    { recipient_name: "", phone: "", card_number: "", bank_name: "", note: "", updated_at: null }
  );

  const load = async () => {
    setLoading(true);
    setError(null);
    setMsg(null);
    try {
      const res: any = await api.getAdminPaymentSettings();
      if (res?.status === 401) {
        localStorage.removeItem("admin_token");
        setError("Сессия истекла. Перезайди.");
        setLoading(false);
        return;
      }
      if (res?.detail && !res?.recipient_name && !res?.phone && !res?.card_number && !res?.bank_name) {
        setError(res.detail);
        setLoading(false);
        return;
      }
      setForm({
        recipient_name: res?.recipient_name || "",
        phone: res?.phone || "",
        card_number: res?.card_number || "",
        bank_name: res?.bank_name || "",
        note: res?.note || "",
        updated_at: res?.updated_at || null,
      });
      setLoading(false);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить реквизиты");
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    setMsg(null);
    try {
      const payload: any = {
        recipient_name: form.recipient_name,
        phone: form.phone,
        card_number: form.card_number,
        bank_name: form.bank_name,
        note: form.note,
      };
      const res: any = await api.patchAdminPaymentSettings(payload);
      if (res?.status === 401) {
        localStorage.removeItem("admin_token");
        setError("Сессия истекла. Перезайди.");
        setSaving(false);
        return;
      }
      if (res?.detail) {
        setError(res.detail);
        setSaving(false);
        return;
      }
      setForm((p) => ({ ...p, updated_at: res?.updated_at || p.updated_at }));
      setMsg("Сохранено ✅");
    } catch (e: any) {
      setError(e?.message || "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="container" style={{ paddingTop: 12, maxWidth: 720 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <button className="btn btn-secondary" onClick={onBack}>
          ← Назад
        </button>
        <div style={{ fontWeight: 700 }}>Реквизиты оплаты</div>
        <div style={{ flex: 1 }} />

      </div>

      {loading ? <div className="card" style={{ padding: 14 }}>Загрузка…</div> : null}
      {error ? <div className="card" style={{ padding: 14, borderColor: "#a33" }}>{error}</div> : null}
      {msg ? <div className="card" style={{ padding: 12 }}>{msg}</div> : null}

      {!loading ? (
        <div className="card" style={{ padding: 14, display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ color: "var(--muted)", fontSize: 12 }}>
            Эти реквизиты показываются пользователю при оформлении заказа.
            {form.updated_at ? ` Последнее обновление: ${new Date(form.updated_at).toLocaleString("ru-RU")}` : ""}
          </div>

          <label style={{ fontSize: 12, color: "var(--muted)" }}>Получатель (ФИО)</label>
          <input className="input" value={form.recipient_name} onChange={(e) => setForm((p) => ({ ...p, recipient_name: e.target.value }))} />

          <label style={{ fontSize: 12, color: "var(--muted)" }}>Телефон</label>
          <input className="input" value={form.phone} onChange={(e) => setForm((p) => ({ ...p, phone: e.target.value }))} />

          <label style={{ fontSize: 12, color: "var(--muted)" }}>Номер карты</label>
          <input className="input" value={form.card_number} onChange={(e) => setForm((p) => ({ ...p, card_number: e.target.value }))} />

          <label style={{ fontSize: 12, color: "var(--muted)" }}>Банк</label>
          <input className="input" value={form.bank_name} onChange={(e) => setForm((p) => ({ ...p, bank_name: e.target.value }))} />

          <label style={{ fontSize: 12, color: "var(--muted)" }}>Примечание (инструкция)</label>
          <textarea
            className="input"
            rows={4}
            value={form.note}
            onChange={(e) => setForm((p) => ({ ...p, note: e.target.value }))}
            style={{ resize: "vertical" }}
          />

          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? "Сохраняю…" : "Сохранить"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

type PromoRow = {
  id: number;
  code: string;
  value: number;
  currency?: string;
  expires_at?: string | null;
  usage_limit?: number | null;
  used_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
};


function toLocalDateInput(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function toLocalTimeInput(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function mergeDateTimeToIso(datePart: string, timePart: string): string | null {
  if (!datePart) return null;
  const t = timePart || "23:59";
  const local = new Date(`${datePart}T${t}:00`);
  if (Number.isNaN(local.getTime())) return null;
  return local.toISOString();
}

function plusDaysLocal(datePart: string, days: number): string {
  const base = datePart ? new Date(`${datePart}T12:00:00`) : new Date();
  if (Number.isNaN(base.getTime())) return toLocalDateInput(new Date().toISOString());
  base.setDate(base.getDate() + days);
  return toLocalDateInput(base.toISOString());
}

type DateTimeEditorProps = {
  value?: string | null;
  onChange: (nextIso: string | null) => void;
};

function DateTimeEditor({ value, onChange }: DateTimeEditorProps) {
  const [datePart, setDatePart] = useState(() => toLocalDateInput(value));
  const [timePart, setTimePart] = useState(() => toLocalTimeInput(value));

  useEffect(() => {
    setDatePart(toLocalDateInput(value));
    setTimePart(toLocalTimeInput(value));
  }, [value]);

  const apply = (d: string, t: string) => {
    setDatePart(d);
    setTimePart(t);
    onChange(mergeDateTimeToIso(d, t));
  };

  return (
    <div className="promo-datetime-editor">
      <div className="promo-datetime-grid">
        <input
          className="input"
          type="date"
          value={datePart}
          onChange={(e) => apply(e.target.value, timePart)}
        />
        <input
          className="input"
          type="time"
          value={timePart}
          onChange={(e) => apply(datePart, e.target.value)}
        />
      </div>
      <div className="promo-chip-row">
        <button type="button" className="chip" onClick={() => apply(datePart || toLocalDateInput(new Date().toISOString()), "12:00")}>12:00</button>
        <button type="button" className="chip" onClick={() => apply(datePart || toLocalDateInput(new Date().toISOString()), "18:00")}>18:00</button>
        <button type="button" className="chip" onClick={() => apply(datePart || toLocalDateInput(new Date().toISOString()), "23:59")}>23:59</button>
      </div>
      <div className="promo-chip-row">
        <button type="button" className="chip" onClick={() => apply(plusDaysLocal(datePart, 1), timePart || "23:59")}>+1 день</button>
        <button type="button" className="chip" onClick={() => apply(plusDaysLocal(datePart, 3), timePart || "23:59")}>+3 дня</button>
        <button type="button" className="chip" onClick={() => apply(plusDaysLocal(datePart, 7), timePart || "23:59")}>+7 дней</button>
        <button type="button" className="chip" onClick={() => apply("", "")}>Без срока</button>
      </div>
    </div>
  );
}

function AdminPromosPanel({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<PromoRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState<string>("");
  const [msg, setMsg] = useState<string | null>(null);

  const [createForm, setCreateForm] = useState<{ code: string; value: string; expires_at: string; usage_limit: string }>(
    { code: "", value: "", expires_at: "", usage_limit: "" }
  );
  const [creating, setCreating] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    setMsg(null);
    try {
      const res: any = await api.getAdminPromos(q ? { q } : undefined);
      if (res?.status === 401) {
        localStorage.removeItem("admin_token");
        setError("Сессия истекла. Перезайди.");
        setLoading(false);
        return;
      }
      if (res?.detail) {
        setError(res.detail);
        setLoading(false);
        return;
      }
      if (Array.isArray(res)) {
        const nextItems = statusFilter ? res : res.filter((o: any) => normStatus(o?.status) !== "received");
        setItems(nextItems);
        setLoading(false);
        return;
      }
      setError("Не удалось загрузить промокоды");
      setLoading(false);
    } catch (e: any) {
      setError(e?.message || "Не удалось загрузить промокоды");
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const create = async () => {
    const code = createForm.code.trim();
    const v = Number(String(createForm.value).replace(",", "."));
    if (!code) return setMsg("Нужен код");
    if (!Number.isFinite(v) || v < 0) return setMsg("Неверное значение скидки");
    setCreating(true);
    setMsg(null);
    setError(null);
    try {
      const payload: any = { code, value: v, currency: "RUB" };
      if (createForm.expires_at) payload.expires_at = new Date(createForm.expires_at).toISOString();
      if (createForm.usage_limit) {
        const ul = Number(createForm.usage_limit);
        if (Number.isFinite(ul) && ul > 0) payload.usage_limit = ul;
      }
      const res: any = await api.createAdminPromo(payload);
      if (res?.detail) {
        setError(res.detail);
        setCreating(false);
        return;
      }
      setMsg("Создано ✅");
      setCreateForm({ code: "", value: "", expires_at: "", usage_limit: "" });
      await load();
    } catch (e: any) {
      setError(e?.message || "Не удалось создать");
    } finally {
      setCreating(false);
    }
  };

  const updateRow = (id: number, patch: Partial<PromoRow>) => {
    setItems((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  };

  const patchOne = async (row: PromoRow) => {
    setMsg(null);
    setError(null);
    try {
      const payload: any = {
        code: row.code,
        value: Number(row.value),
        currency: row.currency || "RUB",
      };
      payload.expires_at = row.expires_at ? row.expires_at : null;
      payload.usage_limit = row.usage_limit != null ? row.usage_limit : null;
      const res: any = await api.patchAdminPromo(row.id, payload);
      if (res?.detail) {
        setError(res.detail);
        return;
      }
      setMsg(`Сохранено #${row.id} ✅`);
      await load();
    } catch (e: any) {
      setError(e?.message || "Не удалось сохранить");
    }
  };

  const del = async (id: number, code: string) => {
    if (!confirm(`Удалить промокод ${code} (#${id})?`)) return;
    setMsg(null);
    setError(null);
    try {
      const res: any = await api.deleteAdminPromo(id);
      if (res?.detail) {
        setError(res.detail);
        return;
      }
      setMsg("Удалено ✅");
      await load();
    } catch (e: any) {
      setError(e?.message || "Не удалось удалить");
    }
  };

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        <button className="btn btn-secondary" onClick={onBack}>
          ← Назад
        </button>
        <div style={{ fontWeight: 700 }}>Спец‑промокоды</div>
        <div style={{ flex: 1 }} />
        <input className="input" placeholder="Поиск по коду" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 220 }} />

      </div>

      {loading ? <div className="card" style={{ padding: 14 }}>Загрузка…</div> : null}
      {error ? <div className="card" style={{ padding: 14, borderColor: "#a33" }}>{error}</div> : null}
      {msg ? <div className="card" style={{ padding: 12 }}>{msg}</div> : null}

      <div className="card" style={{ padding: 14, marginBottom: 12 }}>
        <div style={{ fontWeight: 700, marginBottom: 10 }}>Создать</div>
        <div className="promo-create-grid">
          <input className="input" placeholder="CODE" value={createForm.code} onChange={(e) => setCreateForm((p) => ({ ...p, code: e.target.value }))} />
          <input className="input" placeholder="Скидка (например 10)" value={createForm.value} onChange={(e) => setCreateForm((p) => ({ ...p, value: e.target.value }))} />
          <input className="input" placeholder="Usage limit (опц.)" value={createForm.usage_limit} onChange={(e) => setCreateForm((p) => ({ ...p, usage_limit: e.target.value }))} />
          <DateTimeEditor
            value={createForm.expires_at || null}
            onChange={(nextIso) => setCreateForm((p) => ({ ...p, expires_at: nextIso || "" }))}
          />
        </div>
        <button className="btn btn-primary" style={{ marginTop: 10 }} onClick={create} disabled={creating}>
          {creating ? "Создаю…" : "Создать"}
        </button>
      </div>

      <div className="card promo-table-wrap" style={{ padding: 0, overflowX: "auto" }}>
        <table className="table" style={{ minWidth: 980 }}>
          <thead>
            <tr>
              <th>ID</th>
              <th>CODE</th>
              <th>Скидка</th>
              <th>Expires</th>
              <th>Limit</th>
              <th>Used</th>
              <th>Действия</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ padding: 14, color: "var(--muted)" }}>
                  Пусто
                </td>
              </tr>
            ) : null}
            {items.map((p) => (
              <tr key={p.id}>
                <td>{p.id}</td>
                <td style={{ minWidth: 180 }}>
                  <input className="input" value={p.code} onChange={(e) => updateRow(p.id, { code: e.target.value })} />
                </td>
                <td style={{ minWidth: 140 }}>
                  <input
                    className="input"
                    value={String(p.value ?? "")}
                    onChange={(e) => updateRow(p.id, { value: Number(String(e.target.value).replace(",", ".")) })}
                  />
                </td>
                <td style={{ minWidth: 220 }}>
                  <DateTimeEditor
                    value={p.expires_at || null}
                    onChange={(nextIso) => updateRow(p.id, { expires_at: nextIso })}
                  />
                </td>
                <td style={{ minWidth: 120 }}>
                  <input
                    className="input"
                    value={p.usage_limit == null ? "" : String(p.usage_limit)}
                    onChange={(e) => {
                      const v = e.target.value.trim();
                      updateRow(p.id, { usage_limit: v ? Number(v) : null });
                    }}
                  />
                </td>
                <td>{p.used_count ?? 0}</td>
                <td style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button className="btn btn-primary" onClick={() => patchOne(p)}>
                    Сохранить
                  </button>
                  <button className="btn btn-secondary" onClick={() => del(p.id, p.code)}>
                    Удалить
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="promo-mobile-list">
        {items.length === 0 ? (
          <div className="card" style={{ padding: 14, color: "var(--muted)" }}>Пусто</div>
        ) : null}
        {items.map((p) => (
          <div key={`mobile_${p.id}`} className="card" style={{ padding: 12, marginBottom: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", marginBottom: 8 }}>
              <div style={{ fontWeight: 800 }}>#{p.id}</div>
              <div className="small-muted">исп: {p.used_count ?? 0}</div>
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              <input className="input" value={p.code} onChange={(e) => updateRow(p.id, { code: e.target.value })} placeholder="CODE" />
              <input className="input" value={String(p.value ?? "")} onChange={(e) => updateRow(p.id, { value: Number(String(e.target.value).replace(",", ".")) })} placeholder="Скидка" />
              <DateTimeEditor value={p.expires_at || null} onChange={(nextIso) => updateRow(p.id, { expires_at: nextIso })} />
              <input
                className="input"
                value={p.usage_limit == null ? "" : String(p.usage_limit)}
                onChange={(e) => {
                  const v = e.target.value.trim();
                  updateRow(p.id, { usage_limit: v ? Number(v) : null });
                }}
                placeholder="Usage limit"
              />
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn btn-primary" onClick={() => patchOne(p)} style={{ flex: 1 }}>Сохранить</button>
                <button className="btn btn-secondary" onClick={() => del(p.id, p.code)} style={{ flex: 1 }}>Удалить</button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


function AdminSupplierSourcesPanel({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [supplierName, setSupplierName] = useState("");
  const [managerName, setManagerName] = useState("");
  const [managerContact, setManagerContact] = useState("");
  const [note, setNote] = useState("");
  const [autoImporting, setAutoImporting] = useState(false);
  const [lastImportReport, setLastImportReport] = useState<any | null>(null);

  const resetForm = () => {
    setEditingId(null);
    setSourceUrl("");
    setSupplierName("");
    setManagerName("");
    setManagerContact("");
    setNote("");
  };

  const load = async () => {
    setLoading(true);
    setMsg(null);
    try {
      const res: any = await getAdminSupplierSources();
      setItems(Array.isArray(res) ? res : []);
    } catch (e: any) {
      setMsg(e?.message || "Не удалось загрузить источники");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const saveSource = async () => {
    if (!sourceUrl.trim()) return;
    try {
      const payload = {
        source_url: sourceUrl.trim(),
        supplier_name: supplierName.trim() || undefined,
        manager_name: managerName.trim() || undefined,
        manager_contact: managerContact.trim() || undefined,
        note: note.trim() || undefined,
      };
      if (editingId) {
        await patchAdminSupplierSource(editingId, payload);
        setMsg("Источник обновлён ✅");
      } else {
        await createAdminSupplierSource(payload);
        setMsg("Источник добавлен ✅");
      }
      resetForm();
      load();
    } catch (e: any) {
      setMsg(e?.message || "Не удалось сохранить источник");
    }
  };

  const startEdit = (it: any) => {
    setEditingId(Number(it.id));
    setSourceUrl(String(it.source_url || ""));
    setSupplierName(String(it.supplier_name || ""));
    setManagerName(String(it.manager_name || ""));
    setManagerContact(String(it.manager_contact || ""));
    setNote(String(it.note || ""));
    setMsg(`Редактирование #${it.id}`);
  };

  const delSource = async (id: number) => {
    if (!confirm(`Удалить источник #${id}?`)) return;
    try {
      await deleteAdminSupplierSource(id);
      if (editingId === id) resetForm();
      setMsg("Источник удалён");
      load();
    } catch (e: any) {
      setMsg(e?.message || "Не удалось удалить источник");
    }
  };

  const seedDefaultSources = async () => {
    try {
      let created = 0;
      let skipped = 0;
      for (const source_url of DEFAULT_SUPPLIER_SOURCE_LINKS) {
        try {
          await createAdminSupplierSource({ source_url, note: "seed: стартовый набор источников" });
          created += 1;
        } catch {
          skipped += 1;
        }
      }
      setMsg(`Стартовые источники: +${created} новых, ${skipped} уже были`);
      load();
    } catch (e: any) {
      setMsg(e?.message || "Не удалось добавить стартовые источники");
    }
  };

  const runAutoImportNow = async () => {
    try {
      setAutoImporting(true);
      setLastImportReport(null);
      const res: any = await triggerSupplierAutoImportNow();
      const created = Number(res?.created_products || 0);
      const updated = Number(res?.updated_products || 0);
      const variants = Number(res?.created_variants || 0);
      const categories = Number(res?.created_categories || 0);
      const errCount = Array.isArray(res?.source_reports)
        ? res.source_reports.reduce((acc: number, x: any) => acc + Number(x?.errors || 0), 0)
        : 0;
      setLastImportReport(res || null);
      setMsg(`Импорт завершён ✅ Категории +${categories}, товары +${created}, обновлено ${updated}, варианты +${variants}${errCount ? `, ошибок: ${errCount}` : ""}`);
    } catch (e: any) {
      setMsg(e?.message || "Не удалось запустить автоимпорт");
    } finally {
      setAutoImporting(false);
    }
  };

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <button className="btn btn-secondary" onClick={onBack}>← Назад</button>
        <div style={{ fontWeight: 700 }}>Поставщики / Источники</div>
      </div>

      {msg ? <div className="card" style={{ padding: 12, marginBottom: 12 }}>{msg}</div> : null}

      <div className="card" style={{ padding: 12, marginBottom: 12, display: "grid", gap: 8 }}>
        <div style={{ fontWeight: 800 }}>{editingId ? `Редактировать источник #${editingId}` : "Добавить источник"}</div>
        <input className="input" placeholder="Ссылка на таблицу/сайт/канал" value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} />
        <input className="input" placeholder="Название поставщика (опционально)" value={supplierName} onChange={(e) => setSupplierName(e.target.value)} />
        <input className="input" placeholder="Менеджер (как подписать)" value={managerName} onChange={(e) => setManagerName(e.target.value)} />
        <input className="input" placeholder="Контакт менеджера (tg/link/phone)" value={managerContact} onChange={(e) => setManagerContact(e.target.value)} />
        <input className="input" placeholder="Комментарий" value={note} onChange={(e) => setNote(e.target.value)} />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-primary" onClick={saveSource} disabled={!sourceUrl.trim()}>{editingId ? "Сохранить" : "Добавить"}</button>
          {editingId ? <button className="btn btn-secondary" onClick={resetForm}>Отмена</button> : null}
          <button className="btn btn-secondary" onClick={seedDefaultSources}>Добавить стартовый набор</button>
        </div>
      </div>

      <div className="card" style={{ padding: 12, marginBottom: 12, display: "grid", gap: 8 }}>
        <div style={{ fontWeight: 800 }}>Автообновление и автоимпорт</div>
        <div className="small-muted">Автоматический импорт настроен раз в 24 часа. Можно запустить вручную.</div>
        <button className="btn" onClick={runAutoImportNow} disabled={autoImporting || items.length === 0}>
          {autoImporting ? "Запускаем..." : "Обновить и импортировать сейчас"}
        </button>
      </div>

      {lastImportReport ? (
        <div className="card" style={{ padding: 12, marginBottom: 12, display: "grid", gap: 10 }}>
          <div style={{ fontWeight: 800 }}>Последний отчёт импорта</div>
          <div className="small-muted">
            Категории: +{Number(lastImportReport?.created_categories || 0)} • Товары: +{Number(lastImportReport?.created_products || 0)} • Обновлено: {Number(lastImportReport?.updated_products || 0)} • Варианты: +{Number(lastImportReport?.created_variants || 0)}
          </div>
          {Array.isArray(lastImportReport?.source_reports) && lastImportReport.source_reports.length > 0 ? (
            <div style={{ display: "grid", gap: 8 }}>
              {lastImportReport.source_reports.map((r: any, idx: number) => (
                <div key={`${r?.source_id || idx}_${r?.url || ""}`} className="card" style={{ padding: 10 }}>
                  <div style={{ fontWeight: 700, wordBreak: "break-all" }}>{r?.url || `source #${r?.source_id || "?"}`}</div>
                  <div className="small-muted" style={{ marginTop: 4 }}>
                    imported: {Number(r?.imported || 0)} • errors: {Number(r?.errors || 0)}
                  </div>
                  {r?.last_error_message ? <div className="small-muted" style={{ marginTop: 4 }}>Последняя ошибка: {String(r.last_error_message)}</div> : null}
                  {Array.isArray(r?.error_samples) && r.error_samples.length > 0 ? (
                    <div className="small-muted" style={{ marginTop: 4 }}>
                      Примеры: {r.error_samples.slice(0, 2).map((x: any) => String(x)).join(" | ")}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="card" style={{ padding: 12, marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, gap: 10 }}>
          <div style={{ fontWeight: 800 }}>Сохранённые источники</div>
          <button className="btn btn-secondary" onClick={load} disabled={loading}>Обновить</button>
        </div>
        {loading ? <div className="small-muted">Загрузка...</div> : null}
        {items.length === 0 ? <div className="small-muted">Пока пусто</div> : null}
        <div style={{ display: "grid", gap: 8 }}>
          {items.map((it) => (
            <div key={it.id} className="card" style={{ padding: 10 }}>
              <div style={{ fontWeight: 700, wordBreak: "break-all" }}>{it.source_url}</div>
              <div className="small-muted" style={{ marginTop: 4 }}>
                Поставщик: {it.supplier_name || "—"} • Менеджер: {it.manager_name || "—"} • Контакт: {it.manager_contact || "—"}
              </div>
              {it.note ? <div className="small-muted" style={{ marginTop: 4 }}>Комментарий: {it.note}</div> : null}
              <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                <button className="btn btn-secondary" onClick={() => startEdit(it)}>Редактировать</button>
                <button className="btn btn-secondary" onClick={() => delSource(Number(it.id))}>Удалить</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}




function AdminNewsAndCatalogPanel({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [textBody, setTextBody] = useState("");
  const [imagesRaw, setImagesRaw] = useState("");
  const [catalogTemplate, setCatalogTemplate] = useState("#{category}\n{title}\nцена: {price} ₽");
  const [catalogLimit, setCatalogLimit] = useState(100);

  const load = async () => {
    try {
      const res: any = await getAdminNews(200);
      setItems(Array.isArray(res) ? res : []);
    } catch (e: any) {
      setMsg(e?.message || "Не удалось загрузить новости");
    }
  };

  useEffect(() => {
    load();
  }, []);

  const resetForm = () => {
    setEditingId(null);
    setTitle("");
    setTextBody("");
    setImagesRaw("");
  };

  const saveNews = async () => {
    if (!title.trim()) {
      setMsg("У новости должен быть заголовок");
      return;
    }
    const images = imagesRaw
      .split(/\n|,|;/)
      .map((x) => x.trim())
      .filter(Boolean);
    const payload = { title: title.trim(), text: textBody.trim() || undefined, images };
    try {
      if (editingId) {
        await patchAdminNews(editingId, payload);
        setMsg("Новость обновлена ✅");
      } else {
        await createAdminNews(payload);
        setMsg("Новость создана ✅");
      }
      resetForm();
      await load();
    } catch (e: any) {
      setMsg(e?.message || "Не удалось сохранить новость");
    }
  };

  const startEdit = (it: any) => {
    setEditingId(Number(it.id));
    setTitle(String(it.title || ""));
    setTextBody(String(it.text || ""));
    setImagesRaw(Array.isArray(it.images) ? it.images.join("\n") : "");
  };

  const removeNews = async (id: number) => {
    if (!confirm(`Удалить новость #${id}?`)) return;
    try {
      await deleteAdminNews(id);
      if (editingId === id) resetForm();
      setMsg("Новость удалена");
      await load();
    } catch (e: any) {
      setMsg(e?.message || "Не удалось удалить новость");
    }
  };

  const sendCatalog = async () => {
    try {
      const res: any = await sendAdminCatalogToTelegram({
        template: catalogTemplate.trim() || undefined,
        only_visible: true,
        limit: Math.max(1, Math.min(500, Number(catalogLimit) || 100)),
      });
      setMsg(`Каталог отправлен в TG: ${res?.sent || 0}/${res?.total || 0}`);
    } catch (e: any) {
      setMsg(e?.message || "Не удалось отправить каталог в Telegram");
    }
  };

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
        <button className="btn btn-secondary" onClick={onBack}>← Назад</button>
        <div style={{ fontWeight: 700 }}>Новости + выгрузка каталога в TG</div>
      </div>

      {msg ? <div className="card" style={{ padding: 12, marginBottom: 12 }}>{msg}</div> : null}

      <div className="card" style={{ padding: 12, marginBottom: 12, display: "grid", gap: 8 }}>
        <div style={{ fontWeight: 800 }}>{editingId ? `Редактировать новость #${editingId}` : "Создать новость"}</div>
        <input className="input" placeholder="Заголовок" value={title} onChange={(e) => setTitle(e.target.value)} />
        <textarea className="input" style={{ minHeight: 110 }} placeholder="Текст новости" value={textBody} onChange={(e) => setTextBody(e.target.value)} />
        <textarea className="input" style={{ minHeight: 90 }} placeholder="Картинки (ссылки, каждая с новой строки)" value={imagesRaw} onChange={(e) => setImagesRaw(e.target.value)} />
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn btn-primary" onClick={saveNews} disabled={!title.trim()}>{editingId ? "Сохранить" : "Создать"}</button>
          {editingId ? <button className="btn btn-secondary" onClick={resetForm}>Отмена</button> : null}
        </div>
      </div>

      <div className="card" style={{ padding: 12, marginBottom: 12, display: "grid", gap: 8 }}>
        <div style={{ fontWeight: 800 }}>Выгрузка каталога в Telegram</div>
        <textarea
          className="input"
          style={{ minHeight: 120 }}
          value={catalogTemplate}
          onChange={(e) => setCatalogTemplate(e.target.value)}
          placeholder={'Шаблон. Доступно: {category}, {title}, {price}, {slug}, {id}'}
        />
        <input className="input" type="number" min={1} max={500} value={catalogLimit} onChange={(e) => setCatalogLimit(Number(e.target.value || 100))} />
        <button className="btn" onClick={sendCatalog}>Отправить каталог в TG канал</button>
      </div>

      <div className="card" style={{ padding: 12 }}>
        <div style={{ fontWeight: 800, marginBottom: 8 }}>Список новостей</div>
        {items.length === 0 ? <div className="small-muted">Пока пусто</div> : null}
        <div style={{ display: "grid", gap: 8 }}>
          {items.map((it) => (
            <div key={it.id} className="card" style={{ padding: 10 }}>
              <div style={{ fontWeight: 700 }}>{it.title}</div>
              {it.text ? <div className="small-muted" style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>{it.text}</div> : null}
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button className="btn btn-secondary" onClick={() => startEdit(it)}>Редактировать</button>
                <button className="btn" onClick={() => removeNews(Number(it.id))}>Удалить</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function AdminDashboard() {
  const [authed, setAuthed] = useState<boolean>(() => Boolean(localStorage.getItem("admin_token")));
  const [range, setRange] = useState<RangeKey>("week");
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loadingStats, setLoadingStats] = useState(false);
  const [statsErr, setStatsErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<SeriesPoint | null>(null);
  const [funnel, setFunnel] = useState<AnalyticsFunnel | null>(null);
  const [funnelErr, setFunnelErr] = useState<string | null>(null);
  const [topProducts, setTopProducts] = useState<AnalyticsTopProduct[]>([]);
  const [topProductsErr, setTopProductsErr] = useState<string | null>(null);
  const [opsQueue, setOpsQueue] = useState<OpsNeedsAttention | null>(null);
  const [opsErr, setOpsErr] = useState<string | null>(null);
  const [opsLimit, setOpsLimit] = useState(8);
  const [opsLowStockThreshold, setOpsLowStockThreshold] = useState(2);
  const [opsStaleHours, setOpsStaleHours] = useState(24);
  const [opsIncludeLowStock, setOpsIncludeLowStock] = useState(false);
  const [view, setView] = useState<ViewKey>("dashboard");

  const loadStats = async (r: RangeKey) => {
    setLoadingStats(true);
    setStatsErr(null);
    try {
      const res: any = await getAdminStats(r);
      if (res?.series && res?.month) {
        setStats(res);
        if (Array.isArray(res.series) && res.series.length) {
          setSelected(res.series[res.series.length - 1]);
        }
        setLoadingStats(false);
        return;
      }
      if (res?.status === 401) {
        localStorage.removeItem("admin_token");
        setAuthed(false);
        setLoadingStats(false);
        return;
      }
      setStatsErr(res?.detail || "Не удалось загрузить статистику");
      setLoadingStats(false);
    } catch (e: any) {
      setStatsErr(e?.message || "Не удалось загрузить статистику");
      setLoadingStats(false);
    }
  };

  const loadFunnel = async () => {
    setFunnelErr(null);
    try {
      const res: any = await getAdminAnalyticsFunnel(30);
      if (res?.counts && res?.conversion) {
        setFunnel(res as AnalyticsFunnel);
        return;
      }
      if (res?.status === 401) {
        localStorage.removeItem("admin_token");
        setAuthed(false);
        return;
      }
      setFunnelErr(res?.detail || "Не удалось загрузить воронку");
    } catch (e: any) {
      setFunnelErr(e?.message || "Не удалось загрузить воронку");
    }
  };

  const loadTopProducts = async () => {
    setTopProductsErr(null);
    try {
      const res: any = await getAdminAnalyticsTopProducts(30, 8);
      const items = Array.isArray(res?.items) ? res.items : [];
      setTopProducts(items as AnalyticsTopProduct[]);
      if (!Array.isArray(res?.items) && res?.status === 401) {
        localStorage.removeItem("admin_token");
        setAuthed(false);
      }
    } catch (e: any) {
      setTopProductsErr(e?.message || "Не удалось загрузить топ товаров");
    }
  };

  const loadOpsQueue = async () => {
    setOpsErr(null);
    try {
      const res: any = await getAdminOpsNeedsAttention(opsLimit, opsLowStockThreshold, opsStaleHours, opsIncludeLowStock);
      if (res?.counts && res?.items) {
        setOpsQueue(res as OpsNeedsAttention);
        return;
      }
      if (res?.status === 401) {
        localStorage.removeItem("admin_token");
        setAuthed(false);
        return;
      }
      setOpsErr(res?.detail || "Не удалось загрузить операционную очередь");
    } catch (e: any) {
      setOpsErr(e?.message || "Не удалось загрузить операционную очередь");
    }
  };

  useEffect(() => {
    if (!authed) return;
    loadStats(range);
    loadFunnel();
    loadTopProducts();
    loadOpsQueue();
  }, [authed, range, opsLimit, opsLowStockThreshold, opsStaleHours, opsIncludeLowStock]);

  const navButtons = useMemo(
    () =>
      [
        { k: "orders" as const, label: "Заказы" },
        { k: "withdraws" as const, label: "Выплаты" },
        { k: "payment" as const, label: "Реквизиты" },
        { k: "promos" as const, label: "Спец‑промокоды" },
        { k: "products" as const, label: "Товары" },
        { k: "categories" as const, label: "Категории" },
        { k: "managers" as const, label: "Менеджеры" },
        { k: "suppliers" as const, label: "Поставщики / источники" },
        { k: "news" as const, label: "Новости + TG каталог" },
      ],
    []
  );

  const exportXlsx = async () => {
    try {
      const res: any = await sendAdminSalesExportToTelegram("month", window.location.origin);
      if (res?.status === 401) {
        localStorage.removeItem("admin_token");
        setAuthed(false);
        return;
      }
      alert("Ссылка на Excel отправлена в Telegram-чат администратора ✅");
    } catch (e: any) {
      alert(e?.message || "Ошибка отправки экспорта в Telegram");
    }
  };



  if (!authed) {
    return <AdminLoginGate onAuthed={() => setAuthed(true)} />;
  }

  if (view === "orders") return <AdminOrdersPanel onBack={() => setView("dashboard")} />;
  if (view === "withdraws") return <AdminWithdrawsPanel onBack={() => setView("dashboard")} />;
  if (view === "payment") return <AdminPaymentSettingsPanel onBack={() => setView("dashboard")} />;
  if (view === "promos") return <AdminPromosPanel onBack={() => setView("dashboard")} />;
  if (view === "products") {
    return (
      <div className="container" style={{ paddingTop: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <button className="btn btn-secondary" onClick={() => setView("dashboard")}>
            ← Назад
          </button>
          <div style={{ fontWeight: 700 }}>Товары</div>
        </div>
        <AdminProductManager />
      </div>
    );
  }

  if (view === "categories") {
    return (
      <div className="container" style={{ paddingTop: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <button className="btn btn-secondary" onClick={() => setView("dashboard")}>
            ← Назад
          </button>
          <div style={{ fontWeight: 700 }}>Категории</div>
        </div>
        <AdminCategoryManager />
      </div>
    );
  }

  if (view === "suppliers") return <AdminSupplierSourcesPanel onBack={() => setView("dashboard")} />;
  if (view === "news") return <AdminNewsAndCatalogPanel onBack={() => setView("dashboard")} />;

  if (view === "managers") {
    return (
      <div className="container" style={{ paddingTop: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <button className="btn btn-secondary" onClick={() => setView("dashboard")}>
            ← Назад
          </button>
          <div style={{ fontWeight: 700 }}>Менеджеры</div>
        </div>
        <AdminManagersView />
      </div>
    );
  }

  const series = stats?.series || [];

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div className="card" style={{ padding: 14, marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <div style={{ fontSize: 18, fontWeight: 800 }}>Dashboard</div>
          <button
            className="btn btn-secondary"
            onClick={() => {
              localStorage.removeItem("admin_token");
              setAuthed(false);
            }}
          >
            Выйти
          </button>
        </div>
        <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 6 }}>
          График показывает <b>грязную выручку</b> (без вычета комиссий и закупа).
        </div>
      </div>

      <Segmented value={range} onChange={setRange} />

      <div className="card" style={{ padding: 14, marginTop: 12 }}>
        {loadingStats ? <div style={{ color: "var(--muted)" }}>Загрузка статистики…</div> : null}
        {statsErr ? <div style={{ color: "#ff8c8c" }}>{statsErr}</div> : null}

        <SalesChart
          data={series.map((p) => ({ date: p.date, amount: p.amount }))}
          height={260}
          selectedDate={selected?.date || null}
          onSelect={(p: any) => setSelected({ date: p.date, amount: Number(p.amount) })}
        />

        {selected ? (
          <div className="card" style={{ padding: 12, marginTop: 12 }}>
            <div style={{ fontWeight: 700 }}>{new Date(selected.date).toLocaleDateString("ru-RU")}</div>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>Выручка</div>
            <div style={{ fontSize: 18, fontWeight: 800 }}>{formatRub(Number(selected.amount || 0))}</div>
          </div>
        ) : null}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10, marginTop: 12 }}>
        <div className="card" style={{ padding: 12 }}>
          <div style={{ color: "var(--muted)", fontSize: 12 }}>Заказов за месяц</div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>{stats?.month.orders_count ?? 0}</div>
        </div>
        <div className="card" style={{ padding: 12 }}>
          <div style={{ color: "var(--muted)", fontSize: 12 }}>Выручка (мес.)</div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>{formatRub(stats?.month.revenue_gross ?? 0)}</div>
        </div>
        <div className="card" style={{ padding: 12 }}>
          <div style={{ color: "var(--muted)", fontSize: 12 }}>Закуп (оценка)</div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>{formatRub(stats?.month.cogs_estimated ?? 0)}</div>
        </div>
        <div className="card" style={{ padding: 12 }}>
          <div style={{ color: "var(--muted)", fontSize: 12 }}>Маржа (оценка)</div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>{(stats?.month.margin_percent ?? 0).toFixed(1)}%</div>
        </div>
      </div>


      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ fontWeight: 800, marginBottom: 8 }}>Воронка продаж (30 дней)</div>
        {funnelErr ? <div style={{ color: "#ff8c8c", marginBottom: 8 }}>{funnelErr}</div> : null}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
          <div><div style={{ color: "var(--muted)", fontSize: 12 }}>Просмотры товара</div><div style={{ fontWeight: 800 }}>{funnel?.counts.view_product ?? 0}</div></div>
          <div><div style={{ color: "var(--muted)", fontSize: 12 }}>Добавления в корзину</div><div style={{ fontWeight: 800 }}>{funnel?.counts.add_to_cart ?? 0}</div></div>
          <div><div style={{ color: "var(--muted)", fontSize: 12 }}>Начали оформление</div><div style={{ fontWeight: 800 }}>{funnel?.counts.begin_checkout ?? 0}</div></div>
          <div><div style={{ color: "var(--muted)", fontSize: 12 }}>Покупки</div><div style={{ fontWeight: 800 }}>{funnel?.counts.purchase ?? 0}</div></div>
        </div>
        <div style={{ marginTop: 10, color: "var(--muted)", fontSize: 13 }}>
          CR view→cart: <b>{(funnel?.conversion.view_to_cart_percent ?? 0).toFixed(2)}%</b> • cart→checkout: <b>{(funnel?.conversion.cart_to_checkout_percent ?? 0).toFixed(2)}%</b> • checkout→purchase: <b>{(funnel?.conversion.checkout_to_purchase_percent ?? 0).toFixed(2)}%</b>
        </div>
      </div>


      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ fontWeight: 800, marginBottom: 8 }}>Топ товаров по аналитике (30 дней)</div>
        {topProductsErr ? <div style={{ color: "#ff8c8c", marginBottom: 8 }}>{topProductsErr}</div> : null}
        {topProducts.length === 0 ? (
          <div className="small-muted">Пока недостаточно данных.</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: "6px 4px" }}>Товар</th>
                  <th style={{ textAlign: "right", padding: "6px 4px" }}>Просм.</th>
                  <th style={{ textAlign: "right", padding: "6px 4px" }}>В корз.</th>
                  <th style={{ textAlign: "right", padding: "6px 4px" }}>Покупки</th>
                  <th style={{ textAlign: "right", padding: "6px 4px" }}>CR</th>
                </tr>
              </thead>
              <tbody>
                {topProducts.map((it) => (
                  <tr key={it.product_id} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ padding: "6px 4px" }}>{it.title}</td>
                    <td style={{ textAlign: "right", padding: "6px 4px" }}>{it.view_product}</td>
                    <td style={{ textAlign: "right", padding: "6px 4px" }}>{it.add_to_cart}</td>
                    <td style={{ textAlign: "right", padding: "6px 4px" }}>{it.purchase}</td>
                    <td style={{ textAlign: "right", padding: "6px 4px", fontWeight: 700 }}>{Number(it.purchase_rate_percent || 0).toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>



      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <div style={{ fontWeight: 800 }}>Операционная очередь (что требует внимания)</div>
          <div className="small-muted">Индекс нагрузки: <b>{opsQueue?.severity_score ?? 0}</b></div>
        </div>
        {opsErr ? <div style={{ color: "#ff8c8c", marginTop: 8 }}>{opsErr}</div> : null}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, marginTop: 10 }}>
          <label className="small-muted">Лимит
            <input className="input" type="number" min={3} max={20} value={opsLimit} onChange={(e) => setOpsLimit(Math.min(20, Math.max(3, Number(e.target.value) || 8)))} />
          </label>
          <label className="small-muted">Низкий остаток ≤
            <input className="input" type="number" min={0} max={20} value={opsLowStockThreshold} onChange={(e) => setOpsLowStockThreshold(Math.min(20, Math.max(0, Number(e.target.value) || 2)))} />
          </label>
          <label className="small-muted">Просрочка (часы)
            <input className="input" type="number" min={1} max={168} value={opsStaleHours} onChange={(e) => setOpsStaleHours(Math.min(168, Math.max(1, Number(e.target.value) || 24)))} />
          </label>
          <label className="small-muted" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={opsIncludeLowStock} onChange={(e) => setOpsIncludeLowStock(e.target.checked)} />
            Учитывать низкий остаток
          </label>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10, marginTop: 10 }}>
          <div className="card" style={{ padding: 10 }}>
            <div className="small-muted">Просроченные оплаты</div>
            <div style={{ fontWeight: 800, fontSize: 20 }}>{opsQueue?.counts.stale_orders ?? 0}</div>
          </div>
          <div className="card" style={{ padding: 10 }}>
            <div className="small-muted">Без чека</div>
            <div style={{ fontWeight: 800, fontSize: 20 }}>{opsQueue?.counts.stale_orders_without_proof ?? 0}</div>
          </div>
          <div className="card" style={{ padding: 10 }}>
            <div className="small-muted">Карточки с проблемами</div>
            <div style={{ fontWeight: 800, fontSize: 20 }}>{opsQueue?.counts.products_missing_data ?? 0}</div>
          </div>
          <div className="card" style={{ padding: 10 }}>
            <div className="small-muted">Низкий остаток</div>
            <div style={{ fontWeight: 800, fontSize: 20 }}>{opsQueue?.counts.low_stock_variants ?? 0}</div>
          </div>
        </div>

        <div style={{ marginTop: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={{ fontWeight: 700 }}>Приоритетные задачи</div>
            <div className="small-muted">по убыванию приоритета</div>
          </div>
          {(opsQueue?.queue || []).slice(0, 8).map((task, idx) => (
            <div key={`${task.type}_${idx}`} className="card" style={{ padding: 10, marginBottom: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "start" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 700 }}>{task.title}</div>
                  <div className="small-muted" style={{ marginTop: 4 }}>{task.subtitle}</div>
                  <div style={{ marginTop: 6, fontSize: 13 }}>
                    👉 {task.recommended_action}
                  </div>
                </div>
                <div className="chip chip-sm" style={{ whiteSpace: "nowrap" }}>prio {task.priority}</div>
              </div>
            </div>
          ))}
          {(opsQueue?.queue || []).length === 0 ? <div className="small-muted">Очередь пока пустая</div> : null}
        </div>

        <div style={{ marginTop: 10 }}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>Просроченные заказы</div>
          {(opsQueue?.items.stale_orders || []).slice(0, 5).map((it) => (
            <div key={it.order_id} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "6px 0", borderTop: "1px solid var(--border)" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700 }}>Заказ #{it.order_id} • {it.hours_waiting}ч</div>
                <div className="small-muted">{formatRub(it.total_amount)} {it.fio ? `• ${it.fio}` : ""} {it.has_payment_proof ? "• чек есть" : "• без чека"}</div>
              </div>
            </div>
          ))}
          {(opsQueue?.items.stale_orders || []).length === 0 ? <div className="small-muted">Нет просроченных заказов</div> : null}
        </div>

        <div style={{ marginTop: 10 }}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>Топ проблемных карточек</div>
          {(opsQueue?.items.products_missing_data || []).slice(0, 5).map((it) => (
            <div key={it.product_id} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "6px 0", borderTop: "1px solid var(--border)" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{it.title}</div>
                <div className="small-muted">#{it.product_id} • {it.reasons.join(", ")}</div>
              </div>
            </div>
          ))}
          {(opsQueue?.items.products_missing_data || []).length === 0 ? <div className="small-muted">Нет критичных карточек 🎉</div> : null}
        </div>

        <div style={{ marginTop: 10 }}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>Низкие остатки</div>
          {(opsQueue?.items.low_stock_variants || []).slice(0, 5).map((it) => (
            <div key={it.variant_id} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "6px 0", borderTop: "1px solid var(--border)" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{it.title}</div>
                <div className="small-muted">variant #{it.variant_id} • остаток: {it.stock_quantity} {it.is_out ? "• OUT" : ""}</div>
              </div>
            </div>
          ))}
          {(opsQueue?.items.low_stock_variants || []).length === 0 ? <div className="small-muted">Критичных остатков нет</div> : null}
        </div>
      </div>

      <button className="btn btn-primary" style={{ width: "100%", marginTop: 12 }} onClick={exportXlsx}>
        Экспорт в Excel
      </button>

      <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 10 }}>
        {navButtons.map((b) => (
          <button
            key={b.k}
            className="btn btn-secondary"
            style={{ width: "100%", padding: "14px 14px", textAlign: "left" }}
            onClick={() => setView(b.k)}
          >
            {b.label} →
          </button>
        ))}
      </div>

      <div style={{ height: 30 }} />
    </div>
  );
}
