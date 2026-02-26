import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useParams, useNavigate, useSearchParams } from "react-router-dom";
import api from "../services/api";
import ProductCard from "../components/ProductCard";
import StickySearch from "../components/StickySearch";
import Skeleton from "../components/Skeleton";

type SortMode = "popular" | "price_asc" | "price_desc" | "title_asc";
type ProductAny = any;
type Option = { value: string; label: string };

function pickPrice(p: ProductAny): number {
  const v = Number(p?.price ?? p?.base_price ?? p?.min_price ?? 0);
  return Number.isFinite(v) ? v : 0;
}

function CustomSelect({ label, value, options, onChange }: { label: string; value: string; options: Option[]; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const onPointerDown = (e: MouseEvent) => {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, []);
  const selected = options.find((o) => o.value === value) || options[0];
  return (
    <div className="custom-select" ref={rootRef}>
      <button type="button" className="custom-select-trigger" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="small-muted">{label}</span><span>{selected?.label || "—"}</span>
      </button>
      {open ? <div className="custom-select-menu" role="listbox" aria-label={label}>{options.map((opt) => (
        <button key={opt.value} type="button" className="custom-select-option" data-active={opt.value === value ? "true" : "false"} onClick={() => { onChange(opt.value); setOpen(false); }}>{opt.label}</button>
      ))}</div> : null}
    </div>
  );
}

export default function CategoryView() {
  const { id } = useParams();
  const nav = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [category, setCategory] = useState<any>(null);
  const [products, setProducts] = useState<ProductAny[]>([]);
  const [loadingProducts, setLoadingProducts] = useState<boolean>(false);
  const [query, setQuery] = useState(() => searchParams.get("q") || "");
  const [debouncedQuery, setDebouncedQuery] = useState(() => searchParams.get("q") || "");
  const [page, setPage] = useState<number>(() => Math.max(1, Number(searchParams.get("page") || 1) || 1));
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [sortMode, setSortMode] = useState<SortMode>("popular");
  const perPage = 25;
  const pageCache = useRef(new Map<string, { items: ProductAny[]; total: number; pages: number }>());

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQuery(query), 250);
    return () => window.clearTimeout(t);
  }, [query]);

  useEffect(() => { setPage(1); }, [debouncedQuery, id]);

  useEffect(() => {
    const params = new URLSearchParams(searchParams);
    query.trim() ? params.set("q", query.trim()) : params.delete("q");
    page > 1 ? params.set("page", String(page)) : params.delete("page");
    if (params.toString() !== searchParams.toString()) setSearchParams(params, { replace: true });
  }, [query, page]);

  useEffect(() => {
    const key = `scroll:${location.pathname}?${location.search}`;
    const onScroll = () => sessionStorage.setItem(key, String(window.scrollY || 0));
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [location.pathname, location.search]);

  useEffect(() => {
    (async () => {
      setLoadingProducts(true);
      const cat = await api.getCategories();
      const catRaw = (cat as any)?.data ?? cat;
      const catList = Array.isArray(catRaw) ? catRaw : (Array.isArray((catRaw as any)?.items) ? (catRaw as any).items : []);
      const parsedId = Number(id);
      const catData = Number.isFinite(parsedId) && parsedId > 0 ? catList.find((c: any) => Number(c?.id) === parsedId) : catList.find((c: any) => String(c?.slug || "") === String(id || ""));
      if (catData) setCategory(catData);
      const categoryId = Number.isFinite(parsedId) && parsedId > 0 ? parsedId : Number((catData as any)?.id);
      const cacheKey = `${categoryId}|${debouncedQuery}|${page}|${perPage}`;
      const cached = pageCache.current.get(cacheKey);
      if (cached) {
        setProducts(cached.items); setTotal(cached.total); setPages(cached.pages); setLoadingProducts(false); return;
      }
      const res = await api.getProducts({ category_id: categoryId, q: debouncedQuery || undefined, page, limit: perPage });
      const data = (res as any)?.data ?? res;
      const items = Array.isArray(data?.items) ? data.items : [];
      const totalN = Number(data?.total || 0);
      const pagesN = Number(data?.pages || Math.ceil(totalN / perPage) || 0);
      setProducts(items); setTotal(totalN); setPages(pagesN);
      pageCache.current.set(cacheKey, { items, total: totalN, pages: pagesN });

      // prefetch next page for smooth UX
      if (page < pagesN) {
        const nextKey = `${categoryId}|${debouncedQuery}|${page + 1}|${perPage}`;
        if (!pageCache.current.has(nextKey)) {
          api.getProducts({ category_id: categoryId, q: debouncedQuery || undefined, page: page + 1, limit: perPage }).then((r: any) => {
            const d = r?.data ?? r;
            pageCache.current.set(nextKey, { items: Array.isArray(d?.items) ? d.items : [], total: Number(d?.total || totalN), pages: Number(d?.pages || pagesN) });
          }).catch(() => {});
        }
      }
      setLoadingProducts(false);
    })().catch(() => { setProducts([]); setTotal(0); setPages(0); setLoadingProducts(false); });
  }, [id, debouncedQuery, page]);

  const sortedProducts = useMemo(() => {
    const out = [...products];
    out.sort((a, b) => {
      if (sortMode === "price_asc") return pickPrice(a) - pickPrice(b);
      if (sortMode === "price_desc") return pickPrice(b) - pickPrice(a);
      if (sortMode === "title_asc") return String(a?.title || a?.name || "").localeCompare(String(b?.title || b?.name || ""), "ru");
      return 0;
    });
    return out;
  }, [products, sortMode]);

  const visiblePages = useMemo(() => {
    if (pages <= 1) return [1];
    const start = Math.max(1, page - 2);
    const end = Math.min(pages, page + 2);
    const arr: number[] = [];
    for (let p = start; p <= end; p += 1) arr.push(p);
    return arr;
  }, [page, pages]);

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button className="btn ghost" onClick={() => nav(-1)} aria-label="Назад">← Назад</button>
        <h1 className="h1" style={{ marginBottom: 0 }}>{category ? category.name : "Категория"}</h1>
      </div>

      <div className="catalog-search-top"><StickySearch value={query} onChange={setQuery} placeholder="Поиск по товарам…" hint={`Товаров: ${total}`} fixedTop /></div>
      <div style={{ marginBottom: 12 }}>
        <CustomSelect label="Сортировка" value={sortMode} onChange={(v) => setSortMode(v as SortMode)} options={[
          { value: "popular", label: "По умолчанию" }, { value: "price_asc", label: "Цена: по возрастанию" }, { value: "price_desc", label: "Цена: по убыванию" }, { value: "title_asc", label: "Название: А-Я" },
        ]} />
      </div>

      {loadingProducts ? (
        <div className="grid-products">{Array.from({ length: 8 }).map((_, idx) => <div key={idx} className="card" style={{ padding: 12 }}><Skeleton height={220} style={{ borderRadius: 14, marginBottom: 10 }} /><Skeleton height={16} width="70%" style={{ marginBottom: 8 }} /><Skeleton height={14} width="45%" /></div>)}</div>
      ) : (
        <div className="grid-products catalog-grid-animated">{sortedProducts.map((p) => <ProductCard key={(p as any).id} product={p} />)}</div>
      )}

      {pages > 1 ? (
        <div style={{ marginTop: 14, display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "center", alignItems: "center" }}>
          <button className="btn ghost" type="button" onClick={() => { setPage((v) => Math.max(1, v - 1)); window.scrollTo({ top: 0, behavior: "smooth" }); }} disabled={page <= 1}>← Назад</button>
          {visiblePages[0] > 1 ? <button className="btn ghost" onMouseEnter={() => {}} onClick={() => { setPage(1); window.scrollTo({ top: 0, behavior: "smooth" }); }}>1</button> : null}
          {visiblePages[0] > 2 ? <span className="small-muted">…</span> : null}
          {visiblePages.map((p) => <button key={p} className="btn ghost" style={{ borderColor: p === page ? "var(--ring)" : undefined }} onMouseEnter={() => {
            const parsedId = Number(id); const categoryId = Number.isFinite(parsedId) && parsedId > 0 ? parsedId : Number(category?.id || 0);
            const nextKey = `${categoryId}|${debouncedQuery}|${p}|${perPage}`;
            if (!pageCache.current.has(nextKey)) api.getProducts({ category_id: categoryId, q: debouncedQuery || undefined, page: p, limit: perPage }).then((r: any) => { const d = r?.data ?? r; pageCache.current.set(nextKey, { items: Array.isArray(d?.items) ? d.items : [], total: Number(d?.total || 0), pages: Number(d?.pages || 0) }); }).catch(() => {});
          }} onClick={() => { setPage(p); window.scrollTo({ top: 0, behavior: "smooth" }); }}>{p}</button>)}
          {visiblePages[visiblePages.length - 1] < pages - 1 ? <span className="small-muted">…</span> : null}
          {visiblePages[visiblePages.length - 1] < pages ? <button className="btn ghost" onClick={() => { setPage(pages); window.scrollTo({ top: 0, behavior: "smooth" }); }}>{pages}</button> : null}
          <button className="btn ghost" type="button" onClick={() => { setPage((v) => Math.min(pages, v + 1)); window.scrollTo({ top: 0, behavior: "smooth" }); }} disabled={page >= pages}>Далее →</button>
        </div>
      ) : null}
    </div>
  );
}
