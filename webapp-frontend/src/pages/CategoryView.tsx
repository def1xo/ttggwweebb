import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import api from "../services/api";
import ProductCard from "../components/ProductCard";
import StickySearch from "../components/StickySearch";
import Skeleton from "../components/Skeleton";

const PAGE_SIZE = 25;

export default function CategoryView() {
  const { id } = useParams();
  const nav = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const searchParamsKey = searchParams.toString();
  const [category, setCategory] = useState<any>(null);
  const [products, setProducts] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState(searchParams.get("q") || "");
  const [debouncedQuery, setDebouncedQuery] = useState(searchParams.get("q") || "");
  const [page, setPage] = useState<number>(() => {
    const p = Number(searchParams.get("page") || 1);
    return Number.isFinite(p) && p > 0 ? Math.floor(p) : 1;
  });
  const debouncedInitializedRef = useRef(false);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
    }, 300);
    return () => window.clearTimeout(t);
  }, [query]);

  useEffect(() => {
    if (!debouncedInitializedRef.current) {
      debouncedInitializedRef.current = true;
      return;
    }
    setPage(1);
  }, [debouncedQuery]);

  useEffect(() => {
    const nextQ = searchParams.get("q") || "";
    const nextPageRaw = Number(searchParams.get("page") || 1);
    const nextPage = Number.isFinite(nextPageRaw) && nextPageRaw > 0 ? Math.floor(nextPageRaw) : 1;
    if (nextQ !== query) setQuery(nextQ);
    if (nextQ !== debouncedQuery) setDebouncedQuery(nextQ);
    if (nextPage !== page) setPage(nextPage);
  }, [searchParamsKey]);

  useEffect(() => {
    const params = new URLSearchParams(searchParams);
    if (debouncedQuery) params.set("q", debouncedQuery);
    else params.delete("q");
    if (page > 1) params.set("page", String(page));
    else params.delete("page");
    if (params.toString() !== searchParams.toString()) setSearchParams(params, { replace: true });
  }, [debouncedQuery, page, searchParamsKey, searchParams, setSearchParams]);

  useEffect(() => {
    (async () => {
      try {
        const cat = await api.getCategories();
        const catRaw = (cat as any)?.data ?? cat;
        const catList = Array.isArray(catRaw) ? catRaw : Array.isArray(catRaw?.items) ? catRaw.items : [];
        const parsedId = Number(id);
        const catData = Number.isFinite(parsedId) && parsedId > 0
          ? catList.find((c: any) => Number(c?.id) === parsedId)
          : catList.find((c: any) => String(c?.slug || "") === String(id || ""));
        setCategory(catData || null);
      } catch {
        setCategory(null);
      }
    })();
  }, [id]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const parsedId = Number(id);
        const categoryId = Number.isFinite(parsedId) && parsedId > 0 ? parsedId : Number(category?.id);
        const params: Record<string, any> = { page, limit: PAGE_SIZE };
        if (debouncedQuery) params.q = debouncedQuery;
        if (Number.isFinite(categoryId) && categoryId > 0) params.category_id = categoryId;

        const res = await api.getProducts(params);
        const data: any = (res as any)?.data ?? res;
        const items = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : [];
        setProducts(items);
        setTotal(Number(data?.total || items.length || 0));
        setPages(Math.max(1, Number(data?.pages || Math.ceil((Number(data?.total || 0) || 1) / PAGE_SIZE))));
      } catch {
        setProducts([]);
        setTotal(0);
        setPages(1);
      } finally {
        setLoading(false);
      }
    })();
  }, [id, category?.id, page, debouncedQuery]);

  const visiblePages = useMemo(() => {
    if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
    const start = Math.max(1, page - 2);
    const end = Math.min(pages, start + 4);
    const chunk = [] as number[];
    for (let p = start; p <= end; p += 1) chunk.push(p);
    if (!chunk.includes(1)) chunk.unshift(1);
    if (!chunk.includes(pages)) chunk.push(pages);
    return chunk;
  }, [page, pages]);

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button className="btn ghost" onClick={() => nav(-1)} aria-label="Назад">← Назад</button>
        <h1 className="h1" style={{ marginBottom: 0 }}>{category?.name || "Категория"}</h1>
      </div>

      <div className="catalog-search-top">
        <StickySearch value={query} onChange={setQuery} placeholder="Поиск по товарам…" hint={`Товаров: ${total}`} fixedTop />
      </div>

      {loading ? (
        <div className="grid-products">
          {Array.from({ length: 8 }).map((_, idx) => (
            <div key={idx} className="card" style={{ padding: 10 }}>
              <Skeleton height={180} style={{ borderRadius: 10, marginBottom: 8 }} />
              <Skeleton height={14} width="80%" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid-products fade-in-list">
          {products.map((p) => <ProductCard key={p.id} product={p} />)}
        </div>
      )}

      {!loading && products.length === 0 ? (
        <div className="card" style={{ marginTop: 12, padding: 16 }}>
          <div style={{ fontWeight: 800, marginBottom: 6 }}>Ничего не найдено</div>
        </div>
      ) : null}

      {pages > 1 ? (
        <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center", alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn ghost" type="button" onClick={() => setPage((v) => Math.max(1, v - 1))} disabled={loading || page <= 1}>← Назад</button>
          {visiblePages.map((p, idx) => (
            <button
              key={`${p}-${idx}`}
              className="btn ghost"
              type="button"
              onClick={() => !loading && setPage(p)}
              style={{ opacity: p === page ? 1 : 0.72, fontWeight: p === page ? 800 : 500 }}
            >
              {p}
            </button>
          ))}
          <button className="btn ghost" type="button" onClick={() => setPage((v) => Math.min(pages, v + 1))} disabled={loading || page >= pages}>Далее →</button>
        </div>
      ) : null}
    </div>
  );
}
