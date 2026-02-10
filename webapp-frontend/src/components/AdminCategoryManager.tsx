import React, { useEffect, useState } from "react";
import apiDefault from "../services/api";

type Category = { id: number; name: string; slug?: string; image_url?: string };

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

          <ul style={{ marginTop: 12 }}>
            {list.map((c) => (
              <li key={c.id} style={{ marginBottom: 8 }}>
                <strong>{c.name}</strong> — <span className="small-muted">{c.slug ?? c.image_url ?? ""}</span>
                <div style={{ display: "inline-block", marginLeft: 8 }}>
                  <button className="btn ghost" onClick={() => onDelete(c.id)}>Удалить</button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
