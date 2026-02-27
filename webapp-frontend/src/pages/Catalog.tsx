import { useEffect, useMemo, useRef, useState } from "react";
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
  const [searchParams] = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") || "");
  const [debouncedQuery, setDebouncedQuery] = useState(searchParams.get("q") || "");
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(t);
  }, [query]);

  useEffect(() => {
    const reqId = ++requestIdRef.current;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const catsRes = await api.getCategories(debouncedQuery ? { q: debouncedQuery } : {});
        if (reqId !== requestIdRef.current) return;
        const catsRaw: any = (catsRes as any)?.data ?? catsRes;
        const catItems = Array.isArray(catsRaw)
          ? catsRaw
          : Array.isArray(catsRaw?.items)
          ? catsRaw.items
          : [];
        setCategories(catItems);
      } catch {
        if (reqId !== requestIdRef.current) return;
        setCategories([]);
        setError("Не удалось загрузить каталог");
      } finally {
        if (reqId !== requestIdRef.current) return;
        setLoading(false);
        if (query && document.activeElement !== searchInputRef.current && searchInputRef.current) {
          searchInputRef.current.focus({ preventScroll: true });
        }
      }
    })();
  }, [debouncedQuery, query]);

  const topCategories = useMemo(() => categories.slice(0, 50), [categories]);

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div className="card">
        <div className="panel-title">Каталог</div>
        <StickySearch
          value={query}
          inputRef={searchInputRef}
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
