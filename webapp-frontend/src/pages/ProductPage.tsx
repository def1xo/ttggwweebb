import React, { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../services/api";
import { addCartItem } from "../services/api";
import ColorSwatch from "../components/ColorSwatch";
import { useToast } from "../contexts/ToastContext";
import { useFavorites } from "../contexts/FavoritesContext";
import { hapticImpact } from "../utils/tg";
import { HeartSmall } from "../components/Icons";

function uniq(arr: string[]) {
  return Array.from(new Set(arr.filter(Boolean)));
}

function sortSizes(values: string[]) {
  return values.slice().sort((a, b) => {
    const na = Number(String(a).replace(",", "."));
    const nb = Number(String(b).replace(",", "."));
    const ia = Number.isFinite(na);
    const ib = Number.isFinite(nb);
    if (ia && ib) return na - nb;
    if (ia && !ib) return -1;
    if (!ia && ib) return 1;
    return String(a).localeCompare(String(b));
  });
}

export default function ProductPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const { notify } = useToast();
  const { isFavorite, toggle } = useFavorites();

  const [product, setProduct] = useState<any>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [selectedSize, setSelectedSize] = useState<string | null>(null);
  const [selectedColor, setSelectedColor] = useState<string | null>(null);

  const touchX = useRef<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get(`/api/products/${id}`);
        const p = (res as any).data ?? res;
        setProduct(p);
      } catch (e) {
        setProduct(null);
      }
    })();
  }, [id]);

  const images: string[] = useMemo(() => {
    if (!product) return [];
    const imgs = (product.images || product.image_urls || []) as any[];
    const list = imgs.map((x) => String(x?.url || x)).filter(Boolean);
    if (product.default_image) list.unshift(String(product.default_image));
    // uniq preserving order
    const seen = new Set<string>();
    return list.filter((u) => {
      if (seen.has(u)) return false;
      seen.add(u);
      return true;
    });
  }, [product]);

  const variants: any[] = useMemo(() => (product?.variants || []) as any[], [product]);

  const sizes = useMemo(() => {
    const s = uniq(variants.map((v) => String(v?.size?.name || v?.size || "")).filter(Boolean));
    return sortSizes(s);
  }, [variants]);

  const colors = useMemo(() => {
    return uniq(variants.map((v) => String(v?.color?.name || v?.color || "")).filter(Boolean));
  }, [variants]);

  const price = useMemo(() => {
    const base = Number(product?.price ?? product?.base_price ?? 0);
    const vMatch = variants.find((v) => {
      const s = String(v?.size?.name || v?.size || "");
      const c = String(v?.color?.name || v?.color || "");
      return (!selectedSize || s === selectedSize) && (!selectedColor || c === selectedColor);
    });
    const vPrice = vMatch ? Number(vMatch.price ?? 0) : 0;
    return vPrice || base;
  }, [product, variants, selectedSize, selectedColor]);

  const activeImage = images[activeIndex] || product?.default_image || "/demo/kofta1.jpg";

  const onTouchStart = (e: React.TouchEvent) => {
    touchX.current = e.touches?.[0]?.clientX ?? null;
  };
  const onTouchEnd = (e: React.TouchEvent) => {
    const start = touchX.current;
    const end = e.changedTouches?.[0]?.clientX ?? null;
    touchX.current = null;
    if (start == null || end == null) return;
    const dx = end - start;
    if (Math.abs(dx) < 40) return;
    if (dx < 0) setActiveIndex((i) => Math.min(i + 1, Math.max(0, images.length - 1)));
    else setActiveIndex((i) => Math.max(i - 1, 0));
  };

  const addToCart = () => {
    if (!product) return;
    let variant = variants[0];
    if (selectedSize || selectedColor) {
      const match = variants.find((v) => {
        const s = String(v?.size?.name || v?.size || "");
        const c = String(v?.color?.name || v?.color || "");
        return (!selectedSize || s === selectedSize) && (!selectedColor || c === selectedColor);
      });
      if (match) variant = match;
    }
    const variantId = product?.default_variant_id || variant?.id || product?.id;
    (async () => {
      try {
        await addCartItem(Number(variantId), 1);
        hapticImpact("light");
        notify("Добавлено в корзину", "success");
        try { window.dispatchEvent(new CustomEvent("cart:updated")); } catch {}
      } catch {
        notify("Не удалось добавить в корзину", "error");
      }
    })();
  };

  const toggleFav = () => {
    (async () => {
      try {
        await toggle(Number(product?.id));
        hapticImpact("light");
      } catch {
        // ignore
      }
    })();
  };

  if (!product) {
    return (
      <div className="container" style={{ paddingTop: 12 }}>
        <div className="card" style={{ padding: 16 }}>
          <div style={{ fontWeight: 900, marginBottom: 6 }}>Товар не найден</div>
          <div className="muted" style={{ marginBottom: 14 }}>
            Возможно, его скрыли или удалили.
          </div>
          <button className="btn" onClick={() => nav(-1)}>
            Назад
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="container" style={{ paddingTop: 12, paddingBottom: 120 }}>
      <div className="card" style={{ padding: 14 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <button className="btn" onClick={() => nav(-1)}>
            ←
          </button>
          <div style={{ fontWeight: 900, textAlign: "center", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {product.title}
          </div>
          <button
            type="button"
            className="icon-like-btn"
            onClick={toggleFav}
            aria-label={isFavorite(Number(product?.id)) ? "Убрать из избранного" : "В избранное"}
            style={{ width: 44, height: 44, padding: 0, lineHeight: 0, display: "grid", placeItems: "center", overflow: "visible", color: isFavorite(Number(product?.id)) ? "#ff5b7e" : undefined }}
          >
            <HeartSmall filled={isFavorite(Number(product?.id))} />
          </button>
        </div>

        <div
          style={{ marginTop: 12 }}
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
        >
          <img className="product-detail-hero" src={activeImage} alt={product.title} />

          {images.length > 1 ? (
            <div className="thumb-grid" style={{ marginTop: 10 }}>
              {images.map((u, idx) => (
                <img
                  key={`${u}_${idx}`}
                  className="thumb"
                  src={u}
                  alt=""
                  style={{ outline: idx === activeIndex ? "2px solid var(--ring)" : "none" }}
                  onClick={() => setActiveIndex(idx)}
                />
              ))}
            </div>
          ) : null}
        </div>

        <div style={{ marginTop: 14, display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
          <div style={{ fontWeight: 900, fontSize: 20 }}>{price.toLocaleString("ru-RU")} ₽</div>
        </div>

        {product.description ? <p style={{ marginTop: 10, color: "var(--text)" }}>{product.description}</p> : null}

        {colors.length ? (
          <div style={{ marginTop: 14 }}>
            <div className="muted" style={{ fontWeight: 800, marginBottom: 8 }}>
              Цвет
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {colors.map((c) => (
                <button
                  key={c}
                  type="button"
                  className="chip"
                  onClick={() => setSelectedColor((prev) => (prev === c ? null : c))}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    borderColor: selectedColor === c ? "var(--ring)" : undefined,
                  }}
                >
                  <ColorSwatch name={c} size={16} />
                  <span style={{ fontWeight: 800 }}>{c}</span>
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {sizes.length ? (
          <div style={{ marginTop: 14 }}>
            <div className="muted" style={{ fontWeight: 800, marginBottom: 8 }}>
              Размер
            </div>
            <div className="chips">
              {sizes.map((s) => {
                const active = selectedSize === s;
                return (
                  <button
                    key={s}
                    className="chip"
                    type="button"
                    onClick={() => setSelectedSize(active ? null : s)}
                    style={{ borderColor: active ? "var(--ring)" : undefined }}
                  >
                    {s}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        <div style={{ marginTop: 16, display: "grid", gap: 10 }}>
          <button className="btn btn-primary product-add-btn" onClick={addToCart}>
            Добавить в корзину
          </button>
        </div>
      </div>
    </div>
  );
}
