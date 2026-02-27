import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Collapsible from "./Collapsible";
import { useFavorites } from "../contexts/FavoritesContext";
import { hapticImpact, hapticSelection } from "../utils/tg";

function sanitizeProductTitle(raw: unknown): string {
  const t = String(raw || "").trim();
  if (!t) return "Товар";
  return t.replace(/\s*#\d+\s*$/g, "").trim() || "Товар";
}

type Props = {
  product: any;
  index?: number;
  compact?: boolean;
  onRemoved?: (productId: number) => void;
};

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

function pickImage(product: any): string | null {
  const imgs = (product?.images || product?.image_urls || product?.imageUrls || []) as any[];
  return (
    (Array.isArray(imgs) && imgs.length ? (imgs[0]?.url || imgs[0]) : null) ||
    product?.default_image ||
    product?.image ||
    null
  );
}

function money(v: any): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  try {
    return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(n);
  } catch {
    return String(Math.round(n));
  }
}

export default function FavoriteRow({ product, index = 0, compact = false, onRemoved }: Props) {
  const { toggle } = useFavorites();
  const [open, setOpen] = useState(false);
  const [removing, setRemoving] = useState(false);

  const pid = Number(product?.id);
  const title = sanitizeProductTitle(product?.title || product?.name || "Товар");
  const image = pickImage(product);

  const meta = useMemo(() => {
    const variants = (product?.variants || []) as any[];
    const sizes = sortSizes(
      uniq(
        variants
          .map((v) => String(v?.size?.name || v?.size || ""))
          .filter(Boolean)
      )
    );
    const colors = uniq(
      variants
        .map((v) => String(v?.color?.name || v?.color || ""))
        .filter(Boolean)
    );

    let sizeLabel = "";
    if (sizes.length === 1) sizeLabel = sizes[0];
    else if (sizes.length > 1) sizeLabel = `${sizes[0]}–${sizes[sizes.length - 1]}`;

    const price = Number(product?.price ?? product?.base_price ?? variants?.[0]?.price ?? 0);

    return {
      sizes,
      colors,
      sizeLabel,
      colorsCount: colors.length,
      price,
    };
  }, [product]);

  const delay = `${Math.min(index * 35, 240)}ms`;

  const onToggle = (e: React.MouseEvent) => {
    e.preventDefault();
    setOpen((v) => !v);
    try {
      hapticImpact("light");
    } catch {}
  };

  const onRemove = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!Number.isFinite(pid)) return;

    setRemoving(true);
    try {
      hapticImpact("light");
    } catch {}

    // Optimistic remove from list in parent
    try {
      onRemoved?.(pid);
    } catch {}

    try {
      await toggle(pid);
    } catch {
      // if failed, parent can refresh
    } finally {
      setRemoving(false);
    }
  };

  const onOpenClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      hapticSelection();
    } catch {}
  };

  return (
    <div
      className={`card fav-row list-item-animate ${compact ? "compact" : ""}`.trim()}
      style={{ padding: 12, animationDelay: delay }}
    >
      <button
        className="fav-row__head"
        onClick={onToggle}
        type="button"
        style={{
          width: "100%",
          textAlign: "left",
          background: "transparent",
          border: "none",
          padding: 0,
          color: "inherit",
          cursor: "pointer",
        }}
      >
        <div className="fav-row__left">
          <div className="fav-row__thumb" aria-hidden>
            {image ? <img src={String(image)} alt={title} /> : <div className="no-image">NO IMAGE</div>}
          </div>

          <div className="fav-row__meta">
            <div className="fav-row__title">{title}</div>
            <div className="fav-row__sub">
              {meta.price ? <span className="fav-row__price">{money(meta.price)} ₽</span> : null}
              <div className="chips" style={{ gap: 6 }}>
                {meta.sizeLabel ? <span className="chip chip-sm">{meta.sizeLabel}</span> : null}
                {meta.colorsCount ? <span className="chip chip-sm">{meta.colorsCount} цвет(а)</span> : null}
              </div>
            </div>
          </div>
        </div>

        <div className="fav-row__right" onClick={(e) => e.stopPropagation()}>
          <div className="fav-row__actions">
            <Link
              to={`/product/${Number.isFinite(pid) ? pid : product?.id}`}
              className="btn btn-secondary btn-sm"
              onClick={onOpenClick}
              style={{ textDecoration: "none" }}
            >
              Открыть
            </Link>
            <button type="button" className="btn ghost btn-sm" onClick={onRemove} disabled={removing}>
              {removing ? "…" : "Убрать"}
            </button>
          </div>
          <div className={`chev ${open ? "open" : ""}`} aria-hidden>
            ▾
          </div>
        </div>
      </button>

      <Collapsible open={open} duration={240}>
        <div className="fav-row__body">
          {meta.sizes.length ? (
            <div className="fav-row__block">
              <div className="small-muted" style={{ marginBottom: 6 }}>
                Размеры
              </div>
              <div className="chips">
                {meta.sizes.slice(0, 10).map((s) => (
                  <span key={s} className="chip">
                    {s}
                  </span>
                ))}
                {meta.sizes.length > 10 ? <span className="chip">+{meta.sizes.length - 10}</span> : null}
              </div>
            </div>
          ) : null}

          {meta.colors.length ? (
            <div className="fav-row__block">
              <div className="small-muted" style={{ marginBottom: 6 }}>
                Цвета
              </div>
              <div className="chips">
                {meta.colors.slice(0, 10).map((c) => (
                  <span key={c} className="chip">
                    {c}
                  </span>
                ))}
                {meta.colors.length > 10 ? <span className="chip">+{meta.colors.length - 10}</span> : null}
              </div>
            </div>
          ) : null}

          {product?.description ? (
            <div className="fav-row__block">
              <div className="small-muted" style={{ marginBottom: 6 }}>
                Описание
              </div>
              <div style={{ lineHeight: 1.35, opacity: 0.92 }}>
                {String(product.description).slice(0, compact ? 120 : 220)}
                {String(product.description).length > (compact ? 120 : 220) ? "…" : ""}
              </div>
            </div>
          ) : null}
        </div>
      </Collapsible>
    </div>
  );
}
