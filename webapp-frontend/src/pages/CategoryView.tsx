import React, { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../services/api";
import ProductCard from "../components/ProductCard";
import StickySearch from "../components/StickySearch";

export default function CategoryView() {
  const { id } = useParams();
  const nav = useNavigate();
  const [category, setCategory] = useState<any>(null);
  const [products, setProducts] = useState<any[]>([]);
  const [query, setQuery] = useState("");

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
      } catch (e) {
        // ignore
      }
    })();
  }, [id]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return products;
    return products.filter((p) => {
      const title = String((p as any).title || (p as any).name || "").toLowerCase();
      return title.includes(q);
    });
  }, [products, query]);

  const hint = query
    ? `Найдено: ${filtered.length} / ${products.length}`
    : products.length
    ? `Товаров: ${products.length}`
    : "";

  return (
    <div className="container">
      <div className="app-header" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button className="btn btn-secondary" onClick={() => nav(-1)} aria-label="Назад">
          ← Назад
        </button>
        <h1 style={{ margin: 0, flex: 1, textAlign: "center", paddingRight: 72 }}>
          {category ? category.name : "Категория"}
        </h1>
      </div>

      <div style={{ marginTop: 12 }}>
        <StickySearch value={query} onChange={setQuery} placeholder="Поиск по товарам…" hint={hint} />

        <div className="grid-products">
          {filtered.map((p) => (
            <ProductCard key={(p as any).id} product={p} />
          ))}
        </div>

        {products.length > 0 && filtered.length === 0 ? (
          <div className="card" style={{ marginTop: 12, padding: 16 }}>
            <div style={{ fontWeight: 800, marginBottom: 6 }}>Ничего не найдено</div>
            <div className="muted">Попробуй другой запрос или очисти поиск.</div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
