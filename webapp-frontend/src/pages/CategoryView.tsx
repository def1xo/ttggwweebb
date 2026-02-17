import React, { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
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
  const [category, setCategory] = useState<any>(null);
  const [products, setProducts] = useState<ProductAny[]>([]);
  const [query, setQuery] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("popular");
  const [sizeFilter, setSizeFilter] = useState("all");
  const [priceFilter, setPriceFilter] = useState<"all" | "up_to_5000" | "5000_10000" | "from_10000">("all");
  const [filtersOpen, setFiltersOpen] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const cat = await api.get(`/api/categories/${id}`);
        const catData = (cat as any).data || cat;
        setCategory(catData);

        const parsedId = Number(id);
        const categoryId = Number.isFinite(parsedId) && parsedId > 0
          ? parsedId
          : Number((catData as any)?.id);

        const params = Number.isFinite(categoryId) && categoryId > 0
          ? { category_id: categoryId }
          : undefined;

        const prods = await api.get(`/api/products`, { params });
        const data = (prods as any)?.data ?? prods;
        setProducts(Array.isArray(data) ? data : data?.items || []);
      } catch {
        // noop
      }
    })();
  }, [id]);

  const sizeOptions = useMemo(() => extractValues(products), [products]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();

    let out = products.filter((p) => {
      const title = String((p as any).title || (p as any).name || "").toLowerCase();
      const titleOk = !q || title.includes(q);

      const variants = Array.isArray(p?.variants) ? p.variants : [];
      const sizeOk = sizeFilter === "all" || variants.some((v: any) => String(v?.size?.name ?? v?.size ?? "").trim() === sizeFilter);

      const price = pickPrice(p);
      const priceOk =
        priceFilter === "all"
        || (priceFilter === "up_to_5000" && price <= 5000)
        || (priceFilter === "5000_10000" && price > 5000 && price <= 10000)
        || (priceFilter === "from_10000" && price > 10000);

      return titleOk && sizeOk && priceOk;
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
  }, [products, query, sizeFilter, priceFilter, sortMode]);

  const hint = query
    ? `Найдено: ${filtered.length} / ${products.length}`
    : products.length
    ? `Товаров: ${products.length}`
    : "";

  const hasCustomFilters = sortMode !== "popular" || sizeFilter !== "all" || priceFilter !== "all";

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

            <CustomSelect
              label="Цена"
              value={priceFilter}
              onChange={(v) => setPriceFilter(v as any)}
              options={[
                { value: "all", label: "Любая" },
                { value: "up_to_5000", label: "до 5 000 ₽" },
                { value: "5000_10000", label: "5 001 — 10 000 ₽" },
                { value: "from_10000", label: "от 10 001 ₽" },
              ]}
            />
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
              setPriceFilter("all");
            }}
          >
            Сбросить всё
          </button>
        </div>
      ) : null}

      <div className="grid-products">
        {filtered.map((p) => (
          <ProductCard key={(p as any).id} product={p} />
        ))}
      </div>

      {products.length > 0 && filtered.length === 0 ? (
        <div className="card" style={{ marginTop: 12, padding: 16 }}>
          <div style={{ fontWeight: 800, marginBottom: 6 }}>Ничего не найдено</div>
          <div className="muted">Попробуй снять часть фильтров или очисти поиск.</div>
        </div>
      ) : null}
    </div>
  );
}
