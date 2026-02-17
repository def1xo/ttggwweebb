// webapp-frontend/src/components/Cart.tsx
//
// Main cart page (used by App.tsx).
// Restores the "nice" cart layout and keeps payment requisites hidden until
// the user presses "Оформить заказ" (next step: OrderSuccess).

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  addCartItem,
  applyCartPromo,
  clearCart,
  createOrder,
  deleteCartItem,
  getCart,
  getCartRecommendations,
  removeCartPromo,
  setCartItem,
  trackAnalyticsEvent,
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
  in_stock?: boolean;
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

function pickCardImage(product: any): string | null {
  const imgs = (product?.images || product?.image_urls || product?.imageUrls || []) as any[];
  return (
    (Array.isArray(imgs) && imgs.length ? (imgs[0]?.url || imgs[0]) : null) ||
    product?.default_image ||
    product?.image ||
    null
  );
}

export default function Cart() {
  const nav = useNavigate();
  const { notify } = useToast();

  const [cart, setCart] = useState<CartOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [promo, setPromo] = useState("");
  const [promoApplying, setPromoApplying] = useState(false);

  const [fio, setFio] = useState("");
  const [phone, setPhone] = useState("");
  const [pvz, setPvz] = useState("");
  const [note, setNote] = useState("");
  const [placing, setPlacing] = useState(false);
  const [related, setRelated] = useState<any[]>([]);
  const [relatedLoading, setRelatedLoading] = useState(false);

  const reqIdRef = useRef(0);

  async function load(silent = false) {
    const reqId = ++reqIdRef.current;
    if (silent) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const res: any = await getCart();
      if (reqId !== reqIdRef.current) return;
      const data = (res as any)?.data ?? res;
      if ((data as any)?.status && (data as any)?.status >= 400) {
        setError((data as any)?.detail || "Не удалось загрузить корзину");
        setCart(null);
      } else {
        setCart(data as CartOut);
      }
    } catch (e: any) {
      if (reqId !== reqIdRef.current) return;
      setCart(null);
      setError(e?.message || "Не удалось загрузить корзину");
    } finally {
      if (reqId !== reqIdRef.current) return;
      if (silent) setRefreshing(false);
      else setLoading(false);
    }
  }

  useEffect(() => {
    load();

    const onCartChanged = () => {
      load(true);
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible") load(true);
    };

    window.addEventListener("cart:updated", onCartChanged as EventListener);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      reqIdRef.current += 1;
      window.removeEventListener("cart:updated", onCartChanged as EventListener);
      document.removeEventListener("visibilitychange", onVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const items = cart?.items || [];
  const availableItems = items.filter((it) => it.in_stock !== false);
  const endedItems = items.filter((it) => it.in_stock === false);
  const subtotal = Number(cart?.subtotal || 0);
  const discount = Number(cart?.discount || 0);
  const total = Number(cart?.total || 0);

  const remainingToFree = Math.max(0, FREE_DELIVERY_FROM - subtotal);
  const freeProgress = Math.min(1, subtotal / FREE_DELIVERY_FROM);
  const hasDeliveryAddress = pvz.trim().length > 0;
  const deliveryPrice = availableItems.length > 0 && hasDeliveryAddress && subtotal < FREE_DELIVERY_FROM ? DELIVERY_PRICE : 0;
  const payableTotal = total + deliveryPrice;

  const promoApplied = useMemo(() => {
    return cart?.promo?.code ? String(cart.promo.code) : "";
  }, [cart?.promo]);

  useEffect(() => {
    (async () => {
      if (!availableItems.length) {
        setRelated([]);
        return;
      }
      setRelatedLoading(true);
      try {
        const res: any = await getCartRecommendations(8);
        const data = (res as any)?.data ?? res;
        const out = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : []);
        setRelated(out.slice(0, 8));
      } finally {
        setRelatedLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableItems.map((x) => `${x.product_id}:${x.quantity}`).join('|')]);

  async function onClearEnded() {
    if (!endedItems.length) return;
    try {
      await Promise.all(endedItems.map((it) => deleteCartItem(it.variant_id)));
      notify("Список 'Закончилось' очищен", "success");
      await load(true);
      try { window.dispatchEvent(new CustomEvent("cart:updated")); } catch {}
    } catch (e: any) {
      notify(e?.response?.data?.detail || e?.message || "Не удалось очистить товары без наличия", "error");
    }
  }

  async function onAddRelated(product: any) {
    const variants = Array.isArray(product?.variants) ? product.variants : [];
    const variantId = Number(product?.default_variant_id || variants?.[0]?.id || product?.id || 0);
    if (!Number.isFinite(variantId) || variantId <= 0) return;
    try {
      await addCartItem(variantId, 1);
      notify("Добавлено в корзину", "success");
      trackAnalyticsEvent({
        event: "add_to_cart",
        product_id: Number(product?.id || 0) || null,
        variant_id: variantId,
        source: "cart_related",
      });
      try { window.dispatchEvent(new CustomEvent("cart:updated")); } catch {}
      await load(true);
    } catch (e: any) {
      notify(e?.response?.data?.detail || e?.message || "Не удалось добавить товар", "error");
    }
  }


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
      try { window.dispatchEvent(new CustomEvent("cart:updated")); } catch {}
    } catch (e: any) {
      notify(e?.response?.data?.detail || e?.message || "Не удалось очистить корзину", "error");
    }
  }

  async function onPlaceOrder() {
    if (!availableItems.length) {
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
        promo_code: promoApplied || promo.trim() || undefined,
      };

      trackAnalyticsEvent({
        event: "begin_checkout",
        source: "cart_page",
        items_count: availableItems.length,
        subtotal,
        discount,
        total,
      });

      const res: any = await createOrder(payload);
      const data = (res as any)?.data ?? res;
      if (data?.status && data?.status >= 400) {
        notify(data?.detail || "Не удалось оформить заказ", "error");
        setPlacing(false);
        return;
      }
      const orderId = data?.id;
      notify("Заказ создан ✅", "success");
      trackAnalyticsEvent({
        event: "purchase",
        source: "cart_page",
        order_id: Number(orderId || 0) || null,
        items_count: availableItems.length,
        total: payableTotal,
      });
      // move to success page (there payment requisites + proof upload)
      try { window.dispatchEvent(new CustomEvent("cart:updated")); } catch {}
      if (orderId) nav(`/order/success/${orderId}`);
      else nav(`/profile`);
    } catch (e: any) {
      notify(e?.response?.data?.detail || e?.message || "Не удалось оформить заказ", "error");
    } finally {
      setPlacing(false);
    }
  }

  return (
    <div className="container" style={{ paddingTop: 12, paddingBottom: 150 }}>
      <div className="page-head">
        <div>
          <div className="page-head__title">Корзина</div>
          <div className="small-muted" style={{ marginTop: 6 }}>
            {loading ? "Загрузка…" : refreshing ? "Обновляем…" : availableItems.length ? `${availableItems.length} товар(ов)` : "Пока пусто"}
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
          {availableItems.length === 0 ? (
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
            availableItems.map((it) => (
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
                        <button onClick={() => changeQty(it.variant_id, (it.quantity || 1) - 1)} className="btn ghost" disabled={placing || loading || refreshing}>-</button>
                        <input
                          type="number"
                          className="input qty-input"
                          value={it.quantity || 1}
                          onChange={(e) => changeQty(it.variant_id, Number(e.target.value) || 1)}
                          min={1}
                          disabled={placing || loading || refreshing}
                        />
                        <button onClick={() => changeQty(it.variant_id, (it.quantity || 1) + 1)} className="btn ghost" disabled={placing || loading || refreshing}>+</button>
                      </div>
                    </div>

                    <div className="remove-block">
                      <button onClick={() => changeQty(it.variant_id, 0)} className="btn ghost remove-btn" disabled={placing || loading || refreshing}>Удалить</button>
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}

          {endedItems.length > 0 ? (
            <div className="card" style={{ marginTop: 12, borderColor: "rgba(255,120,120,0.4)", background: "rgba(120,0,0,0.12)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <div style={{ fontWeight: 900 }}>Закончилось</div>
                <button className="btn ghost btn-sm" onClick={onClearEnded} disabled={placing || loading || refreshing}>Очистить</button>
              </div>
              <div className="small-muted" style={{ marginTop: 6 }}>Эти товары временно недоступны и не попадут в заказ.</div>
              <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
                {endedItems.map((it) => (
                  <div key={`ended_${it.variant_id}`} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <div>
                      <div style={{ fontWeight: 800 }}>{it.title}</div>
                      <div className="small-muted">x{it.quantity}</div>
                    </div>
                    <div style={{ fontWeight: 800 }}>0 ₽</div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
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
                          : "Промокод применён"}
                        {cart?.promo?.expires_at ? ` • До: ${toIsoDateTime(cart.promo.expires_at)}` : ""}
                      </div>
                    </div>
                    <button className="btn ghost" onClick={onRemovePromo} disabled={promoApplying || placing || loading || refreshing}>
                      Убрать
                    </button>
                  </div>
                </div>
                ) : (
                  <div style={{ display: "flex", gap: 8 }}>
                    <input className="input" placeholder="Введите промокод" value={promo} onChange={(e) => setPromo(e.target.value)} disabled={promoApplying || placing || loading || refreshing} />
                    <button className="btn" onClick={onApplyPromo} disabled={promoApplying || placing || loading || refreshing || !promo.trim()}>
                      {promoApplying ? "…" : "Применить"}
                    </button>
                  </div>
                )}
              </div>

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


            <label className="small-muted">Телефон (опционально)</label>
            <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+7 9xx xxx xx xx" style={{ marginTop: 6, marginBottom: 8 }} />

            <label className="small-muted">Комментарий (опционально)</label>
            <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Например: просьба проверить замеры" style={{ marginTop: 6, marginBottom: 8 }} />
          </div>

          {relatedLoading ? (
            <div className="card" style={{ marginTop: 12, padding: 12 }}>
              <div className="small-muted">Подбираем сопутствующие товары…</div>
            </div>
          ) : null}

          {!relatedLoading && related.length > 0 ? (
            <div className="card" style={{ marginTop: 12, padding: 12 }}>
              <div style={{ fontWeight: 900, marginBottom: 8 }}>С этим берут</div>
              <div className="related-row">
                {related.map((p: any) => {
                  const pid = Number(p?.id);
                  const title = String(p?.title || p?.name || "Товар");
                  const image = pickCardImage(p);
                  const price = Number(p?.price ?? p?.base_price ?? 0);
                  return (
                    <div key={pid} className="related-item">
                      <Link to={`/product/${pid}`} style={{ textDecoration: "none", color: "inherit" }}>
                        <div className="related-thumb">{image ? <img src={String(image)} alt={title} /> : null}</div>
                        <div className="related-title">{title}</div>
                      </Link>
                      <div style={{ marginTop: 6, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                        <div className="small-muted" style={{ fontWeight: 700 }}>
                          {Number.isFinite(price) && price > 0 ? `${Math.round(price).toLocaleString("ru-RU")} ₽` : "—"}
                        </div>
                        <button className="btn btn-sm" onClick={() => onAddRelated(p)} disabled={placing || loading || refreshing}>
                          + В корзину
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
            <button className="btn full-width-on-mobile" onClick={onPlaceOrder} disabled={placing || loading || refreshing}>
              {placing ? "Оформляем…" : "Оформить заказ"}
            </button>
            <button className="btn ghost full-width-on-mobile" onClick={onClearCart} disabled={placing || loading || refreshing}>
              Очистить
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
