import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import api, { addCartItem, getRelatedProducts, trackAnalyticsEvent } from "../services/api";
import ColorSwatch from "../components/ColorSwatch";
import { useToast } from "../contexts/ToastContext";
import { useFavorites } from "../contexts/FavoritesContext";
import { hapticImpact } from "../utils/tg";
import { HeartSmall } from "../components/Icons";

function uniq(arr: string[]) {
  return Array.from(new Set(arr.filter(Boolean)));
}

function isReasonableSize(v: string): boolean {
  const t = String(v || "").trim();
  if (!t) return false;
  const n = Number(t.replace(",", "."));
  if (Number.isFinite(n)) return n >= 20 && n <= 60;
  return true;
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


function isFootwearProduct(title: string, categoryName?: string): boolean {
  const hay = `${title || ""} ${categoryName || ""}`.toLowerCase();
  return /(new\s*balance|\bnb\b|nike|adidas|jordan|yeezy|air\s*max|dunk|campus|samba|gazelle|vomero|крос|кед|обув)/i.test(hay);
}

const DEFAULT_SHOE_SIZE_RANGE = Array.from({ length: 10 }, (_, i) => String(36 + i));

function normalizeMediaUrl(raw: unknown): string | null {
  if (!raw) return null;
  const url = String(raw).trim();
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  const base = String((import.meta as any).env?.VITE_BACKEND_URL || (import.meta as any).env?.VITE_API_URL || "").trim().replace(/\/+$/, "").replace(/\/api$/, "");
  if (url.startsWith("/")) return base ? `${base}${url}` : url;
  return base ? `${base}/${url}` : url;
}

function pickImage(p: any): string | null {
  const imgs = (p?.images || p?.image_urls || p?.imageUrls || []) as any[];
  const raw =
    (Array.isArray(imgs) && imgs.length ? (imgs[0]?.url || imgs[0]) : null) ||
    p?.default_image ||
    p?.image ||
    null;
  return normalizeMediaUrl(raw);
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
  const [related, setRelated] = useState<any[]>([]);

  const touchX = useRef<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get(`/api/products/${id}`);
        const p = (res as any).data ?? res;
        setProduct(p);
      } catch {
        setProduct(null);
      }
    })();
  }, [id]);

  useEffect(() => {
    (async () => {
      if (!product?.id) {
        setRelated([]);
        return;
      }
      try {
        const res: any = await getRelatedProducts(Number(product.id), 8);
        const data = (res as any)?.data ?? res;
        const list = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : []);
        setRelated(list.slice(0, 8));
      } catch {
        setRelated([]);
      }
    })();
  }, [product?.id, product?.category_id]);

  useEffect(() => {
    if (!product?.id) return;
    trackAnalyticsEvent({
      event: "view_product",
      product_id: Number(product.id),
      category_id: Number(product?.category_id || 0) || null,
      source: "product_page",
    });
  }, [product?.id, product?.category_id]);


  const images: string[] = useMemo(() => {
    if (!product) return [];
    const imgs = (product.images || product.image_urls || []) as any[];
    const list = imgs.map((x) => normalizeMediaUrl(x?.url || x)).filter(Boolean) as string[];
    if (product.default_image) {
      const d = normalizeMediaUrl(product.default_image);
      if (d) list.unshift(d);
    }
    const seen = new Set<string>();
    return list.filter((u) => {
      if (seen.has(u)) return false;
      seen.add(u);
      return true;
    });
  }, [product]);

  const variants: any[] = useMemo(() => (product?.variants || []) as any[], [product]);

  const sizes = useMemo(() => {
    const fromVariants = variants.map((v) => String(v?.size?.name || v?.size || "")).filter(Boolean);
    const fromProduct = Array.isArray(product?.sizes) ? product.sizes.map((x: any) => String(x || "")).filter(Boolean) : [];
    return sortSizes(uniq([...fromVariants, ...fromProduct]).filter(isReasonableSize));
  }, [variants, product?.sizes]);

  const colors = useMemo(() => {
    const fromVariants = variants.map((v) => String(v?.color?.name || v?.color || "")).filter(Boolean);
    const fromProduct = Array.isArray(product?.colors) ? product.colors.map((x: any) => String(x || "")).filter(Boolean) : [];
    return uniq([...fromVariants, ...fromProduct]);
  }, [variants, product?.colors]);

  const sizeOptions = sizes;

  const sizeAvailability = useMemo(() => {
    const out: Record<string, boolean> = {};
    const variantBySize = new Map<string, any[]>();
    for (const v of variants) {
      const sz = String(v?.size?.name || v?.size || "").trim();
      if (!sz) continue;
      const arr = variantBySize.get(sz) || [];
      arr.push(v);
      variantBySize.set(sz, arr);
    }

    for (const sz of sizeOptions) {
      const vv = variantBySize.get(sz) || [];
      if (vv.length === 0) {
        out[sz] = sizes.includes(sz);
        continue;
      }
      const inStock = vv.some((v) => {
        const c = String(v?.color?.name || v?.color || "");
        const colorOk = !selectedColor || c === selectedColor;
        return colorOk && Number(v?.stock ?? 0) > 0;
      });
      out[sz] = inStock;
    }
    return out;
  }, [variants, sizeOptions, selectedColor, sizes]);

  const hasAnyStock = useMemo(() => variants.some((v) => Number(v?.stock ?? 0) > 0), [variants]);

  const selectedVariant = useMemo(() => {
    return variants.find((v) => {
      const s = String(v?.size?.name || v?.size || "");
      const c = String(v?.color?.name || v?.color || "");
      return (!selectedSize || s === selectedSize) && (!selectedColor || c === selectedColor);
    }) || null;
  }, [variants, selectedSize, selectedColor]);

  const selectionMissing = (sizeOptions.length > 0 && !selectedSize) || (colors.length > 0 && !selectedColor);

  const price = useMemo(() => {
    const base = Number(product?.price ?? product?.base_price ?? 0);
    const vMatch = selectedVariant;
    const vPrice = vMatch ? Number(vMatch.price ?? 0) : 0;
    return vPrice || base;
  }, [product, selectedVariant]);

  const activeImage = images[activeIndex] || normalizeMediaUrl(product?.default_image) || "/logo_black.png";

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
    if (selectionMissing) {
      notify("Выбери размер и цвет перед добавлением", "error");
      return;
    }
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
    if (Number(variant?.stock ?? 0) <= 0) {
      notify("Товар сейчас не в наличии", "error");
      return;
    }
    (async () => {
      try {
        await addCartItem(Number(variantId), 1);
        hapticImpact("light");
        notify("Добавлено в корзину", "success");
        trackAnalyticsEvent({
          event: "add_to_cart",
          product_id: Number(product?.id || 0) || null,
          variant_id: Number(variantId),
          source: "product_page_main_cta",
        });
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

  const addRelatedToCart = async (item: any) => {
    const variants = Array.isArray(item?.variants) ? item.variants : [];
    const variantId = Number(item?.default_variant_id || variants?.[0]?.id || item?.id || 0);
    if (!Number.isFinite(variantId) || variantId <= 0) return;
    try {
      await addCartItem(variantId, 1);
      notify("Товар добавлен в корзину", "success");
      trackAnalyticsEvent({
        event: "add_to_cart",
        product_id: Number(item?.id || 0) || null,
        variant_id: variantId,
        source: "product_page_related",
      });
      try { window.dispatchEvent(new CustomEvent("cart:updated")); } catch {}
      hapticImpact("light");
    } catch {
      notify("Не удалось добавить товар", "error");
    }
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
          {!hasAnyStock ? <span className="chip" style={{ color: "#ff8e8e", borderColor: "rgba(255,120,120,0.45)" }}>Нет в наличии</span> : null}
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

        {sizeOptions.length ? (
          <div style={{ marginTop: 14 }}>
            <div className="muted" style={{ fontWeight: 800, marginBottom: 8 }}>
              Размер
            </div>
            <div className="chips">
              {sizeOptions.map((s) => {
                const active = selectedSize === s;
                const available = Boolean(sizeAvailability[s]);
                return (
                  <button
                    key={s}
                    className="chip"
                    type="button"
                    disabled={!available}
                    onClick={() => setSelectedSize(active ? null : s)}
                    style={{
                      borderColor: active ? "var(--ring)" : undefined,
                      opacity: available ? 1 : 0.45,
                      textDecoration: available ? "none" : "line-through",
                      cursor: available ? "pointer" : "not-allowed",
                    }}
                    title={available ? "В наличии" : "Нет этого размера"}
                  >
                    {s}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        <div style={{ marginTop: 16, display: "grid", gap: 10 }}>
          <button className="btn btn-primary product-add-btn" onClick={addToCart} disabled={!hasAnyStock || (selectedVariant ? Number(selectedVariant?.stock ?? 0) <= 0 : false)}>
            {!hasAnyStock ? "Нет в наличии" : "Добавить в корзину"}
          </button>
        </div>
      </div>

      {related.length > 0 ? (
        <div className="card" style={{ marginTop: 12, padding: 14 }}>
          <div className="panel-title" style={{ marginBottom: 10 }}>С этим берут</div>
          <div className="related-row">
            {related.map((p) => {
              const pid = Number(p?.id);
              const pTitle = String(p?.title || p?.name || "Товар");
              const pPrice = Number(p?.price ?? p?.base_price ?? 0);
              const img = pickImage(p);
              const pInStock = Boolean(p?.has_stock ?? (Array.isArray(p?.variants) ? p.variants.some((v: any) => Number(v?.stock ?? 0) > 0) : true));
              return (
                <div key={pid} className="related-item" style={{ borderRadius: 16, padding: 10, background: "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01))", border: "1px solid var(--border)" }}>
                  <Link to={`/product/${pid}`} style={{ textDecoration: "none", color: "inherit" }}>
                    <div className="related-thumb">{img ? <img src={img} alt={pTitle} /> : null}</div>
                    <div className="related-title">{pTitle}</div>
                  </Link>
                  <div style={{ marginTop: 6, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                    <div className="small-muted" style={{ fontWeight: 700 }}>
                      {Number.isFinite(pPrice) && pPrice > 0 ? `${pPrice.toLocaleString("ru-RU")} ₽` : "—"}
                    </div>
                    <button className="btn btn-sm" type="button" onClick={() => addRelatedToCart(p)} disabled={!pInStock}>
                      + В корзину
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
