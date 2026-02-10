import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Collapsible from "../components/Collapsible";
import FavoriteRow from "../components/FavoriteRow";
import ManagerPanelMini from "../components/ManagerPanelMini";
import { axiosInstance, getFavorites, getMyProfile } from "../services/api";
import { hapticImpact, hapticNotify, hapticSelection } from "../utils/tg";

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

function parseOrders(data: any): OrderAny[] {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data?.orders)) return data.orders;
  return [];
}

function parseFavorites(res: any): any[] {
  const data = (res as any)?.data ?? res;
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data?.favorites)) return data.favorites;
  if (Array.isArray(data?.products)) return data.products;
  return [];
}

function formatMoney(v: any): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  try {
    return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(n);
  } catch {
    return String(Math.round(n));
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

export default function Profile() {
  const [me, setMe] = useState<any | null>(null);
  const [meLoading, setMeLoading] = useState(false);

  const [orders, setOrders] = useState<OrderAny[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [ordersErr, setOrdersErr] = useState<string | null>(null);
  const [ordersExpanded, setOrdersExpanded] = useState<Record<string, boolean>>({});

  const [favorites, setFavorites] = useState<any[]>([]);
  const [favLoading, setFavLoading] = useState(false);
  const [favErr, setFavErr] = useState<string | null>(null);

  const role = String(me?.role || "user");
  const canSeeRef = role === "admin" || role === "manager" || role === "supermanager" || role === "superadmin";
  const canEditPromos = role === "admin" || role === "superadmin" || role === "manager" || role === "supermanager" || role === "assistant";
  const promoManagePath = role === "admin" || role === "superadmin" ? "/admin" : "/manager";

  const displayName = useMemo(() => {
    const dn = me?.display_name || me?.name;
    if (dn) return String(dn);
    const fn = me?.first_name ? String(me.first_name) : "";
    const ln = me?.last_name ? String(me.last_name) : "";
    const full = `${fn} ${ln}`.trim();
    return full || (me?.username ? `@${me.username}` : "Профиль");
  }, [me]);

  async function loadMe() {
    setMeLoading(true);
    try {
      const data = await getMyProfile(true);
      setMe(data);
    } catch {
      setMe(null);
    } finally {
      setMeLoading(false);
    }
  }

  async function loadOrders() {
    setOrdersLoading(true);
    setOrdersErr(null);
    try {
      const endpoints = ["/api/orders/me", "/api/orders", "/api/my/orders", "/orders/me"];
      let last: any = null;
      for (const ep of endpoints) {
        try {
          const res = await axiosInstance.get(ep);
          const data = (res as any)?.data ?? res;
          const list = parseOrders(data);
          setOrders(list);
          return;
        } catch (e: any) {
          last = e;
          const st = e?.response?.status;
          if (st === 401 || st === 403) {
            setOrders([]);
            setOrdersErr("Нужна авторизация для просмотра заказов");
            return;
          }
        }
      }
      const msg = last?.response?.data?.detail || last?.message || "Не удалось загрузить заказы";
      setOrders([]);
      setOrdersErr(String(msg));
    } finally {
      setOrdersLoading(false);
    }
  }

  async function loadFavorites() {
    setFavLoading(true);
    setFavErr(null);
    try {
      const res: any = await getFavorites();
      setFavorites(parseFavorites(res));
    } catch (e: any) {
      setFavorites([]);
      setFavErr(e?.response?.data?.detail || e?.message || "Не удалось загрузить избранное");
    } finally {
      setFavLoading(false);
    }
  }

  useEffect(() => {
    loadMe();
    loadOrders();
    loadFavorites();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadMe();
      loadOrders();
      loadFavorites();
    }, 45000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const lastOrders = useMemo(() => {
    const copy = [...orders];
    copy.sort((a, b) => {
      const da = a?.created_at ? Date.parse(String(a.created_at)) : 0;
      const db = b?.created_at ? Date.parse(String(b.created_at)) : 0;
      return db - da;
    });
    return copy.slice(0, 5);
  }, [orders]);

  const lastFav = useMemo(() => favorites.slice(0, 5), [favorites]);

  const toggleOrder = (id: string) => {
    try {
      hapticImpact("light");
    } catch {}
    setOrdersExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const copyRef = async () => {
    const code = String(me?.promo_code || "").trim();
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      hapticNotify("success");
    } catch {
      // clipboard may be blocked inside some WebViews
      try {
        (window as any).Telegram?.WebApp?.showPopup?.({
          title: "Реф. код",
          message: code,
          buttons: [{ type: "ok", text: "Ок" }],
        });
      } catch {}
      try {
        hapticNotify("warning");
      } catch {}
    }
  };

  return (
    <div className="container" style={{ paddingTop: 12, paddingBottom: 90 }}>
      <div className="page-head">
        <div className="page-head__title">Профиль</div>
        <div className="page-head__actions">
          <Link to="/catalog" className="btn ghost" style={{ textDecoration: "none" }}>
            Каталог
          </Link>
        </div>
      </div>

      <div className="card" style={{ padding: 14, marginTop: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div className="avatar" aria-hidden>
            {me?.avatar_url ? <img src={String(me.avatar_url)} alt="" /> : <span>👤</span>}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 900, fontSize: 18, lineHeight: 1.2 }}>{meLoading ? "Загрузка…" : displayName}</div>
            <div className="small-muted" style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap" }}>
              {me?.username ? <span className="chip chip-sm">@{me.username}</span> : null}
              {role ? <span className="chip chip-sm">{role}</span> : null}
              {me?.telegram_id ? <span className="chip chip-sm">id: {me.telegram_id}</span> : null}
            </div>
          </div>
        </div>

        {canSeeRef || canEditPromos ? (
          <div className="card" style={{ padding: 12, marginTop: 12 }}>
            {canSeeRef ? (
              <>
                <div className="small-muted" style={{ marginBottom: 6 }}>
                  Реф. код (видно только админу/менеджеру)
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <div style={{ fontWeight: 900, fontSize: 16 }}>{me?.promo_code ? String(me.promo_code) : "—"}</div>
                  {me?.promo_code ? (
                    <button className="btn btn-secondary btn-sm" onClick={copyRef} type="button">
                      Скопировать
                    </button>
                  ) : null}
                </div>
              </>
            ) : (
              <div className="small-muted" style={{ marginBottom: 6 }}>
                Управление промокодами
              </div>
            )}

            {canEditPromos ? (
              <div style={{ marginTop: canSeeRef ? 8 : 0 }}>
                <Link to={promoManagePath} className="btn btn-sm" style={{ textDecoration: "none" }}>
                  Изменить промокоды
                </Link>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* Orders preview */}
      <div className="section-head" style={{ marginTop: 14 }}>
        <div className="section-head__title">Последние заказы</div>
        <Link
          to="/orders"
          className="link-pill"
          onClick={() => {
            try {
              hapticSelection();
            } catch {}
          }}
        >
          Смотреть все
        </Link>
      </div>

      {ordersLoading ? (
        <div className="skeleton-list" style={{ marginTop: 12 }}>
          {[0, 1].map((i) => (
            <div key={i} className="skeleton-row" style={{ marginTop: i ? 10 : 0 }} />
          ))}
        </div>
      ) : null}

      {ordersErr ? (
        <div className="card error-card" style={{ padding: 12, marginTop: 12 }}>
          {ordersErr}
        </div>
      ) : null}

      {!ordersLoading && !ordersErr && lastOrders.length === 0 ? (
        <div className="card empty-state" style={{ padding: 14, marginTop: 12 }}>
          <div className="empty-emoji" aria-hidden>
            📦
          </div>
          <div style={{ fontWeight: 900, fontSize: 18 }}>Пока нет заказов</div>
          <div className="small-muted" style={{ marginTop: 8 }}>
            Оформи первый заказ — он появится здесь.
          </div>
        </div>
      ) : null}

      {!ordersLoading && !ordersErr && lastOrders.length > 0 ? (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
          {lastOrders.map((o: any, idx: number) => {
            const id = String(o?.id ?? idx);
            const open = !!ordersExpanded[id];
            const created = o?.created_at ? new Date(String(o.created_at)) : null;
            const createdLabel = created && !isNaN(created.getTime()) ? created.toLocaleString() : "";
            const total = pickTotal(o);
            return (
              <div key={id} className="card list-item-animate" style={{ padding: 12, animationDelay: `${Math.min(idx * 35, 180)}ms` }}>
                <button
                  type="button"
                  onClick={() => toggleOrder(id)}
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
                    {o?.delivery_address ? (
                      <div>
                        <div className="small-muted">Доставка</div>
                        <div style={{ fontWeight: 700, marginTop: 4 }}>{String(o.delivery_address)}</div>
                      </div>
                    ) : null}

                    {Array.isArray(o?.items) && o.items.length > 0 ? (
                      <div>
                        <div className="small-muted" style={{ marginBottom: 6 }}>
                          Состав
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                          {o.items.slice(0, 6).map((it: any, j: number) => {
                            const title = it?.title || it?.name || it?.product_name || `Товар ${j + 1}`;
                            const qty = it?.quantity ?? it?.qty ?? 1;
                            const size = it?.size ? ` • ${it.size}` : "";
                            const color = it?.color ? ` • ${it.color}` : "";
                            return (
                              <div key={j} className="order-item-row">
                                <div style={{ fontWeight: 700 }}>{title}</div>
                                <div className="small-muted">
                                  x{qty}{size}{color}
                                </div>
                              </div>
                            );
                          })}
                          {o.items.length > 6 ? <div className="small-muted">… и ещё {o.items.length - 6}</div> : null}
                        </div>
                      </div>
                    ) : null}

                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                      <Link
                        to={`/order/success/${id}`}
                        className="btn btn-secondary btn-sm"
                        onClick={() => {
                          try {
                            hapticSelection();
                          } catch {}
                        }}
                        style={{ textDecoration: "none" }}
                      >
                        Открыть
                      </Link>
                      <Link to="/catalog" className="btn ghost btn-sm" style={{ textDecoration: "none" }}>
                        В каталог
                      </Link>
                    </div>
                  </div>
                </Collapsible>
              </div>
            );
          })}
        </div>
      ) : null}

      {/* Favorites preview */}
      <div className="section-head" style={{ marginTop: 14 }}>
        <div className="section-head__title">Избранное</div>
        <Link
          to="/favorites"
          className="link-pill"
          onClick={() => {
            try {
              hapticSelection();
            } catch {}
          }}
        >
          Смотреть все
        </Link>
      </div>

      {favLoading ? (
        <div className="skeleton-list" style={{ marginTop: 12 }}>
          {[0].map((i) => (
            <div key={i} className="skeleton-row" style={{ marginTop: i ? 10 : 0 }} />
          ))}
        </div>
      ) : null}

      {favErr ? (
        <div className="card error-card" style={{ padding: 12, marginTop: 12 }}>
          {favErr}
        </div>
      ) : null}

      {!favLoading && !favErr && lastFav.length === 0 ? (
        <div className="card empty-state" style={{ padding: 14, marginTop: 12 }}>
          <div className="empty-emoji" aria-hidden>
            ✨
          </div>
          <div style={{ fontWeight: 900, fontSize: 18 }}>Пока пусто</div>
          <div className="small-muted" style={{ marginTop: 8 }}>
            Добавляй товары в избранное — они появятся здесь.
          </div>
        </div>
      ) : null}

      {!favLoading && !favErr && lastFav.length > 0 ? (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
          {lastFav.map((p, idx) => (
            <FavoriteRow
              key={String(p?.id ?? idx)}
              product={p}
              index={idx}
              compact
              onRemoved={(pid) => setFavorites((prev) => prev.filter((x) => Number(x?.id) !== Number(pid)))}
            />
          ))}
        </div>
      ) : null}

      {/* manager/admin panels */}
      <div style={{ marginTop: 14 }}>
        <ManagerPanelMini />
      </div>
    </div>
  );
}
