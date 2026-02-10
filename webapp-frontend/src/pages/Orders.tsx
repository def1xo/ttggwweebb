import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Collapsible from "../components/Collapsible";
import { axiosInstance, reportClientError } from "../services/api";
import { hapticImpact } from "../utils/tg";

type OrderAny = any;

function normalizeStatus(s: any): string {
  if (!s) return "";
  const raw = String(s);
  return (raw.split(".").pop() || raw).trim();
}

function statusLabel(s: any): string {
  const key = normalizeStatus(s);
  const map: Record<string, string> = {
    awaiting_payment: "Ожидает оплату",
    paid: "Чек загружен",
    processing: "В обработке",
    sent: "Отправлен",
    received: "Получен",
    delivered: "Доставлен",
    cancelled: "Отменён",
  };
  return map[key] || (key || "—");
}

function formatMoney(v: any): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  try {
    return new Intl.NumberFormat("ru-RU").format(n);
  } catch {
    return String(n);
  }
}

function pickTotal(o: any): number | null {
  const cands = [o?.total_amount, o?.total, o?.amount, o?.sum];
  for (const v of cands) {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function parseList(data: any): OrderAny[] {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data?.orders)) return data.orders;
  return [];
}

export default function Orders() {
  const [items, setItems] = useState<OrderAny[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const sorted = useMemo(() => {
    const copy = [...items];
    copy.sort((a, b) => {
      const da = a?.created_at ? Date.parse(String(a.created_at)) : 0;
      const db = b?.created_at ? Date.parse(String(b.created_at)) : 0;
      return db - da;
    });
    return copy;
  }, [items]);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const endpoints = ["/api/orders/me", "/api/orders", "/api/my/orders", "/orders/me"];
      let lastError: any = null;
      for (const ep of endpoints) {
        try {
          const res = await axiosInstance.get(ep);
          const data = (res as any)?.data ?? res;
          const list = parseList(data);
          setItems(list);
          return;
        } catch (e: any) {
          lastError = e;
          const st = e?.response?.status;
          if (st === 401 || st === 403) {
            setErr("Нужна авторизация для просмотра заказов");
            setItems([]);
            return;
          }
          // try next endpoint
        }
      }

      // if nothing worked
      const msg =
        lastError?.response?.data?.detail ||
        lastError?.message ||
        "Не удалось загрузить заказы. Проверьте бэкенд.";
      setErr(String(msg));
      setItems([]);

      try {
        await reportClientError({
          message: "Orders page: failed to load orders",
          raw: String(msg),
          ts: Date.now(),
        });
      } catch {}
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      load();
    }, 30000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggle(id: string) {
    try { hapticImpact("light"); } catch {}
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  return (
    <div className="container" style={{ paddingTop: 12, paddingBottom: 90 }}>
      <div className="page-head">
        <div className="page-head__title">Заказы</div>
      </div>

      {loading ? <div className="small-muted" style={{ marginTop: 10 }}>Загрузка…</div> : null}
      {err ? (
        <div className="card" style={{ padding: 12, marginTop: 12, color: "salmon" }}>
          {err}
        </div>
      ) : null}

      {!loading && !err && sorted.length === 0 ? (
        <div className="card empty-state" style={{ padding: 14, marginTop: 12 }}>
          <div className="empty-emoji" aria-hidden>📦</div>
          <div style={{ fontWeight: 900, fontSize: 18 }}>Пока нет заказов</div>
          <div className="small-muted" style={{ marginTop: 8 }}>
            Когда вы оформите заказ — он появится тут.
          </div>
          <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Link to="/catalog" className="btn" style={{ textDecoration: "none" }}>Перейти в каталог</Link>
          </div>
        </div>
      ) : null}

      {sorted.length > 0 ? (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
          {sorted.map((o: any, idx: number) => {
            const id = String(o?.id ?? idx);
            const open = !!expanded[id];
            const total = pickTotal(o);
            const created = o?.created_at ? new Date(String(o.created_at)) : null;
            const createdLabel = created && !isNaN(created.getTime()) ? created.toLocaleString() : "";
            return (
              <div
                key={id}
                className="card list-item-animate"
                style={{ padding: 12, animationDelay: `${Math.min(idx * 35, 240)}ms` }}
              >
                <button
                  className="order-row"
                  onClick={() => toggle(id)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    background: "transparent",
                    border: "none",
                    color: "inherit",
                    padding: 0,
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 10,
                    cursor: "pointer",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 900 }}>Заказ #{id}</div>
                    <div className="small-muted" style={{ marginTop: 4 }}>
                      {statusLabel(o?.status)}{createdLabel ? ` • ${createdLabel}` : ""}
                    </div>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
                    <div style={{ fontWeight: 900 }}>{total == null ? "" : `${formatMoney(total)} ₽`}</div>
                    <div className={`chev ${open ? "open" : ""}`} aria-hidden>
                      ▾
                    </div>
                  </div>
                </button>

                <Collapsible open={open} duration={240}>
                  <div style={{ paddingTop: 10, display: "flex", flexDirection: "column", gap: 10 }}>
                    {createdLabel ? (
                      <div className="small-muted">Создан: <b style={{ color: "var(--text, #fff)" }}>{createdLabel}</b></div>
                    ) : null}

                    {o?.delivery_address ? (
                      <div>
                        <div className="small-muted">Доставка</div>
                        <div style={{ fontWeight: 700, marginTop: 4 }}>{String(o.delivery_address)}</div>
                      </div>
                    ) : null}

                    {Array.isArray(o?.items) && o.items.length > 0 ? (
                      <div>
                        <div className="small-muted" style={{ marginBottom: 6 }}>Состав</div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                          {o.items.slice(0, 12).map((it: any, j: number) => {
                            const title = it?.title || it?.name || it?.product_name || `Товар ${j + 1}`;
                            const qty = it?.quantity ?? it?.qty ?? 1;
                            const size = it?.size ? ` • ${it.size}` : "";
                            const color = it?.color ? ` • ${it.color}` : "";
                            return (
                              <div key={j} className="order-item-row">
                                <div style={{ fontWeight: 700 }}>{title}</div>
                                <div className="small-muted">x{qty}{size}{color}</div>
                              </div>
                            );
                          })}
                          {o.items.length > 12 ? (
                            <div className="small-muted">… и ещё {o.items.length - 12}</div>
                          ) : null}
                        </div>
                      </div>
                    ) : null}

                    <div style={{ display: "flex", gap: 10 }}>
                      <Link
                        to={`/order/success/${id}`}
                        className="btn"
                        onClick={() => {
                          try { hapticSelection(); } catch {}
                        }}
                      >
                        Открыть
                      </Link>
                      <Link
                        to="/catalog"
                        className="btn ghost"
                        onClick={() => {
                          try { hapticSelection(); } catch {}
                        }}
                      >
                        В магазин
                      </Link>
                    </div>
                  </div>
                </Collapsible>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
