// webapp-frontend/src/components/Cart.tsx
//
// Main cart page (used by App.tsx).
// Restores the "nice" cart layout and keeps payment requisites hidden until
// the user presses "Оформить заказ" (next step: OrderSuccess).

import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  applyCartPromo,
  clearCart,
  createOrder,
  deleteCartItem,
  getCart,
  removeCartPromo,
  setCartItem,
} from "../services/api";
import { useToast } from "../contexts/ToastContext";

type CartItem = {
  variant_id: number;
  quantity: number;
  price: number;
  product_id: number;
  title: string;
  image?: string | null;
  size?: string | null;
  color?: string | null;
};

type CartPromo = {
  code: string;
  kind: "special" | "referral" | string;
  discount_percent?: number | string | null;
  discount_amount?: number | string | null;
  expires_at?: string | null;
};

type CartOut = {
  items: CartItem[];
  subtotal: number;
  discount: number;
  total: number;
  promo?: CartPromo | null;
};

const FREE_DELIVERY_FROM = 5000;
const DELIVERY_PRICE = 449;

function fmtRub(value: any) {
  const n = Number(value || 0);
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
  }).format(Number.isFinite(n) ? n : 0);
}

function toIsoDateTime(ts?: string | null) {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString();
  } catch {
    return "";
  }
}

export default function Cart() {
  const nav = useNavigate();
  const { notify } = useToast();

  const [cart, setCart] = useState<CartOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [promo, setPromo] = useState("");
  const [promoApplying, setPromoApplying] = useState(false);

  const [fio, setFio] = useState("");
  const [phone, setPhone] = useState("");
  const [pvz, setPvz] = useState("");
  const [note, setNote] = useState("");
  const [placing, setPlacing] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res: any = await getCart();
      const data = (res as any)?.data ?? res;
      if ((data as any)?.status && (data as any)?.status >= 400) {
        setError((data as any)?.detail || "Не удалось загрузить корзину");
        setCart(null);
      } else {
        setCart(data as CartOut);
      }
    } catch (e: any) {
      setCart(null);
      setError(e?.message || "Не удалось загрузить корзину");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const items = cart?.items || [];
  const subtotal = Number(cart?.subtotal || 0);
  const discount = Number(cart?.discount || 0);
  const total = Number(cart?.total || 0);

  const remainingToFree = Math.max(0, FREE_DELIVERY_FROM - subtotal);
  const freeProgress = Math.min(1, subtotal / FREE_DELIVERY_FROM);
  const hasDeliveryAddress = pvz.trim().length > 0;
  const deliveryPrice = items.length > 0 && hasDeliveryAddress && subtotal < FREE_DELIVERY_FROM ? DELIVERY_PRICE : 0;
  const payableTotal = total + deliveryPrice;

  const promoApplied = useMemo(() => {
    return cart?.promo?.code ? String(cart.promo.code) : "";
  }, [cart?.promo]);

  // UI: hide promo inputs for regular users.
  const canUsePromo = useMemo(() => {
    try {
      const raw = localStorage.getItem("me");
      if (!raw) return false;
      const p = JSON.parse(raw);
      const role = String(p?.role || "user");
      return role === "admin" || role === "manager" || role === "supermanager" || role === "superadmin";
    } catch {
      return false;
    }
  }, []);

  async function changeQty(variant_id: number, nextQty: number) {
    const q = Math.max(0, Number(nextQty) || 0);
    try {
      if (q <= 0) {
        const res: any = await deleteCartItem(variant_id);
        const data = res?.data ?? res;
        setCart(data);
        return;
      }
      const res: any = await setCartItem(variant_id, q);
      const data = res?.data ?? res;
      setCart(data);
    } catch (e: any) {
      notify(e?.response?.data?.detail || e?.message || "Не удалось обновить количество", "error");
    }
  }

  async function onApplyPromo() {
    if (!promo.trim()) return;
    setPromoApplying(true);
    try {
      const res: any = await applyCartPromo(promo.trim());
      const data = res?.data ?? res;
      if (data?.status && data?.status >= 400) {
        notify(data?.detail || "Не удалось применить промокод", "error");
      } else {
        setCart(data);
        notify("Промокод применён ✅", "success");
      }
    } catch (e: any) {
      notify(e?.response?.data?.detail || e?.message || "Не удалось применить промокод", "error");
    } finally {
      setPromoApplying(false);
    }
  }

  async function onRemovePromo() {
    setPromoApplying(true);
    try {
      const res: any = await removeCartPromo();
      const data = res?.data ?? res;
      setCart(data);
      notify("Промокод убран", "success");
    } catch (e: any) {
      notify(e?.response?.data?.detail || e?.message || "Не удалось убрать промокод", "error");
    } finally {
      setPromoApplying(false);
    }
  }

  async function onClearCart() {
    try {
      const res: any = await clearCart();
      const data = res?.data ?? res;
      setCart(data);
      notify("Корзина очищена", "success");
    } catch (e: any) {
      notify(e?.response?.data?.detail || e?.message || "Не удалось очистить корзину", "error");
    }
  }

  async function onPlaceOrder() {
    if (!items.length) {
      notify("Корзина пуста", "error");
      return;
    }
    if (!fio.trim()) {
      notify("Введите ФИО", "error");
      return;
    }
    if (!pvz.trim()) {
      notify("Введите адрес/ПВЗ", "error");
      return;
    }

    setPlacing(true);
    try {
      const payload = {
        fio: fio.trim(),
        phone: phone.trim() || undefined,
        delivery_type: "pvz",
        delivery_address: pvz.trim(),
        note: note.trim() || undefined,
      };

      const res: any = await createOrder(payload);
      const data = (res as any)?.data ?? res;
      if (data?.status && data?.status >= 400) {
        notify(data?.detail || "Не удалось оформить заказ", "error");
        setPlacing(false);
        return;
      }
      const orderId = data?.id;
      notify("Заказ создан ✅", "success");
      // move to success page (there payment requisites + proof upload)
      if (orderId) nav(`/order/success/${orderId}`);
      else nav(`/profile`);
    } catch (e: any) {
      notify(e?.response?.data?.detail || e?.message || "Не удалось оформить заказ", "error");
    } finally {
      setPlacing(false);
    }
  }

  return (
    <div className="container" style={{ paddingTop: 12, paddingBottom: 90 }}>
      <div className="page-head">
        <div>
          <div className="page-head__title">Корзина</div>
          <div className="small-muted" style={{ marginTop: 6 }}>
            {loading ? "Загрузка…" : items.length ? `${items.length} товар(ов)` : "Пока пусто"}
          </div>
        </div>
        <div className="page-head__actions">
          <Link to="/catalog" className="btn ghost" style={{ textDecoration: "none" }}>
            Каталог
          </Link>
        </div>
      </div>

      {error ? <div className="card" style={{ padding: 12, borderColor: "#a33", marginBottom: 12 }}>{error}</div> : null}

      <div className="cart-grid">
        <div className="left-column">
          {items.length === 0 ? (
            <div className="card empty-state" style={{ padding: 14 }}>
              <div className="empty-emoji" aria-hidden>
                🛍️
              </div>
              <div style={{ fontWeight: 900, fontSize: 18 }}>Корзина пуста</div>
              <div className="small-muted" style={{ marginTop: 8 }}>
                Перейдите в каталог и добавьте товары.
              </div>
              <div style={{ marginTop: 12 }}>
                <Link to="/catalog" className="btn" style={{ textDecoration: "none" }}>
                  Перейти в каталог
                </Link>
              </div>
            </div>
          ) : (
            items.map((it) => (
              <div key={String(it.variant_id)} className="card cart-item">
                <div className="thumb">
                  {it.image ? <img src={String(it.image)} alt={it.title} /> : <div className="no-image">NO IMAGE</div>}
                </div>

                <div className="item-body">
                  <div className="item-top">
                    <div>
                      <div style={{ fontWeight: 900 }}>{it.title}</div>
                      <div className="chips" style={{ gap: 6, marginTop: 8 }}>
                        {it.size ? <span className="chip chip-sm">{it.size}</span> : null}
                        {it.color ? <span className="chip chip-sm">{it.color}</span> : null}
                      </div>
                    </div>

                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontWeight: 900 }}>{fmtRub(it.price)}</div>
                      <div className="small-muted" style={{ marginTop: 6 }}>{fmtRub(Number(it.price || 0) * Number(it.quantity || 1))}</div>
                    </div>
                  </div>

                  <div className="item-controls">
                    <div className="field-block qty-block">
                      <div className="small-muted">Кол-во</div>
                      <div className="qty-control">
                        <button onClick={() => changeQty(it.variant_id, (it.quantity || 1) - 1)} className="btn ghost">-</button>
                        <input
                          type="number"
                          className="input qty-input"
                          value={it.quantity || 1}
                          onChange={(e) => changeQty(it.variant_id, Number(e.target.value) || 1)}
                          min={1}
                        />
                        <button onClick={() => changeQty(it.variant_id, (it.quantity || 1) + 1)} className="btn ghost">+</button>
                      </div>
                    </div>

                    <div className="remove-block">
                      <button onClick={() => changeQty(it.variant_id, 0)} className="btn ghost remove-btn">Удалить</button>
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="right-column">
          <div className="card sticky-summary">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ fontWeight: 900 }}>Итого</div>
              <div className="small-muted">Подробно</div>
            </div>

            <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <div className="small-muted">Подытог</div>
                <div>{fmtRub(subtotal)}</div>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <div className="small-muted">Скидка</div>
                <div>-{fmtRub(discount)}</div>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <div className="small-muted">Доставка</div>
                <div>{deliveryPrice > 0 ? fmtRub(deliveryPrice) : "Бесплатно"}</div>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 900, marginTop: 6 }}>
                <div>К оплате</div>
                <div>{fmtRub(payableTotal)}</div>
              </div>
            </div>

            <div className="free-delivery">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                <div className="small-muted" style={{ fontWeight: 900 }}>Бесплатная доставка</div>
                <div className="small-muted" style={{ fontWeight: 900 }}>от {fmtRub(FREE_DELIVERY_FROM)}</div>
              </div>
              <div className="progress" aria-hidden="true">
                <div className="progress-bar" style={{ width: `${Math.round(freeProgress * 100)}%` }} />
              </div>
              <div className="small-muted" style={{ marginTop: 6 }}>
                {remainingToFree === 0 ? "Доставка бесплатная 🎉" : `Добавь ещё ${fmtRub(remainingToFree)} до бесплатной доставки`}
              </div>
            </div>

            {canUsePromo ? (
              <div style={{ marginTop: 14 }}>
                <div className="small-muted" style={{ marginBottom: 8 }}>Промокод</div>
                {promoApplied ? (
                <div className="card" style={{ padding: 10, marginBottom: 10 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <div>
                      <div style={{ fontWeight: 900 }}>{promoApplied}</div>
                      <div className="small-muted" style={{ marginTop: 4 }}>
                        {cart?.promo?.kind === "special"
                          ? `Скидка: ${cart?.promo?.discount_percent ?? "?"}%`
                          : "Реферальный код"}
                        {cart?.promo?.expires_at ? ` • До: ${toIsoDateTime(cart.promo.expires_at)}` : ""}
                      </div>
                    </div>
                    <button className="btn ghost" onClick={onRemovePromo} disabled={promoApplying}>
                      Убрать
                    </button>
                  </div>
                </div>
                ) : (
                  <div style={{ display: "flex", gap: 8 }}>
                    <input className="input" placeholder="Введите промокод" value={promo} onChange={(e) => setPromo(e.target.value)} />
                    <button className="btn" onClick={onApplyPromo} disabled={promoApplying || !promo.trim()}>
                      {promoApplying ? "…" : "Применить"}
                    </button>
                  </div>
                )}
              </div>
            ) : null}
          </div>

          <div className="card" style={{ marginTop: 12 }}>
            <div style={{ fontWeight: 900, marginBottom: 8 }}>Данные для доставки</div>

            <label className="small-muted">ФИО</label>
            <input className="input" value={fio} onChange={(e) => setFio(e.target.value)} placeholder="Иван Иванов" style={{ marginTop: 6, marginBottom: 8 }} />

            <label className="small-muted">Адрес ПВЗ</label>
            <input className="input" value={pvz} onChange={(e) => setPvz(e.target.value)} placeholder="CDEK / Ozon / Яндекс — укажите ПВЗ" style={{ marginTop: 6, marginBottom: 8 }} />

            <div className="notice" style={{ marginBottom: 8 }}>
              <strong>Доставка:</strong> фикс {fmtRub(DELIVERY_PRICE)} при сумме заказа до {fmtRub(FREE_DELIVERY_FROM)},
              от {fmtRub(FREE_DELIVERY_FROM)} — бесплатно.
            </div>

            <div className="notice" style={{ marginBottom: 8 }}>
              <strong>Важно:</strong> реквизиты для оплаты появятся <strong>после</strong> нажатия “Оформить заказ”.
              После оплаты загрузите чек — заказ уйдёт на модерацию.
            </div>

            <label className="small-muted">Телефон (опционально)</label>
            <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+7 9xx xxx xx xx" style={{ marginTop: 6, marginBottom: 8 }} />

            <label className="small-muted">Комментарий (опционально)</label>
            <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Например: просьба проверить замеры" style={{ marginTop: 6, marginBottom: 8 }} />
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
            <button className="btn full-width-on-mobile" onClick={onPlaceOrder} disabled={placing || loading}>
              {placing ? "Оформляем…" : "Оформить заказ"}
            </button>
            <button className="btn ghost full-width-on-mobile" onClick={onClearCart} disabled={placing || loading}>
              Очистить
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
