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
  const [msg, setMsg] = useState<string | null>(null);
  const [newId, setNewId] = useState("");

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setLoading(true);
    setErr(null);
    setMsg(null);
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
    const userId = Number(newId);
    if (!Number.isFinite(userId) || userId <= 0) return setErr("Укажи корректный Telegram user id");

    setErr(null);
    setMsg(null);
    try {
      if (typeof apiDefault.addAdminManager === "function") {
        const res = await apiDefault.addAdminManager({ telegram_id: userId });
        if (res?.detail || res?.error) throw new Error(res?.detail || res?.error);
      } else {
        const resp = await fetch("/api/admin/managers", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ telegram_id: userId }),
        });
        if (!resp.ok) throw new Error((await resp.text()) || "Ошибка добавления");
      }

      setMsg("Пользователь добавлен ✅");
      setNewId("");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Ошибка добавления");
    }
  }

  async function onToggleRole(id: number, role?: string) {
    setErr(null);
    setMsg(null);
    try {
      const newRole = role === "manager" ? "assistant" : "manager";
      if (typeof apiDefault.patchAdminManager === "function") {
        await apiDefault.patchAdminManager(id, { role: newRole });
      } else {
        const resp = await fetch(`/api/admin/managers/${id}`, {
          method: "PATCH",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role: newRole }),
        });
        if (!resp.ok) throw new Error((await resp.text()) || "Ошибка смены роли");
      }
      setMsg("Роль обновлена ✅");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Ошибка смены роли");
    }
  }

  async function onDelete(id: number) {
    if (!confirm("Удалить менеджера?")) return;
    setErr(null);
    setMsg(null);
    try {
      if (typeof apiDefault.deleteAdminManager === "function") {
        await apiDefault.deleteAdminManager(id);
      } else {
        const resp = await fetch(`/api/admin/managers/${id}`, { method: "DELETE", credentials: "include" });
        if (!resp.ok) throw new Error((await resp.text()) || "Ошибка удаления");
      }
      setMsg("Пользователь удалён ✅");
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
          <div>
            <button className="btn" onClick={load}>Обновить</button>
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          {err && <div style={{ color: "#ff7b7b", marginBottom: 8 }}>{err}</div>}
          {msg && <div style={{ color: "#78e08f", marginBottom: 8 }}>{msg}</div>}

          <form onSubmit={onAdd} style={{ display: "flex", gap: 8 }}>
            <input className="input" placeholder="Telegram user id" value={newId} onChange={(e) => setNewId(e.target.value)} />
            <button className="btn" type="submit">Добавить менеджера</button>
          </form>

          <div style={{ marginTop: 12 }}>
            {loading && <div className="small-muted">Загрузка…</div>}
            {!loading && list.length === 0 && <div className="small-muted">Нет менеджеров</div>}
            {!loading && list.length > 0 && (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden" }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left", padding: 8 }}>id</th>
                      <th style={{ textAlign: "left", padding: 8 }}>tg id</th>
                      <th style={{ textAlign: "left", padding: 8 }}>ник</th>
                      <th style={{ textAlign: "left", padding: 8 }}>роль</th>
                      <th style={{ textAlign: "left", padding: 8 }}>баланс</th>
                      <th style={{ textAlign: "left", padding: 8 }}>действия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((m) => (
                      <tr key={m.id}>
                        <td style={{ padding: 8, borderTop: "1px solid #222" }}>{m.id}</td>
                        <td style={{ padding: 8, borderTop: "1px solid #222" }}>{m.telegram_id ?? m.user_id ?? "-"}</td>
                        <td style={{ padding: 8, borderTop: "1px solid #222" }}>{m.username ?? m.full_name ?? "-"}</td>
                        <td style={{ padding: 8, borderTop: "1px solid #222" }}>{m.role}</td>
                        <td style={{ padding: 8, borderTop: "1px solid #222" }}>{m.balance ?? 0} ₽</td>
                        <td style={{ padding: 8, borderTop: "1px solid #222" }}>
                          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                            <button className="btn ghost" onClick={() => onToggleRole(m.id, m.role)}>
                              {m.role === "manager" ? "Сделать ассистентом" : "Сделать менеджером"}
                            </button>
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
