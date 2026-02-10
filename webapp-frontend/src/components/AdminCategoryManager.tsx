import React, { useEffect, useState } from "react";
import apiDefault from "../services/api";

type Category = { id: number; name: string; slug?: string };

function normalizeCategories(data: any): Category[] {
  const arr = Array.isArray(data) ? data : Array.isArray(data?.categories) ? data.categories : Array.isArray(data?.items) ? data.items : [];
  return arr as Category[];
}

function normalizeCategories(data: any): Category[] {
  const arr = Array.isArray(data) ? data : Array.isArray(data?.categories) ? data.categories : Array.isArray(data?.items) ? data.items : [];
  return arr as Category[];
}

export default function AdminCategoryManager() {
  const [list, setList] = useState<Category[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");

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
      if (typeof apiDefault.getAdminCategories === "function") {
        const res = await apiDefault.getAdminCategories();
        if (res?.detail || res?.error) {
          setErr(res?.detail || res?.error || "Ошибка загрузки категорий");
          setList([]);
          return;
        }
        setList(normalizeCategories(res));
      } else {
        const tryUrls = ["/api/admin/categories", "/admin/categories", "/api/categories", "/categories"];
        let data: any = null;
        for (const u of tryUrls) {
          try {
            const r = await fetch(u, { credentials: "include" });
            if (r.ok) {
              data = await r.json();
              break;
            }
          } catch {}
        }
        setList(normalizeCategories(data));
      }
    } catch (e: any) {
      setErr(e?.message || "Ошибка загрузки категорий");
    } finally {
      setLoading(false);
    }
  }

  async function onCreate(e?: React.FormEvent) {
    if (e) e.preventDefault();
    if (!name.trim()) return setErr("Укажи название");
    setErr(null);
    try {
      if (typeof apiDefault.createAdminCategory === "function") {
        await apiDefault.createAdminCategory({ name: name.trim(), slug: slug.trim() });
      } else if (typeof apiDefault.createCategory === "function") {
        await apiDefault.createCategory({ name: name.trim() });
      } else {
        // backend admin categories may require multipart/form-data (name: Form(...))
        const fd = new FormData();
        fd.append("name", name.trim());
        if (slug.trim()) fd.append("slug", slug.trim());
        const resp = await fetch("/api/admin/categories", {
          method: "POST",
          credentials: "include",
          body: fd,
        });
        if (!resp.ok) {
          const txt = await resp.text();
          throw new Error(txt || "Ошибка создания");
        }
      }
      setName("");
      setSlug("");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Ошибка создания");
    }
  }

  async function onDelete(id: number) {
    if (!confirm("Удалить категорию?")) return;
    setErr(null);
    try {
      if (typeof apiDefault.deleteAdminCategory === "function") {
        await apiDefault.deleteAdminCategory(id);
      } else if (typeof apiDefault.deleteCategory === "function") {
        await apiDefault.deleteCategory(id);
      } else {
        await fetch(`/api/admin/categories/${id}`, { method: "DELETE", credentials: "include" });
      }
      await load();
    } catch (e: any) {
      setErr(e?.message || "Ошибка удаления");
    }
  }

  return (
    <div>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div className="panel-title">Категории</div>
          {loading ? <div className="small-muted">Загрузка…</div> : null}
        </div>

        <div style={{ marginTop: 12 }}>
          {err && <div style={{ color: "red" }}>{err}</div>}

          <form onSubmit={onCreate} style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
            <input className="input" placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} />
            <input className="input" placeholder="slug (url)" value={slug} onChange={(e) => setSlug(e.target.value)} />
            <button className="btn" type="submit" disabled={loading}>Создать</button>
          </form>

          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 10 }}>
            {list.map((c) => (
              <div key={c.id} className="card" style={{ padding: 12 }}>
                <div style={{ fontWeight: 800, marginBottom: 4 }}>{c.name}</div>
                <div className="small-muted" style={{ minHeight: 18 }}>{c.slug || "—"}</div>
                <button className="btn ghost" style={{ marginTop: 10 }} onClick={() => onDelete(c.id)}>Удалить</button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
