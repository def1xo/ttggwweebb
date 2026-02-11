import React, { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../services/api";
import ProductCard from "../components/ProductCard";
import StickySearch from "../components/StickySearch";

type SortMode = "popular" | "price_asc" | "price_desc" | "title_asc";

type ProductAny = any;

function pickPrice(p: ProductAny): number {
  const v = Number(p?.price ?? p?.base_price ?? p?.min_price ?? 0);
  return Number.isFinite(v) ? v : 0;
}

function extractValues(products: ProductAny[], key: "size" | "color"): string[] {
  const set = new Set<string>();
  for (const p of products) {
    const variants = Array.isArray(p?.variants) ? p.variants : [];
    for (const v of variants) {
      const raw = key === "size" ? (v?.size?.name ?? v?.size) : (v?.color?.name ?? v?.color);
      const value = String(raw ?? "").trim();
      if (value) set.add(value);
    }
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
}

export default function CategoryView() {
  const { id } = useParams();
  const nav = useNavigate();
  const [category, setCategory] = useState<any>(null);
  const [products, setProducts] = useState<ProductAny[]>([]);
  const [query, setQuery] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("popular");
  const [sizeFilter, setSizeFilter] = useState("all");
  const [colorFilter, setColorFilter] = useState("all");
  const [priceFilter, setPriceFilter] = useState<"all" | "up_to_5000" | "5000_10000" | "from_10000">("all");

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

  const sizeOptions = useMemo(() => extractValues(products, "size"), [products]);
  const colorOptions = useMemo(() => extractValues(products, "color"), [products]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();

    let out = products.filter((p) => {
      const title = String((p as any).title || (p as any).name || "").toLowerCase();
      const titleOk = !q || title.includes(q);

      const variants = Array.isArray(p?.variants) ? p.variants : [];
      const sizeOk = sizeFilter === "all" || variants.some((v: any) => String(v?.size?.name ?? v?.size ?? "").trim() === sizeFilter);
      const colorOk = colorFilter === "all" || variants.some((v: any) => String(v?.color?.name ?? v?.color ?? "").trim() === colorFilter);

      const price = pickPrice(p);
      const priceOk =
        priceFilter === "all"
        || (priceFilter === "up_to_5000" && price <= 5000)
        || (priceFilter === "5000_10000" && price > 5000 && price <= 10000)
        || (priceFilter === "from_10000" && price > 10000);

      return titleOk && sizeOk && colorOk && priceOk;
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
  }, [products, query, sizeFilter, colorFilter, priceFilter, sortMode]);

  const hint = query
    ? `Найдено: ${filtered.length} / ${products.length}`
    : products.length
    ? `Товаров: ${products.length}`
    : "";

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

      <StickySearch value={query} onChange={setQuery} placeholder="Поиск по товарам…" hint={hint} />

      <div className="catalog-tools" style={{ marginBottom: 12 }}>
        <select className="input" value={sortMode} onChange={(e) => setSortMode(e.target.value as SortMode)}>
          <option value="popular">Сортировка: по умолчанию</option>
          <option value="price_asc">Цена: по возрастанию</option>
          <option value="price_desc">Цена: по убыванию</option>
          <option value="title_asc">Название: А-Я</option>
        </select>

        <select className="input" value={sizeFilter} onChange={(e) => setSizeFilter(e.target.value)}>
          <option value="all">Размер: все</option>
          {sizeOptions.map((size) => (
            <option key={size} value={size}>{size}</option>
          ))}
        </select>

        <select className="input" value={colorFilter} onChange={(e) => setColorFilter(e.target.value)}>
          <option value="all">Цвет: все</option>
          {colorOptions.map((color) => (
            <option key={color} value={color}>{color}</option>
          ))}
        </select>

        <select className="input" value={priceFilter} onChange={(e) => setPriceFilter(e.target.value as any)}>
          <option value="all">Цена: любая</option>
          <option value="up_to_5000">до 5 000 ₽</option>
          <option value="5000_10000">5 001 — 10 000 ₽</option>
          <option value="from_10000">от 10 001 ₽</option>
        </select>
      </div>

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
