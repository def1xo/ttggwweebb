import React, { useEffect, useState } from "react";
import apiDefault from "../services/api";

type Manager = {
  id: number;
  user_id?: number;
  telegram_id?: number;
  username?: string;
  full_name?: string;
  role?: string;
  balance?: number;
};

export default function AdminManagersView() {
  const [list, setList] = useState<Manager[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [newId, setNewId] = useState("");

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setLoading(true); setErr(null);
    try {
      if (typeof apiDefault.getAdminManagers === "function") {
        const res = await apiDefault.getAdminManagers();
        const arr = Array.isArray(res) ? res : Array.isArray(res?.managers) ? res.managers : Array.isArray(res?.items) ? res.items : [];
        setList(arr);
      } else {
        const tryUrls = ["/api/admin/managers", "/admin/managers", "/api/managers"];
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
        const arr = Array.isArray(data) ? data : data?.managers ?? data?.items ?? [];
        setList(arr);
      }
    } catch (e: any) {
      setErr(e?.message || "Ошибка загрузки менеджеров");
    } finally {
      setLoading(false);
    }
  }

  async function onAdd(e?: React.FormEvent) {
    if (e) e.preventDefault();
    if (!newId) return setErr("Укажи Telegram user id");
    setErr(null);
    try {
      if (typeof apiDefault.addAdminManager === "function") {
        const res = await apiDefault.addAdminManager({ user_id: Number(newId) });
        if (res?.detail || res?.error) throw new Error(res?.detail || res?.error);
      } else {
        await fetch("/api/admin/managers", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_id: Number(newId) }),
        });
      }
      setNewId("");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Ошибка добавления");
    }
  }

  async function onToggleRole(id: number, role?: string) {
    setErr(null);
    try {
      const newRole = role === "manager" ? "assistant" : "manager";
      if (typeof apiDefault.patchAdminManager === "function") {
        await apiDefault.patchAdminManager(id, { role: newRole });
      } else {
        await fetch(`/api/admin/managers/${id}`, {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role: newRole }),
        });
      }
      await load();
    } catch (e: any) {
      setErr(e?.message || "Ошибка смены роли");
    }
  }

  async function onDelete(id: number) {
    if (!confirm("Удалить менеджера?")) return;
    setErr(null);
    try {
      if (typeof apiDefault.deleteAdminManager === "function") {
        await apiDefault.deleteAdminManager(id);
      } else {
        await fetch(`/api/admin/managers/${id}`, { method: "DELETE", credentials: "include" });
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
          <div className="panel-title">Менеджеры и ассистенты</div>
          <div><button className="btn" onClick={load}>Обновить</button></div>
        </div>

        <div style={{ marginTop: 12 }}>
          {err && <div style={{ color: "red" }}>{err}</div>}
          <form onSubmit={onAdd} style={{ display: "flex", gap: 8 }}>
            <input className="input" placeholder="Telegram user id" value={newId} onChange={(e) => setNewId(e.target.value)} />
            <button className="btn" type="submit">Добавить менеджера</button>
          </form>

          <div style={{ marginTop: 12 }}>
            {loading && <div className="small-muted">Загрузка…</div>}
            {!loading && list.length === 0 && <div className="small-muted">Нет менеджеров</div>}
            {!loading && list.length > 0 && (
              <div style={{ overflowX: "auto" }}>

              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th>id</th><th>tg id</th><th>ник</th><th>роль</th><th>баланс</th><th>действия</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map(m => (
                    <tr key={m.id}>
                      <td style={{ padding: 6, borderTop: "1px solid #222" }}>{m.id}</td>
                      <td style={{ padding: 6, borderTop: "1px solid #222" }}>{m.telegram_id ?? m.user_id ?? "-"}</td>
                      <td style={{ padding: 6, borderTop: "1px solid #222" }}>{m.username ?? m.full_name ?? "-"}</td>
                      <td style={{ padding: 6, borderTop: "1px solid #222" }}>{m.role}</td>
                      <td style={{ padding: 6, borderTop: "1px solid #222" }}>{m.balance ?? 0} ₽</td>
                      <td style={{ padding: 6, borderTop: "1px solid #222" }}>
                        <div style={{ display: "flex", gap: 6 }}>
                          <button className="btn ghost" onClick={() => onToggleRole(m.id, m.role)}>{m.role === "manager" ? "Сделать ассистентом" : "Сделать менеджером"}</button>
                          <button className="btn ghost" onClick={() => onDelete(m.id)}>Удалить</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
