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
        setCategory((cat as any).data || cat);
        const prods = await api.get(`/api/products`, { params: { category_id: id } });
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
      <div className="app-header">
        <button onClick={() => nav(-1)} style={{ position: "absolute", left: 12 }}>
          ←
        </button>
        <h1 style={{ margin: "0 auto" }}>{category ? category.name : "Категория"}</h1>
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
