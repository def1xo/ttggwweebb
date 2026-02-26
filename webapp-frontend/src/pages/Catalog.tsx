import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import api from "../services/api";
import Skeleton from "../components/Skeleton";
import StickySearch from "../components/StickySearch";
import ProductCard from "../components/ProductCard";

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
  const [products, setProducts] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(t);
  }, [query]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [catsRes, prodRes] = await Promise.all([
          api.getCategories(debouncedQuery ? { q: debouncedQuery } : {}),
          api.getProducts({ q: debouncedQuery || undefined, page: 1, limit: 24 }),
        ]);

        const catsRaw: any = (catsRes as any)?.data ?? catsRes;
        const prodsRaw: any = (prodRes as any)?.data ?? prodRes;

        const catItems = Array.isArray(catsRaw)
          ? catsRaw
          : Array.isArray(catsRaw?.items)
          ? catsRaw.items
          : [];

        const prodItems = Array.isArray(prodsRaw)
          ? prodsRaw
          : Array.isArray(prodsRaw?.items)
          ? prodsRaw.items
          : [];

        setCategories(catItems);
        setProducts(prodItems);
      } catch {
        setCategories([]);
        setProducts([]);
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
          placeholder="Поиск по категориям и товарам…"
          hint={query ? `Категорий: ${categories.length}, товаров: ${products.length}` : ""}
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

        <div style={{ marginTop: 16, marginBottom: 8, fontWeight: 700 }}>Товары</div>
        {loading ? (
          <div className="grid-products">
            {Array.from({ length: 6 }).map((_, idx) => (
              <div key={idx} className="card" style={{ padding: 10 }}>
                <Skeleton height={180} style={{ borderRadius: 10, marginBottom: 8 }} />
                <Skeleton height={14} width="80%" />
              </div>
            ))}
          </div>
        ) : (
          <div className="grid-products fade-in-list">
            {products.map((p) => (
              <ProductCard key={p.id} product={p} />
            ))}
          </div>
        )}

        {!loading && !error && topCategories.length === 0 && products.length === 0 ? (
          <div className="card" style={{ marginTop: 12, padding: 16 }}>
            <div style={{ fontWeight: 800, marginBottom: 6 }}>Ничего не найдено</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
