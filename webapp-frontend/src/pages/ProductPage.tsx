import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { addCartItem, getProduct, getRelatedProducts, trackAnalyticsEvent } from "../services/api";
import ColorSwatch from "../components/ColorSwatch";
import { useToast } from "../contexts/ToastContext";
import { useFavorites } from "../contexts/FavoritesContext";
import { hapticImpact } from "../utils/tg";
import { HeartSmall } from "../components/Icons";
import { getImagesForSelectedColor, isColorInStock } from "../utils/productMedia";

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

function normalizeMediaUrl(raw: unknown): string | null {
  if (!raw) return null;
  const url = String(raw).trim();
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  const base = String((import.meta as any).env?.VITE_BACKEND_URL || (import.meta as any).env?.VITE_API_URL || "").trim().replace(/\/+$/, "").replace(/\/api$/, "");
  if (url.startsWith("/")) return base ? `${base}${url}` : url;
  return base ? `${base}/${url}` : url;
}

function collectProductImages(p: any): string[] {
  if (!p) return [];
  const buckets = [p.images, p.default_image];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const bucket of buckets) {
    const list = Array.isArray(bucket) ? bucket : [bucket];
    for (const item of list) {
      const normalized = normalizeMediaUrl(item);
      if (!normalized || seen.has(normalized)) continue;
      seen.add(normalized);
      out.push(normalized);
    }
  }
  return out;
}

function getVariantStock(v: any): number {
  const raw = v?.stock_quantity ?? v?.stock ?? v?.quantity ?? v?.qty ?? 0;
  const value = Number(raw);
  return Number.isFinite(value) ? value : 0;
}

function pickImage(p: any): string | null {
  const all = collectProductImages(p);
  return all[0] || normalizeMediaUrl(p?.image) || null;
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
  const [isImageViewerOpen, setIsImageViewerOpen] = useState(false);
  const [slideDir, setSlideDir] = useState<"next" | "prev">("next");

  const touchX = useRef<number | null>(null);
  const viewerTouchX = useRef<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const p: any = await getProduct(String(id || ""));
        setProduct(p);
        if (p?.selected_color) setSelectedColor(String(p.selected_color));
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
    return getImagesForSelectedColor(product, selectedColor);
  }, [product, selectedColor]);

  useEffect(() => {
    setActiveIndex(0);
  }, [product?.id]);

  useEffect(() => {
    if (activeIndex < images.length) return;
    setActiveIndex(0);
  }, [activeIndex, images.length]);

  useEffect(() => {
    if (!isImageViewerOpen) return;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") setIsImageViewerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isImageViewerOpen]);

  const variants: any[] = useMemo(() => (product?.variants || []) as any[], [product]);

  const sizes = useMemo(() => {
    const relevantVariants = selectedColor
      ? variants.filter((v) => String(v?.color?.name || v?.color || "") === selectedColor)
      : variants;
    const fromVariants = relevantVariants.map((v) => String(v?.size?.name || v?.size || "")).filter(Boolean);
    const fromProduct = !selectedColor && Array.isArray(product?.sizes)
      ? product.sizes.map((x: any) => String(x || "")).filter(Boolean)
      : [];
    return sortSizes(uniq([...fromVariants, ...fromProduct]).filter(isReasonableSize));
  }, [variants, product?.sizes, selectedColor]);

  const colors = useMemo(() => {
    const fromVariants = variants.map((v) => String(v?.color?.name || v?.color || "")).filter(Boolean);
    const fromProduct = Array.isArray(product?.colors) ? product.colors.map((x: any) => String(x || "")).filter(Boolean) : [];
    const fromColorVariants = Array.isArray(product?.available_colors) ? product.available_colors.map((x: any) => String(x || "")).filter(Boolean) : [];
    return uniq([...fromVariants, ...fromProduct, ...fromColorVariants]);
  }, [variants, product?.colors, product?.available_colors]);

  const colorHasAnyStock = useMemo(() => {
    const out: Record<string, boolean> = {};
    for (const c of colors) {
      out[c] = isColorInStock(variants, c);
    }
    return out;
  }, [colors, variants]);

  const sizeOptions = sizes;

  const variantStockBySize = useMemo(() => {
    const out: Record<string, number> = {};
    for (const v of variants) {
      const sz = String(v?.size?.name || v?.size || "").trim();
      if (!sz) continue;
      const stock = getVariantStock(v);
      out[sz] = (out[sz] || 0) + Math.max(0, stock);
    }
    return out;
  }, [variants]);

  const colorAvailabilityBySelectedSize = useMemo(() => {
    const out: Record<string, boolean> = {};
    if (!selectedSize) {
      for (const c of colors) out[c] = true;
      return out;
    }
    for (const c of colors) {
      const hasForSize = variants.some((v) => {
        const s = String(v?.size?.name || v?.size || "").trim();
        const vc = String(v?.color?.name || v?.color || "");
        return s === selectedSize && vc === c && getVariantStock(v) > 0;
      });
      out[c] = hasForSize;
    }
    return out;
  }, [colors, variants, selectedSize]);



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
        // when there is no actual variant for this size, it must be unavailable
        out[sz] = false;
        continue;
      }
      const inStock = vv.some((v) => {
        const c = String(v?.color?.name || v?.color || "");
        const colorOk = !selectedColor || c === selectedColor;
        return colorOk && getVariantStock(v) > 0;
      });
      out[sz] = inStock;
    }
    return out;
  }, [variants, sizeOptions, selectedColor, sizes]);

  const hasAnyStock = useMemo(
    () => variants.some((v) => getVariantStock(v) > 0),
    [variants],
  );

  const selectedVariant = useMemo(() => {
    return variants.find((v) => {
      const s = String(v?.size?.name || v?.size || "");
      const c = String(v?.color?.name || v?.color || "");
      return (!selectedSize || s === selectedSize) && (!selectedColor || c === selectedColor);
    }) || null;
  }, [variants, selectedSize, selectedColor]);

  useEffect(() => {
    if (!selectedSize || !selectedColor) return;
    if (sizeAvailability[selectedSize]) return;
    setSelectedSize(null);
  }, [selectedColor, selectedSize, sizeAvailability]);

  const showColorPicker = colors.length > 1;
  const selectionMissing = (sizeOptions.length > 0 && !selectedSize) || (showColorPicker && !selectedColor);
  const selectedColorInStock = !selectedColor || Boolean(colorHasAnyStock[selectedColor]);

  const price = useMemo(() => {
    const base = Number(product?.price ?? product?.base_price ?? 0);
    const vMatch = selectedVariant;
    const vPrice = vMatch ? Number(vMatch.price ?? 0) : 0;
    return vPrice || base;
  }, [product, selectedVariant]);

  const activeImage = images[activeIndex] || normalizeMediaUrl(product?.default_image) || "/logo_black.png";

  const goToNextImage = () => {
    if (images.length <= 1) return;
    setSlideDir("next");
    setActiveIndex((i) => (i + 1) % images.length);
  };

  const goToPrevImage = () => {
    if (images.length <= 1) return;
    setSlideDir("prev");
    setActiveIndex((i) => (i - 1 + images.length) % images.length);
  };

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
    if (dx < 0) goToNextImage();
    else goToPrevImage();
  };

  const onViewerTouchStart = (e: React.TouchEvent) => {
    viewerTouchX.current = e.touches?.[0]?.clientX ?? null;
  };

  const onViewerTouchEnd = (e: React.TouchEvent) => {
    const start = viewerTouchX.current;
    const end = e.changedTouches?.[0]?.clientX ?? null;
    viewerTouchX.current = null;
    if (start == null || end == null) return;
    const dx = end - start;
    if (Math.abs(dx) < 40) return;
    e.stopPropagation();
    if (dx < 0) goToNextImage();
    else goToPrevImage();
  };

  const addToCart = () => {
    if (!product) return;
    if (selectionMissing) {
      notify(sizeOptions.length > 0 && !selectedSize ? "Выбери размер перед добавлением" : "Выбери цвет перед добавлением", "error");
      return;
    }
    if (!selectedColorInStock) {
      notify("Нет в наличии. Выберите другой цвет", "error");
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
    if (getVariantStock(variant) <= 0) {
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
          <img key={`${activeImage}_${slideDir}`} className={`product-detail-hero product-detail-hero--${slideDir} image-fade-in`} src={activeImage} alt={product.title} style={{ cursor: "zoom-in" }} loading="eager" onClick={() => setIsImageViewerOpen(true)} />

          {images.length > 1 ? (
            <div className="thumb-grid" style={{ marginTop: 10 }}>
              {images.map((u, idx) => (
                <img
                  key={`${u}_${idx}`}
                  className="thumb image-fade-in"
                  src={u}
                  loading="lazy"
                  alt=""
                  style={{ outline: idx === activeIndex ? "2px solid var(--ring)" : "none" }}
                  onClick={() => {
                    setSlideDir(idx >= activeIndex ? "next" : "prev");
                    setActiveIndex(idx);
                  }}
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

        {showColorPicker ? (
          <div style={{ marginTop: 14 }}>
            <div className="muted" style={{ fontWeight: 800, marginBottom: 8 }}>
              Цвет
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {colors.map((c) => {
                const outOfStock = !colorHasAnyStock[c];
                return (
                <button
                  key={c}
                  type="button"
                  className="chip"
                  onClick={() => setSelectedColor(c)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    borderColor: selectedColor === c ? "var(--ring)" : undefined,
                    opacity: outOfStock || (selectedSize && !colorAvailabilityBySelectedSize[c]) ? 0.45 : 1,
                    filter: outOfStock || (selectedSize && !colorAvailabilityBySelectedSize[c]) ? "grayscale(0.35)" : "none",
                  }}
                >
                  <ColorSwatch name={c} size={16} />
                  <span style={{ fontWeight: 800 }}>{c}</span>
                  {outOfStock ? <span className="small-muted">нет в наличии</span> : null}
                </button>
                );
              })}
            </div>
            {selectedColor && !selectedColorInStock ? (
              <div className="small-muted" style={{ marginTop: 8, color: "#ff9b9b" }}>
                Нет в наличии для выбранного цвета.
              </div>
            ) : null}
          </div>
        ) : null}

        {sizeOptions.length ? (
          <div style={{ marginTop: 14 }}>
            <div className="muted" style={{ fontWeight: 800, marginBottom: 8 }}>
              Размер
            </div>
            {!selectedColorInStock ? (<div className="small-muted" style={{ marginBottom: 8, color: "#ff9b9b" }}>Размеры для этого цвета недоступны</div>) : null}
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
                    title={available ? `В наличии: ${Math.max(0, Number(variantStockBySize[s] || 0))} шт` : "Нет этого размера"}
                  >
                    {s}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        <div style={{ marginTop: 16, display: "grid", gap: 10 }}>
          <button
            className="btn btn-primary product-add-btn"
            onClick={addToCart}
            disabled={!hasAnyStock || !selectedColorInStock || (selectedVariant ? getVariantStock(selectedVariant) <= 0 : false)}
          >
            {!hasAnyStock || !selectedColorInStock ? "Нет в наличии" : "Добавить в корзину"}
          </button>
        </div>
      </div>


      {isImageViewerOpen ? (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setIsImageViewerOpen(false)}
          onTouchStart={onViewerTouchStart}
          onTouchEnd={onViewerTouchEnd}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            background: "rgba(0,0,0,0.92)",
            display: "grid",
            placeItems: "center",
            padding: 16,
          }}
        >
          <button
            type="button"
            className="image-viewer__close"
            onClick={() => setIsImageViewerOpen(false)}
            onTouchEnd={(e) => e.stopPropagation()}
            aria-label="Закрыть полноэкранный просмотр"
          >
            Закрыть ✕
          </button>

          {images.length > 1 ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                goToPrevImage();
              }}
              style={{
                position: "fixed",
                left: 10,
                top: "50%",
                transform: "translateY(-50%)",
                width: 44,
                height: 44,
                borderRadius: 999,
                border: "1px solid rgba(255,255,255,0.25)",
                background: "rgba(18,18,18,0.7)",
                color: "#fff",
                fontSize: 26,
              }}
              aria-label="Предыдущее фото"
            >
              ‹
            </button>
          ) : null}

          <img
            key={`viewer_${activeImage}_${slideDir}`}
            src={activeImage}
            alt={product.title}
            onClick={(e) => e.stopPropagation()}
            className={`image-viewer__img image-viewer__img--${slideDir}`}
            style={{ maxWidth: "100%", maxHeight: "90vh", objectFit: "contain", borderRadius: 12 }}
          />

          {images.length > 1 ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                goToNextImage();
              }}
              style={{
                position: "fixed",
                right: 10,
                top: "50%",
                transform: "translateY(-50%)",
                width: 44,
                height: 44,
                borderRadius: 999,
                border: "1px solid rgba(255,255,255,0.25)",
                background: "rgba(18,18,18,0.7)",
                color: "#fff",
                fontSize: 26,
              }}
              aria-label="Следующее фото"
            >
              ›
            </button>
          ) : null}
        </div>
      ) : null}

      {related.length > 0 ? (
        <div className="card" style={{ marginTop: 12, padding: 14 }}>
          <div className="panel-title" style={{ marginBottom: 10 }}>С этим берут</div>
          <div className="related-row">
            {related.map((p) => {
              const pid = Number(p?.id);
              const pTitle = String(p?.title || p?.name || "Товар");
              const pPrice = Number(p?.price ?? p?.base_price ?? 0);
              const img = pickImage(p);
              const pInStock = Boolean(
                p?.has_stock ??
                  (Array.isArray(p?.variants)
                    ? p.variants.some((v: any) => Number(v?.stock_quantity ?? v?.stock ?? 0) > 0)
                    : true),
              );
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
