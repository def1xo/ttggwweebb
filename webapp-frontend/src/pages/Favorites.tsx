import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import FavoriteRow from "../components/FavoriteRow";
import { getFavorites } from "../services/api";
import { hapticSelection } from "../utils/tg";

function parseFavorites(res: any): any[] {
  const data = (res as any)?.data ?? res;
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data?.favorites)) return data.favorites;
  if (Array.isArray(data?.products)) return data.products;
  return [];
}

export default function Favorites() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      const res: any = await getFavorites();
      const list = parseFavorites(res);
      setItems(list);
    } catch (e: any) {
      setItems([]);
      setErr(e?.response?.data?.detail || e?.message || "Не удалось загрузить избранное");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onRemoved = (productId: number) => {
    setItems((prev) => prev.filter((p) => Number(p?.id) !== Number(productId)));
  };

  return (
    <div className="container" style={{ paddingTop: 12, paddingBottom: 90 }}>
      <div className="page-head">
        <div className="page-head__title">Избранное</div>
        <div className="page-head__actions">
          <button
            className="icon-btn"
            onClick={() => {
              try {
                hapticSelection();
              } catch {}
              load();
            }}
            disabled={loading}
            title="Обновить"
            aria-label="Обновить"
          >
            ↻
          </button>
          <Link to="/catalog" className="btn ghost" style={{ textDecoration: "none" }}>
            Каталог
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="skeleton-list" style={{ marginTop: 12 }}>
          {[0, 1, 2].map((i) => (
            <div key={i} className="skeleton-row" style={{ marginTop: i ? 10 : 0 }} />
          ))}
        </div>
      ) : null}

      {err ? (
        <div className="card error-card" style={{ padding: 12, marginTop: 12 }}>
          {err}
        </div>
      ) : null}

      {!loading && !err && items.length === 0 ? (
        <div className="card empty-state" style={{ padding: 14, marginTop: 12 }}>
          <div className="empty-emoji" aria-hidden>
            ✨
          </div>
          <div style={{ fontWeight: 900, fontSize: 18 }}>Пока пусто</div>
          <div className="small-muted" style={{ marginTop: 8 }}>
            Добавляй товары в избранное — они появятся здесь.
          </div>
          <div style={{ marginTop: 12 }}>
            <Link to="/catalog" className="btn" style={{ textDecoration: "none" }}>
              Перейти в каталог
            </Link>
          </div>
        </div>
      ) : null}

      {!loading && !err && items.length > 0 ? (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((p, idx) => (
            <FavoriteRow key={String(p?.id ?? idx)} product={p} index={idx} onRemoved={onRemoved} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
