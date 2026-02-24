import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useParams, useNavigate, useSearchParams } from "react-router-dom";
import api from "../services/api";
import ProductCard from "../components/ProductCard";
import StickySearch from "../components/StickySearch";

type SortMode = "popular" | "price_asc" | "price_desc" | "title_asc";

type ProductAny = any;

type Option = { value: string; label: string };

function pickPrice(p: ProductAny): number {
  const v = Number(p?.price ?? p?.base_price ?? p?.min_price ?? 0);
  return Number.isFinite(v) ? v : 0;
}

function extractValues(products: ProductAny[]): string[] {
  const set = new Set<string>();
  for (const p of products) {
    const variants = Array.isArray(p?.variants) ? p.variants : [];
    for (const v of variants) {
      const raw = v?.size?.name ?? v?.size;
      const value = String(raw ?? "").trim();
      if (value) set.add(value);
    }
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
}

function CustomSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (v: string) => void;
}) {
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
      <button
        type="button"
        className="custom-select-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="small-muted">{label}</span>
        <span>{selected?.label || "—"}</span>
      </button>
      {open ? (
        <div className="custom-select-menu" role="listbox" aria-label={label}>
          {options.map((opt) => {
            const active = opt.value === value;
            return (
              <button
                key={opt.value}
                type="button"
                className="custom-select-option"
                data-active={active ? "true" : "false"}
                onClick={() => {
                  onChange(opt.value);
                  setOpen(false);
                }}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      ) : null}
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
  const [query, setQuery] = useState(() => searchParams.get("q") || "");
  const [debouncedQuery, setDebouncedQuery] = useState(() => searchParams.get("q") || "");
  const [page, setPage] = useState<number>(() => {
    const p = Number(searchParams.get("page") || 1);
    return Number.isFinite(p) && p > 0 ? Math.floor(p) : 1;
  });
  const [sortMode, setSortMode] = useState<SortMode>("popular");
  const [sizeFilter, setSizeFilter] = useState("all");
  const [priceMin, setPriceMin] = useState<string>("");
  const [priceMax, setPriceMax] = useState<string>("");
  const [filtersOpen, setFiltersOpen] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const cat = await api.getCategories();
        const catRaw = (cat as any)?.data ?? cat;
        const catList = Array.isArray(catRaw) ? catRaw : (Array.isArray((catRaw as any)?.items) ? (catRaw as any).items : []);
        const parsedId = Number(id);
        const catData = Number.isFinite(parsedId) && parsedId > 0
          ? catList.find((c: any) => Number(c?.id) === parsedId)
          : catList.find((c: any) => String(c?.slug || "") === String(id || ""));
        if (catData) setCategory(catData);

        const categoryId = Number.isFinite(parsedId) && parsedId > 0
          ? parsedId
          : Number((catData as any)?.id);

        const categoryFilter = Number.isFinite(categoryId) && categoryId > 0
          ? { category_id: categoryId }
          : {};

        // Backend defaults to per_page=50. For categories with larger catalogs,
        // fetch all pages to avoid "new items push old out" effect.
        const perPage = 500;
        let page = 1;
        const merged: ProductAny[] = [];
        while (page <= 50) {
          const prods = await api.getProducts({ ...categoryFilter, page, per_page: perPage });
          const data = (prods as any)?.data ?? prods;
          const items = Array.isArray(data) ? data : data?.items || [];
          if (!Array.isArray(items) || items.length === 0) break;
          merged.push(...items);

          const total = Number((data as any)?.total || 0);
          if (total > 0 && merged.length >= total) break;
          if (items.length < perPage) break;
          page += 1;
        }
        setProducts(merged);
      } catch {
        // noop
      }
    })();
  }, [id]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebouncedQuery(query);
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
    const next = params.toString();
    const cur = searchParams.toString();
    if (next !== cur) setSearchParams(params, { replace: true });
  }, [query, page]);

  useEffect(() => {
    const key = `scroll:${location.pathname}?${location.search}`;
    const raw = sessionStorage.getItem(key);
    const y = Number(raw || 0);
    if (Number.isFinite(y) && y > 0) {
      window.setTimeout(() => window.scrollTo(0, y), 0);
    }
    const onScroll = () => {
      sessionStorage.setItem(key, String(window.scrollY || 0));
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      onScroll();
      window.removeEventListener("scroll", onScroll);
    };
  }, [location.pathname, location.search]);

  const sizeOptions = useMemo(() => extractValues(products), [products]);

  const filtered = useMemo(() => {
    const q = debouncedQuery.trim().toLowerCase();

    let out = products.filter((p) => {
      const title = String((p as any).title || (p as any).name || "").toLowerCase();
      const sku = String((p as any).sku || (p as any).article || (p as any).vendor_code || "").toLowerCase();
      const titleOk = !q || title.includes(q) || sku.includes(q);

      const variants = Array.isArray(p?.variants) ? p.variants : [];
      const sizeOk = sizeFilter === "all" || variants.some((v: any) => String(v?.size?.name ?? v?.size ?? "").trim() === sizeFilter);

      const price = pickPrice(p);
      const minVal = Number(priceMin);
      const maxVal = Number(priceMax);
      const minOk = !priceMin.trim() || (!Number.isNaN(minVal) && price >= minVal);
      const maxOk = !priceMax.trim() || (!Number.isNaN(maxVal) && price <= maxVal);

      return titleOk && sizeOk && minOk && maxOk;
    });

    out = out.slice().sort((a, b) => {
      if (sortMode === "price_asc") return pickPrice(a) - pickPrice(b);
      if (sortMode === "price_desc") return pickPrice(b) - pickPrice(a);
      if (sortMode === "title_asc") {
        const ta = String(a?.title || a?.name || "");
        const tb = String(b?.title || b?.name || "");
        return ta.localeCompare(tb, "ru");
      }
      return 0;
    });

    return out;
  }, [products, debouncedQuery, sizeFilter, priceMin, priceMax, sortMode]);

  const perPage = 24;
  const totalPages = Math.max(1, Math.ceil(filtered.length / perPage));
  const safePage = Math.min(Math.max(1, page), totalPages);
  const paged = useMemo(() => {
    const start = (safePage - 1) * perPage;
    return filtered.slice(start, start + perPage);
  }, [filtered, safePage]);

  useEffect(() => {
    if (safePage !== page) setPage(safePage);
  }, [safePage, page]);

  const hint = debouncedQuery
    ? `Найдено в категории: ${filtered.length} / ${products.length}`
    : products.length
    ? `Товаров: ${products.length}`
    : "";

  const hasCustomFilters = sortMode !== "popular" || sizeFilter !== "all" || !!priceMin.trim() || !!priceMax.trim();

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button className="btn ghost" onClick={() => nav(-1)} aria-label="Назад">
          ← Назад
        </button>
        <h1 className="h1" style={{ marginBottom: 0 }}>
          {category ? category.name : "Категория"}
        </h1>
      </div>

      <div className="catalog-search-top">
        <StickySearch value={query} onChange={setQuery} placeholder="Поиск по товарам…" hint={hint} fixedTop />
      </div>

      <div style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
        <button className="btn btn-secondary" type="button" onClick={() => setFiltersOpen((v) => !v)}>
          {filtersOpen ? "Скрыть фильтр" : "Фильтр"}
        </button>
        <div className="small-muted">{filtered.length} товаров</div>
      </div>

      {filtersOpen ? (
        <div className="catalog-filter-panel" style={{ marginBottom: 12 }}>
          <div className="catalog-filter-panel__title">Фильтры и сортировка</div>
          <div className="catalog-tools">
            <CustomSelect
              label="Сортировка"
              value={sortMode}
              onChange={(v) => setSortMode(v as SortMode)}
              options={[
                { value: "popular", label: "По умолчанию" },
                { value: "price_asc", label: "Цена: по возрастанию" },
                { value: "price_desc", label: "Цена: по убыванию" },
                { value: "title_asc", label: "Название: А-Я" },
              ]}
            />

            <CustomSelect
              label="Размер"
              value={sizeFilter}
              onChange={setSizeFilter}
              options={[{ value: "all", label: "Все" }, ...sizeOptions.map((size) => ({ value: size, label: size }))]}
            />

            <div className="card" style={{ padding: 10 }}>
              <div className="small-muted" style={{ marginBottom: 8 }}>Цена</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <input
                  className="input"
                  inputMode="numeric"
                  placeholder="От"
                  value={priceMin}
                  onChange={(e) => setPriceMin(e.target.value.replace(/[^0-9]/g, ""))}
                />
                <input
                  className="input"
                  inputMode="numeric"
                  placeholder="До"
                  value={priceMax}
                  onChange={(e) => setPriceMax(e.target.value.replace(/[^0-9]/g, ""))}
                />
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {hasCustomFilters ? (
        <div style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
          <div className="small-muted">Фильтры применены</div>
          <button
            className="btn ghost"
            onClick={() => {
              setSortMode("popular");
              setSizeFilter("all");
              setPriceMin("");
              setPriceMax("");
            }}
          >
            Сбросить всё
          </button>
        </div>
      ) : null}

      <div className="grid-products">
        {paged.map((p) => (
          <ProductCard key={(p as any).id} product={p} />
        ))}
      </div>

      {filtered.length > perPage ? (
        <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center", alignItems: "center" }}>
          <button className="btn ghost" type="button" onClick={() => setPage((v) => Math.max(1, v - 1))} disabled={safePage <= 1}>← Назад</button>
          <div className="small-muted">Страница {safePage} / {totalPages}</div>
          <button className="btn ghost" type="button" onClick={() => setPage((v) => Math.min(totalPages, v + 1))} disabled={safePage >= totalPages}>Далее →</button>
        </div>
      ) : null}

      {products.length > 0 && filtered.length === 0 ? (
        <div className="card" style={{ marginTop: 12, padding: 16 }}>
          <div style={{ fontWeight: 800, marginBottom: 6 }}>Ничего не найдено</div>
          <div className="muted">Попробуй снять часть фильтров или очисти поиск.</div>
          <div style={{ marginTop: 10 }}>
            <button
              className="btn ghost"
              type="button"
              onClick={() => {
                setQuery("");
                setDebouncedQuery("");
                setPage(1);
                setSortMode("popular");
                setSizeFilter("all");
                setPriceMin("");
                setPriceMax("");
              }}
            >
              Сбросить поиск
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
