import React, { useMemo } from "react";
import { Link } from "react-router-dom";
import { useToast } from "../contexts/ToastContext";
import { useFavorites } from "../contexts/FavoritesContext";
import { hapticImpact } from "../utils/tg";
import ColorSwatch from "./ColorSwatch";
import { HeartSmall } from "./Icons";
import { addCartItem } from "../services/api";

type Props = {
  product: any;
};

function uniq(arr: string[]) {
  return Array.from(new Set(arr.filter(Boolean)));
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

export default function ProductCard({ product }: Props) {
  const { notify } = useToast();
  const { isFavorite, toggle } = useFavorites();

  const title = (product?.title || product?.name || "Товар") as string;
  const imgs = (product?.images || product?.image_urls || product?.imageUrls || []) as any[];
  const image =
    (Array.isArray(imgs) && imgs.length ? (imgs[0]?.url || imgs[0]) : null) ||
    product?.default_image ||
    "/demo/kofta1.jpg";

  const variantList = (product?.variants || []) as any[];
  const defaultVariant = variantList?.[0] || null;
  const defaultVariantId = product?.default_variant_id || defaultVariant?.id || product?.id;

  const price = Number(product?.price ?? product?.base_price ?? defaultVariant?.price ?? 0);

  const meta = useMemo(() => {
    const sizes = sortSizes(
      uniq(
        (variantList || [])
          .map((v) => String(v?.size?.name || v?.size || ""))
          .filter(Boolean)
      )
    );
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

    return { sizes, colors, sizeLabel, isNew };
  }, [product, variantList]);

  const addToCart = async (e?: React.MouseEvent) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    const variantId = defaultVariantId;
    try {
      await addCartItem(Number(variantId), 1);
      hapticImpact("light");
      notify("Добавлено в корзину", "success");
      try { window.dispatchEvent(new CustomEvent("cart:updated")); } catch {}
    } catch {
      notify("Не удалось добавить в корзину", "error");
    }
  };

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
          <img src={image} alt={title} style={{ width: "100%", height: 160, objectFit: "cover", borderRadius: 12 }} />
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
          <div className="quick-add">
            <button type="button" onClick={addToCart} aria-label="Добавить в корзину">
              В корзину
            </button>
          </div>
        </div>

        <div style={{ padding: "12px 12px 14px" }}>
          <div style={{ fontWeight: 900, lineHeight: 1.25 }}>{title}</div>
          <div className="muted" style={{ marginTop: 6, fontWeight: 800 }}>
            {price.toLocaleString("ru-RU")} ₽
          </div>

          {(meta.sizeLabel || meta.colors.length) ? (
            <div className="mini-row">
              <div className="chips">
                {meta.sizeLabel ? <span className="chip">{meta.sizeLabel}</span> : null}
                {meta.colors.length ? <span className="chip">{meta.colors.length} цвет(а)</span> : null}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                {meta.colors.slice(0, 2).map((c) => (
                  <ColorSwatch key={c} name={c} size={14} />
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </Link>
  );
}
