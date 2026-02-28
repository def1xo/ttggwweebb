import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useFavorites } from "../contexts/FavoritesContext";
import { hapticImpact } from "../utils/tg";
import ColorSwatch from "./ColorSwatch";
import { HeartSmall } from "./Icons";

type Props = {
  product: any;
};

function uniq(arr: string[]) {
  return Array.from(new Set(arr.filter(Boolean)));
}

function isReasonableSizeChip(v: string): boolean {
  const t = String(v || "").trim();
  if (!t) return false;
  const n = Number(t.replace(",", "."));
  if (Number.isFinite(n)) return n >= 20 && n <= 60;
  return true;
}

function sortSizes(values: string[]) {
  // numeric sort when possible, otherwise lexicographic
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

function sanitizeProductTitle(raw: unknown): string {
  const t = String(raw || "").trim();
  if (!t) return "Товар";
  return t.replace(/\s*#\d+\s*$/g, "").trim() || "Товар";
}

function normalizeMediaUrl(raw: unknown): string | null {
  if (!raw) return null;
  const url = String(raw).trim();
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;

  const base = String((import.meta as any).env?.VITE_BACKEND_URL || (import.meta as any).env?.VITE_API_URL || "").trim().replace(/\/+$/, "").replace(/\/api$/, "");
  if (url.startsWith("/")) {
    return base ? `${base}${url}` : url;
  }
  return base ? `${base}/${url}` : url;
}

export default function ProductCard({ product }: Props) {
  const { isFavorite, toggle } = useFavorites();

  const title = sanitizeProductTitle(product?.title || product?.name || "Товар");
  const imgs = (product?.images || product?.image_urls || product?.imageUrls || []) as any[];
  const rawImage =
    (Array.isArray(imgs) && imgs.length ? (imgs[0]?.url || imgs[0]) : null) ||
    product?.default_image ||
    null;
  const validImage = normalizeMediaUrl(rawImage);
  const [cardImage, setCardImage] = useState<string | null>(validImage);

  const variantList = (product?.variants || []) as any[];
  const defaultVariant = variantList?.[0] || null;

  const price = Number(product?.price ?? product?.min_variant_price ?? product?.base_price ?? defaultVariant?.price ?? 0);

  const meta = useMemo(() => {
    const variantSizes = (variantList || [])
      .map((v) => String(v?.size?.name || v?.size || ""))
      .filter(Boolean);
    const productSizes = Array.isArray(product?.sizes) ? product.sizes.map((x: any) => String(x || "")).filter(Boolean) : [];
    const sizes = sortSizes(uniq([...variantSizes, ...productSizes]).filter(isReasonableSizeChip));
    const colors = uniq(
      (variantList || [])
        .map((v) => String(v?.color?.name || v?.color || ""))
        .filter(Boolean)
    );

    let sizeLabel = "";
    if (sizes.length === 1) sizeLabel = sizes[0];
    else if (sizes.length > 1) {
      const first = sizes[0];
      const last = sizes[sizes.length - 1];
      sizeLabel = `${first}–${last}`;
    }

    const created = product?.created_at ? new Date(product.created_at) : null;
    const isNew = created ? Date.now() - created.getTime() < 7 * 24 * 60 * 60 * 1000 : false;
    const inStock = Boolean(product?.has_stock ?? (variantList || []).some((v) => Number(v?.stock || 0) > 0));
    const showColorMeta = colors.length > 1;
    return { sizes, colors, sizeLabel, isNew, inStock, showColorMeta };
  }, [product, variantList, imgs]);


  const toggleFav = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await toggle(Number(product?.id));
      hapticImpact("light");
    } catch {}
  };

  return (
    <Link to={`/product/${product?.id}`} className="card" style={{ textDecoration: "none", color: "inherit" }}>
      <div className="product-card">
        <div className="product-thumb">
          {cardImage ? (
            <img src={cardImage} alt={title} loading="lazy" decoding="async" onError={() => setCardImage(null)} style={{ width: "100%", height: 160, objectFit: "cover", borderRadius: 12 }} />
          ) : (
            <div aria-label="placeholder" style={{ width: "100%", height: 160, borderRadius: 12, background: "linear-gradient(135deg, rgba(255,255,255,0.10), rgba(255,255,255,0.03))", border: "1px solid var(--border)" }} />
          )}
          {meta.isNew ? <div className="badge">NEW</div> : null}
          <button
            type="button"
            onClick={toggleFav}
            aria-label={isFavorite(Number(product?.id)) ? "Убрать из избранного" : "В избранное"}
            style={{
              position: "absolute",
              top: 10,
              right: 10,
              width: 40,
              height: 40,
              display: "grid",
              placeItems: "center",
              borderRadius: 14,
              border: "1px solid var(--border)",
              background: "color-mix(in srgb, var(--bg) 78%, transparent)",
              backdropFilter: "blur(10px)",
              boxShadow: "var(--shadow-soft)",
              zIndex: 2,
            }}
          >
            <HeartSmall filled={isFavorite(Number(product?.id))} />
          </button>
        </div>

        <div style={{ padding: "12px 12px 14px" }}>
          <div style={{ fontWeight: 900, lineHeight: 1.25 }}>{title}</div>
          <div className="muted" style={{ marginTop: 6, fontWeight: 800 }}>
            {price.toLocaleString("ru-RU")} ₽
          </div>

          {(meta.sizeLabel || meta.showColorMeta || !meta.inStock) ? (
            <div className="mini-row">
              <div className="chips">
                {meta.sizeLabel ? <span className="chip">{meta.sizeLabel}</span> : null}
                {meta.showColorMeta ? <span className="chip">{meta.colors.length} цвет(а)</span> : null}
                {!meta.inStock ? <span className="chip">нет в наличии</span> : null}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                {meta.showColorMeta ? meta.colors.slice(0, 2).map((c) => (
                  <ColorSwatch key={c} name={c} size={14} />
                )) : null}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </Link>
  );
}
