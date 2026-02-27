import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") || "");
  const [debouncedQuery, setDebouncedQuery] = useState(searchParams.get("q") || "");
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(t);
  }, [query]);

  useEffect(() => {
    const params = new URLSearchParams(searchParams);
    if (query.trim()) params.set("q", query.trim());
    else params.delete("q");
    if (params.toString() !== searchParams.toString()) setSearchParams(params, { replace: true });
  }, [query, searchParams, setSearchParams]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const catsRes = await api.getCategories(debouncedQuery ? { q: debouncedQuery } : {});
        const catsRaw: any = (catsRes as any)?.data ?? catsRes;
        const catItems = Array.isArray(catsRaw)
          ? catsRaw
          : Array.isArray(catsRaw?.items)
          ? catsRaw.items
          : [];
        setCategories(catItems);
      } catch {
        setCategories([]);
        setError("Не удалось загрузить каталог");
      } finally {
        setLoading(false);
      }
    })();
  }, [debouncedQuery]);

  const topCategories = useMemo(() => categories.slice(0, 50), [categories]);

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div className="card">
        <div className="panel-title">Каталог</div>
        <StickySearch
          value={query}
          onChange={setQuery}
          placeholder="Поиск категорий (можно по названию товара)…"
          hint={query ? `Категорий: ${categories.length}` : ""}
        />

        {error ? <div className="small-muted" style={{ marginTop: 12 }}>{error}</div> : null}

        <div style={{ marginTop: 12, marginBottom: 8, fontWeight: 700 }}>Категории</div>
        {loading ? (
          <div className="categories-grid">
            {Array.from({ length: 8 }).map((_, idx) => (
              <div key={idx} className="card" style={{ padding: 12 }}>
                <Skeleton height={56} style={{ borderRadius: 8 }} />
              </div>
            ))}
          </div>
        ) : (
          <div className="categories-grid fade-in-list">
            {topCategories.map((c) => (
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

        {!loading && !error && topCategories.length === 0 ? (
          <div className="card" style={{ marginTop: 12, padding: 16 }}>
            <div style={{ fontWeight: 800, marginBottom: 6 }}>Ничего не найдено</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
