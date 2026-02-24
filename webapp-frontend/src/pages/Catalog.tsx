import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
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
  const [categories, setCategories] = useState<Category[]>([]);
  const [globalProducts, setGlobalProducts] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [searchLoading, setSearchLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [globalMode, setGlobalMode] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res: any = await api.getCategories();
        let list: Category[] = [];

        if (Array.isArray(res)) list = res;
        else if (Array.isArray(res?.data)) list = res.data;
        else if (Array.isArray(res?.items)) list = res.items;
        else list = [];

        setCategories(list);
      } catch {
        setCategories([]);
        setError("Не удалось загрузить каталог");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setGlobalProducts([]);
      setSearchLoading(false);
      return;
    }
    const t = window.setTimeout(async () => {
      setSearchLoading(true);
      try {
        const res: any = await api.getProducts({ q, page: 1, per_page: 30 });
        const data = (res as any)?.data ?? res;
        const items = Array.isArray(data) ? data : data?.items || [];
        setGlobalProducts(Array.isArray(items) ? items : []);
      } catch {
        setGlobalProducts([]);
      } finally {
        setSearchLoading(false);
      }
    }, 260);
    return () => window.clearTimeout(t);
  }, [query]);

  const filteredCategories = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return categories;
    return categories.filter((c) => String(c.name || "").toLowerCase().includes(q));
  }, [categories, query]);

  const categoryById = useMemo(() => {
    const map = new Map<number, string>();
    categories.forEach((c) => map.set(Number(c.id), c.name));
    return map;
  }, [categories]);

  const hasQuery = Boolean(query.trim());

  if (loading) {
    return (
      <div className="container" style={{ paddingTop: 12 }}>
        <div className="card">
          <div className="panel-title">Каталог</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12, marginTop: 12 }}>
            {Array.from({ length: 8 }).map((_, idx) => (
              <div key={idx} className="card" style={{ padding: 12 }}>
                <Skeleton height={100} style={{ borderRadius: 8, marginBottom: 8 }} />
                <Skeleton height={14} width="70%" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) return <div className="container card">{error}</div>;

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div className="card">
        <div className="panel-title">Каталог</div>
        <StickySearch
          value={query}
          onChange={setQuery}
          placeholder="Поиск по товарам и категориям…"
          hint={
            hasQuery
              ? `Товары: ${globalProducts.length} • Категории: ${filteredCategories.length}`
              : categories.length
              ? `Категорий: ${categories.length}`
              : ""
          }
        />
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button className={`chip ${!globalMode ? "chip--active" : ""}`} type="button" onClick={() => setGlobalMode(false)}>Категории</button>
          <button className={`chip ${globalMode ? "chip--active" : ""}`} type="button" onClick={() => setGlobalMode(true)}>Глобально по товарам</button>
        </div>

        {hasQuery ? (
          <div style={{ marginTop: 10, display: "grid", gap: 12 }}>
            <div>
              <div className="small-muted" style={{ marginBottom: 8, fontWeight: 700 }}>Товары</div>
              {searchLoading ? <Skeleton height={54} /> : null}
              {!searchLoading && globalProducts.length === 0 ? (
                <div className="card" style={{ padding: 14 }}>
                  <div style={{ fontWeight: 800 }}>Товары не найдены</div>
                  <div className="muted">Попробуй другое название или артикул.</div>
                </div>
              ) : null}
              <div style={{ display: "grid", gap: 10 }}>
                {globalProducts.map((p: any) => (
                  <Link key={p.id} to={`/product/${p.id}`} className="card" style={{ textDecoration: "none", color: "inherit", padding: 12 }}>
                    <div style={{ fontWeight: 800 }}>{p.title || p.name}</div>
                    <div className="small-muted">{categoryById.get(Number(p.category_id)) || `Категория #${p.category_id || "—"}`}</div>
                  </Link>
                ))}
              </div>
            </div>

            <div>
              <div className="small-muted" style={{ marginBottom: 8, fontWeight: 700 }}>Категории</div>
              {filteredCategories.length === 0 ? (
                <div className="card" style={{ padding: 14 }}>
                  <div style={{ fontWeight: 800 }}>Категории не найдены</div>
                </div>
              ) : (
                <div className="categories-grid">
                  {filteredCategories.map((c) => (
                    <Link key={c.id} to={`/catalog/${c.slug || c.id}`} className="category-full-tile" style={{ textDecoration: "none", color: "inherit" }}>
                      <div className="category-info">
                        <div className="category-title">{c.name}</div>
                        <div className="category-sub">Перейти в категорию</div>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : categories.length === 0 ? (
          <div className="small-muted" style={{ marginTop: 12 }}>Категорий пока нет</div>
        ) : (
          <div className="categories-grid" style={{ marginTop: 8 }}>
            {categories.map((c) => (
              <Link key={c.id} to={`/catalog/${c.slug || c.id}`} className="category-full-tile" style={{ textDecoration: "none", color: "inherit" }}>
                <div className="category-info">
                  <div className="category-title">{c.name}</div>
                  <div className="category-sub">Перейти в категорию</div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
