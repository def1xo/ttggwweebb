import React, { useEffect, useState } from "react";
import apiDefault from "../services/api";
import ProductModal from "./ProductModal";
import ColorSwatch from "./ColorSwatch";

type Product = {
  id?: number;
  title: string;
  price?: number;
  category_id?: number | null;
  description?: string | null;
  default_image?: string | null;
  sizes?: string[];
  colors?: string[];
};

export default function AdminProductManager() {
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<Product | null>(null);

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => load(), 30000);
    return () => window.clearInterval(timer);
  }, []);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      if (typeof apiDefault.getAdminProducts === "function") {
        const res = await apiDefault.getAdminProducts({ limit: 200, offset: 0 });
        const arr = res?.products ?? res ?? [];
        setItems(arr);
      } else {
        const r = await fetch("/api/admin/products", { credentials: "include" });
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
    await load();
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
      await load();
    } catch (e: any) {
      setErr(e?.message || "Ошибка удаления");
    }
  }

  return (
    <div>
      <div className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="panel-title">Товары</div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={() => setEditing({ title: "", price: 0 })}>Добавить товар</button>
        </div>
      </div>

      <div style={{ marginTop: 12 }}>
        {err && <div style={{ color: "red" }}>{err}</div>}
        {loading && <div className="small-muted">Загрузка…</div>}
        {!loading && items.length === 0 && <div className="small-muted">Товары не найдены</div>}
        {!loading && items.length > 0 && (
          <div style={{ display: "grid", gap: 8 }}>
            {items.map((p) => (
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
                    Цена: {(p as any).price ?? (p as any).base_price ?? "—"} ₽ • Категория: {p.category_id ?? "—"}
                    {Array.isArray(p.sizes) && p.sizes.length > 0 && (
                      <>
                        {" "}
                        • Размеры:{" "}
                        {p.sizes.length > 4 ? `${p.sizes[0]}–${p.sizes[p.sizes.length - 1]}` : p.sizes.join(", ")}
                      </>
                    )}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn ghost" onClick={() => setEditing(p)}>Ред.</button>
                  <button className="btn ghost" onClick={() => remove(p.id)}>Удалить</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {editing && <ProductModal open={true} product={editing} onClose={() => setEditing(null)} onSaved={onSaved} />}
    </div>
  );
}
