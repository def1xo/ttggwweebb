import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import api from "../services/api";
import Skeleton from "../components/Skeleton";
import StickySearch from "../components/StickySearch";

type Category = {
  id: number;
  name: string;
  slug?: string;
  image_url?: string | null;
};

export default function Catalog() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res: any = await api.getCategories();
        let list: Category[] = [];

        if (Array.isArray(res)) list = res;
        else if (Array.isArray(res?.data)) list = res.data;
        else if (Array.isArray(res?.items)) list = res.items;
        else list = [];

        setCategories(list);
      } catch (e: any) {
        setCategories([]);
        setError("Не удалось загрузить каталог");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return categories;
    return categories.filter((c) => String(c.name || "").toLowerCase().includes(q));
  }, [categories, query]);

  if (loading) {
    return (
      <div className="container" style={{ paddingTop: 12 }}>
        <div className="card">
          <div className="panel-title">Каталог</div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
              gap: 12,
              marginTop: 12,
            }}
          >
            {Array.from({ length: 8 }).map((_, idx) => (
              <div key={idx} className="card" style={{ padding: 12 }}>
                <Skeleton height={100} style={{ borderRadius: 8, marginBottom: 8 }} />
                <Skeleton height={14} width="70%" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return <div className="container card">{error}</div>;
  }

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div className="card">
        <div className="panel-title">Каталог</div>
        <StickySearch
          value={query}
          onChange={setQuery}
          placeholder="Поиск по категориям…"
          hint={query ? `Найдено: ${filtered.length} / ${categories.length}` : categories.length ? `Категорий: ${categories.length}` : ""}
        />

        {categories.length === 0 ? (
          <div className="small-muted" style={{ marginTop: 12 }}>
            Категорий пока нет
          </div>
        ) : (
          <div className="categories-grid" style={{ marginTop: 8 }}>
            {filtered.map((c) => (
              <Link
                key={c.id}
                to={`/catalog/${c.slug || c.id}`}
                className="category-full-tile"
                style={{ textDecoration: "none", color: "inherit" }}
              >
                <div className="category-info">
                  <div className="category-title">{c.name}</div>
                  <div className="category-sub">Перейти в категорию</div>
                </div>
              </Link>
            ))}
          </div>
        )}

        {categories.length > 0 && filtered.length === 0 ? (
          <div className="card" style={{ marginTop: 12, padding: 16 }}>
            <div style={{ fontWeight: 800, marginBottom: 6 }}>Ничего не найдено</div>
            <div className="muted">Попробуй другой запрос или очисти поиск.</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
