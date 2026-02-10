import React, { useEffect, useState } from "react";
import apiDefault from "../services/api";

type Category = { id: number; name: string; slug?: string; image_url?: string };

export default function AdminCategoryManager() {
  const [list, setList] = useState<Category[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      if (typeof apiDefault.getAdminCategories === "function") {
        const res = await apiDefault.getAdminCategories();
        const arr = res?.categories ?? res ?? [];
        setList(arr);
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
        const arr = Array.isArray(data) ? data : data?.items ?? data?.categories ?? [];
        setList(arr);
      }
    } catch (e: any) {
      setErr(e?.message || "Ошибка загрузки категорий");
    } finally {
      setLoading(false);
    }
  }

  async function onCreate(e?: React.FormEvent) {
    if (e) e.preventDefault();
    if (!name) return setErr("Укажи название");
    setErr(null);
    try {
      if (typeof apiDefault.createAdminCategory === "function") {
        await apiDefault.createAdminCategory({ name, slug });
      } else if (typeof apiDefault.createCategory === "function") {
        await apiDefault.createCategory({ name });
      } else {
        await fetch("/api/admin/categories", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, slug }),
        });
      }
      setName(""); setSlug("");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Ошибка создания");
    }
  }

  async function onSaveEdit(id: number) {
    setErr(null);
    try {
      if (typeof apiDefault.updateAdminCategory === "function") {
        await apiDefault.updateAdminCategory(id, { name, slug });
      } else {
        await fetch(`/api/admin/categories/${id}`, {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, slug }),
        });
      }
      setEditingId(null);
      setName(""); setSlug("");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Ошибка редактирования");
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
          <div><button className="btn" onClick={load}>Обновить</button></div>
        </div>

        <div style={{ marginTop: 12 }}>
          {err && <div style={{ color: "red" }}>{err}</div>}
          {loading && <div className="small-muted">Загрузка…</div>}

          <form onSubmit={onCreate} style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <input className="input" placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} />
            <input className="input" placeholder="slug (url)" value={slug} onChange={(e) => setSlug(e.target.value)} />
            <button className="btn" type="submit">Создать</button>
          </form>

          <ul style={{ marginTop: 12 }}>
            {list.map((c) => (
              <li key={c.id} style={{ marginBottom: 8 }}>
                <strong>{c.name}</strong> — <span className="small-muted">{c.slug ?? c.image_url ?? ""}</span>
                <div style={{ display: "inline-block", marginLeft: 8 }}>
                  <button className="btn ghost" onClick={() => { setEditingId(c.id); setName(c.name); setSlug(c.slug ?? ""); }}>Редактировать</button>
                  <button className="btn ghost" onClick={() => onDelete(c.id)}>Удалить</button>
                </div>
                {editingId === c.id && (
                  <div style={{ marginTop: 8 }}>
                    <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
                    <input className="input" value={slug} onChange={(e) => setSlug(e.target.value)} />
                    <button className="btn" onClick={() => onSaveEdit(c.id)}>Сохранить</button>
                    <button className="btn ghost" onClick={() => { setEditingId(null); setName(""); setSlug(""); }}>Отмена</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
