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
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") || "");
  const [debouncedQuery, setDebouncedQuery] = useState(searchParams.get("q") || "");
  const [categories, setCategories] = useState<Category[]>([]);
  const [products, setProducts] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState<number>(() => {
    const p = Number(searchParams.get("page") || 1);
    return Number.isFinite(p) && p > 0 ? Math.floor(p) : 1;
  });
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(t);
  }, [query]);

  useEffect(() => {
    const params = new URLSearchParams(searchParams);
    if (query.trim()) params.set("q", query.trim());
    else params.delete("q");
    if (page > 1) params.set("page", String(page));
    else params.delete("page");
    if (params.toString() !== searchParams.toString()) setSearchParams(params, { replace: true });
  }, [query, page, searchParams, setSearchParams]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [catsRes, prodRes] = await Promise.all([
          api.getCategories(debouncedQuery ? { q: debouncedQuery } : {}),
          api.getProducts({ q: debouncedQuery || undefined, page, limit: 25 }),
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

        const hasServerPaginationMeta = Boolean(
          prodsRaw && typeof prodsRaw === "object" && (
            typeof prodsRaw?.total === "number"
            || typeof prodsRaw?.pages === "number"
            || typeof prodsRaw?.page === "number"
          )
        );

        setCategories(catItems);
        const totalCount = Number(prodsRaw?.total || prodItems.length || 0);
        const pageCount = Math.max(1, Number(prodsRaw?.pages || Math.ceil(Math.max(1, totalCount) / 25)));
        if (hasServerPaginationMeta) {
          setProducts(prodItems);
        } else {
          const start = (Math.max(1, page) - 1) * 25;
          setProducts(prodItems.slice(start, start + 25));
        }
        setTotal(totalCount);
        setPages(pageCount);
      } catch {
        setCategories([]);
        setProducts([]);
        setTotal(0);
        setPages(1);
        setError("Не удалось загрузить каталог");
      } finally {
        setLoading(false);
      }
    })();
  }, [debouncedQuery, page]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [page]);

  useEffect(() => {
    if (page > pages) setPage(pages);
  }, [page, pages]);

  const topCategories = useMemo(() => categories.slice(0, 10), [categories]);

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div className="card">
        <div className="panel-title">Каталог</div>
        <StickySearch
          value={query}
          onChange={setQuery}
          placeholder="Поиск по категориям и товарам…"
          hint={query ? `Категорий: ${categories.length}, товаров: ${total}` : ""}
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

        {pages > 1 ? (
          <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center", alignItems: "center" }}>
            <button className="btn ghost" type="button" onClick={() => setPage((v) => Math.max(1, v - 1))} disabled={page <= 1}>← Назад</button>
            <div className="small-muted">Страница {page} / {pages}</div>
            <button className="btn ghost" type="button" onClick={() => setPage((v) => Math.min(pages, v + 1))} disabled={page >= pages}>Далее →</button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
