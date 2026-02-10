// webapp-frontend/src/pages/ManagerDashboard.tsx
import React, { useEffect, useState } from "react";
import { getManagerAssistants, addManagerAssistant, patchManagerAssistant } from "../services/api";
import axiosInstance from "../services/axiosInstance";
import { Link } from "react-router-dom";
import "../main.css";

type Assist = {
  id: number;
  user_id?: number;
  username?: string;
  full_name?: string;
  percent?: number;
  balance?: number;
};

export default function ManagerDashboard() {
  const [items, setItems] = useState<Assist[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [newId, setNewId] = useState<string>("");
  const [newPercent, setNewPercent] = useState<number>(0);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  async function load() {
    setErr(null);
    setLoading(true);
    try {
      const res = await getManagerAssistants();
      const list = Array.isArray(res) ? res : res?.assistants ?? [];
      setItems(list as Assist[]);
    } catch (e: any) {
      setErr(e?.message || "Не удалось загрузить список подручных");
    } finally {
      setLoading(false);
    }
  }

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (!newId) {
      setErr("Укажи Telegram user id");
      return;
    }
    try {
      await addManagerAssistant({ user_id: Number(newId), percent: Number(newPercent) });
      setNewId("");
      setNewPercent(0);
      setRefreshKey((k) => k + 1);
    } catch (e: any) {
      setErr(e?.message || "Ошибка при добавлении подручного");
    }
  }

  async function onChangePercent(id: number, percent: number) {
    try {
      await patchManagerAssistant(id, { percent });
      setRefreshKey((k) => k + 1);
    } catch (e: any) {
      setErr(e?.message || "Ошибка при обновлении процента");
    }
  }

  async function onRemove(id: number) {
    if (!confirm("Удалить подручного?")) return;
    try {
      await axiosInstance.delete(`/api/manager/assistants/${id}`);
      setRefreshKey((k) => k + 1);
    } catch (e: any) {
      setErr(e?.message || "Ошибка при удалении");
    }
  }

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <h2>Панель менеджера</h2>
        <div>
          <Link to="/profile" className="btn ghost">Назад в профиль</Link>
        </div>
      </div>

      <div style={{ marginTop: 12 }}>
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontWeight: 700 }}>Баланс</div>
            <div className="small-muted">Здесь будет баланс менеджера (см. API)</div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontWeight: 700 }}>Подручные</div>
            <div>
              <button className="btn" onClick={() => setRefreshKey(k => k + 1)}>Обновить</button>
            </div>
          </div>

          <div style={{ marginTop: 12 }}>
            {loading && <div className="small-muted">Загрузка…</div>}
            {err && <div style={{ color: "red" }}>{err}</div>}

            {!loading && items.length === 0 && <div className="small-muted">У вас пока нет подручных</div>}

            {!loading && items.length > 0 && (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th>id</th>
                    <th>telegram</th>
                    <th>имя</th>
                    <th>баланс</th>
                    <th>процент</th>
                    <th>действия</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.id}>
                      <td>{it.id}</td>
                      <td>{it.username ?? it.user_id ?? "-"}</td>
                      <td>{it.full_name ?? "-"}</td>
                      <td>{typeof it.balance === "number" ? `${it.balance} ₽` : `${it.balance ?? 0} ₽`}</td>
                      <td>
                        <input
                          type="number"
                          value={it.percent ?? 0}
                          onChange={(e) => {
                            const val = Number(e.target.value);
                            setItems(prev => prev.map(p => p.id === it.id ? { ...p, percent: val } : p));
                          }}
                          onBlur={(e) => onChangePercent(it.id, Number(e.currentTarget.value))}
                          style={{ width: 80 }}
                        />
                      </td>
                      <td>
                        <button className="btn ghost" onClick={() => onRemove(it.id)}>Удалить</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div style={{ marginTop: 12 }}>
              <form onSubmit={onAdd} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input className="input" placeholder="Telegram user id" value={newId} onChange={(e)=>setNewId(e.target.value)} />
                <input className="input" type="number" placeholder="процент (0-10)" value={newPercent} onChange={(e)=>setNewPercent(Number(e.target.value))} style={{ width: 120 }} />
                <button className="btn" type="submit">Добавить подручного</button>
              </form>
              <div className="small-muted" style={{ marginTop: 8 }}>
                Подручные могут иметь процент, который вы назначаете (frontend отправляет на API). Если сервер вернёт ошибку — она будет показана.
              </div>
            </div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 12 }}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Промо-коды (управление)</div>
          <div className="small-muted">
            Управление промо-кодами пока требует бэкенд-эндпоинтов. Здесь мы покажем форму и отправим запрос на `/api/manager/promo` — если такого эндпоинта нет, появится сообщение об ошибке.
          </div>
          <PromoManager />
        </div>
      </div>
    </div>
  );
}

/* Встроенный компонент: управление промо — пробует отправить на бек, но показывает понятную ошибку, если endpoint отсутствует */
function PromoManager() {
  const [list, setList] = useState<string[]|null>(null);
  const [newCode, setNewCode] = useState("");
  const [err, setErr] = useState<string|null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(()=>{ load(); }, []);

  async function load() {
    setErr(null);
    setLoading(true);
    try {
      const res = await axiosInstance.get("/api/manager/promo");
      const data = res?.data !== undefined ? res.data : res;
      // data can be { items: [...] } or array or object; normalize to array of strings
      let itemsArr: string[] = [];
      if (Array.isArray(data)) itemsArr = data as string[];
      else if (Array.isArray(data?.items)) itemsArr = data.items;
      else if (Array.isArray(data?.promos)) itemsArr = data.promos;
      else if (typeof data === "object" && data !== null) {
        // try to map object values to strings
        itemsArr = Object.values(data).filter(v => typeof v === "string") as string[];
      } else {
        itemsArr = [];
      }
      setList(itemsArr);
    } catch (e: any) {
      setList(null);
      setErr("Промо-эндпоинт недоступен на сервере.");
    } finally {
      setLoading(false);
    }
  }

  async function add() {
    setErr(null);
    if (!newCode) {
      setErr("Укажи код");
      return;
    }
    try {
      await axiosInstance.post("/api/manager/promo", { code: newCode });
      setNewCode("");
      await load();
    } catch (e: any) {
      setErr(e?.message || "Ошибка при добавлении промо");
    }
  }

  return (
    <div style={{ marginTop: 8 }}>
      {err && <div style={{ color: "red", marginBottom: 8 }}>{err}</div>}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input className="input" value={newCode} onChange={e=>setNewCode(e.target.value)} placeholder="Новый промо-код" />
        <button className="btn" onClick={add}>Добавить</button>
        <button className="btn ghost" onClick={load}>Обновить</button>
      </div>

      {loading && <div className="small-muted" style={{ marginTop: 8 }}>Загрузка…</div>}

      {list && list.length > 0 && (
        <ul style={{ marginTop: 8 }}>
          {list.map((c,i)=> <li key={i}>{c}</li>)}
        </ul>
      )}

      {list && list.length === 0 && !loading && <div className="small-muted" style={{ marginTop: 8 }}>Промо отсутствуют</div>}
    </div>
  );
}
