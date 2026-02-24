import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import apiDefault from "../services/api";
import ProductModal from "./ProductModal";
import ColorSwatch from "./ColorSwatch";
import StickySearch from "./StickySearch";

type Product = {
  id?: number;
  title: string;
  price?: number;
  category_id?: number | null;
  description?: string | null;
  default_image?: string | null;
  sizes?: string[];
  colors?: string[];
  import_source_url?: string | null;
  import_source_kind?: string | null;
  import_supplier_name?: string | null;
  image_count?: number;
};

export default function AdminProductManager() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<Product | null>(null);
  const [query, setQuery] = useState(() => searchParams.get("q") || "");
  const [debouncedQuery, setDebouncedQuery] = useState(() => searchParams.get("q") || "");
  const [page, setPage] = useState<number>(() => {
    const p = Number(searchParams.get("page") || 1);
    return Number.isFinite(p) && p > 0 ? Math.floor(p) : 1;
  });
  const cacheKey = useMemo(() => {
    const key = `admin:products:${JSON.stringify({ q: (debouncedQuery || "").trim(), page })}`;
    return key || "admin:products:default";
  }, [debouncedQuery, page]);

  useEffect(() => {
    load(debouncedQuery);
  }, [debouncedQuery, page]);

  useEffect(() => {
    const timer = window.setInterval(() => load(debouncedQuery), 30000);
    return () => window.clearInterval(timer);
  }, [debouncedQuery, page]);

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
    const key = `scroll:${cacheKey || "admin:products:default"}`;
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
  }, [cacheKey]);

  async function load(q = "") {
    setLoading(true);
    setErr(null);
    try {
      if (typeof apiDefault.getAdminProducts === "function") {
        const res = await apiDefault.getAdminProducts({ q: q.trim() || undefined, page, per_page: 200 });
        const arr = res?.products ?? res ?? [];
        setItems(arr);
      } else {
        const params = new URLSearchParams();
        if (q.trim()) params.set("q", q.trim());
        params.set("page", String(page));
        params.set("per_page", "200");
        const r = await fetch(`/api/admin/products${params.toString() ? `?${params.toString()}` : ""}`, { credentials: "include" });
        if (r.ok) {
          const data = await r.json();
          setItems(Array.isArray(data) ? data : data?.products ?? []);
        } else setItems([]);
      }
    } catch (e: any) {
      setErr(e?.message || "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }

  async function onSaved(resData: any) {
    // if axios response object — use data
    const payload = resData?.data ?? resData;
    setEditing(null);
    await load(debouncedQuery);
  }

  async function remove(id?: number) {
    if (!id) return;
    if (!confirm("Удалить товар?")) return;
    try {
      if (typeof apiDefault.deleteProduct === "function") {
        await apiDefault.deleteProduct(id);
      } else {
        await fetch(`/api/admin/products/${id}`, { method: "DELETE", credentials: "include" });
      }
      await load(debouncedQuery);
    } catch (e: any) {
      setErr(e?.message || "Ошибка удаления");
    }
  }

  const filteredItems = useMemo(() => {
    const q = debouncedQuery.trim().toLowerCase();
    if (!q) return items;
    return items.filter((p) => {
      const title = String((p as any).title || (p as any).name || "").toLowerCase();
      const sku = String((p as any).sku || (p as any).article || (p as any).vendor_code || "").toLowerCase();
      const pid = String((p as any).id || "");
      return title.includes(q) || sku.includes(q) || pid.includes(q);
    });
  }, [items, debouncedQuery]);

  const perPage = 25;
  const totalPages = Math.max(1, Math.ceil(filteredItems.length / perPage));
  const safePage = Math.min(Math.max(1, page), totalPages);
  const pagedItems = useMemo(() => {
    const start = (safePage - 1) * perPage;
    return filteredItems.slice(start, start + perPage);
  }, [filteredItems, safePage]);

  useEffect(() => {
    if (safePage !== page) setPage(safePage);
  }, [safePage, page]);

  return (
    <div>
      <div className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="panel-title">Товары</div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={() => setEditing({ title: "", price: 0 })}>Добавить товар</button>
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        <StickySearch
          value={query}
          onChange={setQuery}
          placeholder="Поиск по товарам (название / SKU / ID)…"
          hint={debouncedQuery ? `Найдено: ${filteredItems.length} / ${items.length}` : items.length ? `Товаров: ${items.length}` : ""}
        />
      </div>

      <div style={{ marginTop: 12 }}>
        {err && <div style={{ color: "red" }}>{err}</div>}
        {loading && <div className="small-muted">Загрузка…</div>}
        {!loading && items.length === 0 && <div className="small-muted">Товары не найдены</div>}
        {!loading && items.length > 0 && filteredItems.length === 0 && <div className="small-muted">Ничего не найдено</div>}
        {!loading && pagedItems.length > 0 && (
          <div style={{ display: "grid", gap: 8 }}>
            {pagedItems.map((p) => (
              <div key={p.id} className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={{ minWidth: 0 }}>
                  <div className="font-semibold" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    {p.title}
                    {Array.isArray(p.colors) && p.colors.length > 0 && (
                      <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        {p.colors.slice(0, 3).map((c, idx) => (
                          <ColorSwatch key={`${c}-${idx}`} name={c} />
                        ))}
                      </span>
                    )}
                  </div>

                  <div className="small-muted">
                    Цена: {(p as any).price ?? (p as any).base_price ?? "—"} ₽ • Закуп: {(p as any).cost_price ?? "—"} ₽ • Остаток: {(p as any).stock_quantity ?? (Array.isArray((p as any).variants) && (p as any).variants.length ? (p as any).variants[0]?.stock_quantity : "—")} • Категория: {p.category_id ?? "—"} • Фото: {(p as any).image_count ?? 0}
                    {Array.isArray(p.sizes) && p.sizes.length > 0 ? (
                      <>
                        {" "}
                        • Размеры:{" "}
                        {p.sizes.length > 4 ? `${p.sizes[0]}–${p.sizes[p.sizes.length - 1]}` : p.sizes.join(", ")}
                      </>
                    ) : (
                      <> • Размеры: —</>
                    )}
                  </div>
                  <div className="small-muted" style={{ marginTop: 4, wordBreak: "break-all" }}>
                    Импорт: {(p as any).import_supplier_name || "—"} • {(p as any).import_source_kind || "—"} • {(p as any).import_source_url || "—"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn ghost" onClick={() => { sessionStorage.setItem(`scroll:${cacheKey || "admin:products:default"}`, String(window.scrollY || 0)); setEditing(p); }}>Ред.</button>
                  <button className="btn ghost" onClick={() => remove(p.id)}>Удалить</button>
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && filteredItems.length > perPage ? (
          <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center", alignItems: "center" }}>
            <button className="btn ghost" type="button" onClick={() => setPage((v) => Math.max(1, v - 1))} disabled={safePage <= 1}>← Назад</button>
            <div className="small-muted">Страница {safePage} / {totalPages}</div>
            <button className="btn ghost" type="button" onClick={() => setPage((v) => Math.min(totalPages, v + 1))} disabled={safePage >= totalPages}>Далее →</button>
          </div>
        ) : null}
      </div>

      {editing && <ProductModal open={true} product={editing} onClose={() => setEditing(null)} onSaved={onSaved} />}
    </div>
  );
}
