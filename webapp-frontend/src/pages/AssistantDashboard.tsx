import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { assistantRequestWithdraw, getAssistantDashboard } from "../services/api";
import "../main.css";

type CommissionRow = {
  id?: number;
  order_id?: number;
  amount?: number;
  created_at?: string;
};

type ReferredRow = {
  user_id?: number;
  bound_at?: string;
};

export default function AssistantDashboard() {
  const [loading, setLoading] = useState(true);
  const [balance, setBalance] = useState<number>(0);
  const [commissions, setCommissions] = useState<CommissionRow[]>([]);
  const [referred, setReferred] = useState<ReferredRow[]>([]);
  const [reqAmount, setReqAmount] = useState<number>(0);
  const [reqDetails, setReqDetails] = useState<string>("");
  const [msg, setMsg] = useState<string | null>(null);

  async function load() {
    setMsg(null);
    setLoading(true);
    try {
      const data: any = await getAssistantDashboard();
      setBalance(Number(data?.balance ?? 0));
      setCommissions(Array.isArray(data?.commissions) ? (data.commissions as CommissionRow[]) : []);
      setReferred(Array.isArray(data?.referred) ? (data.referred as ReferredRow[]) : []);
    } catch (e: any) {
      setMsg(e?.message || "Не удалось загрузить кабинет подручного");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submitWithdraw = async () => {
    setMsg(null);
    try {
      await assistantRequestWithdraw(reqAmount, reqDetails);
      setMsg("Запрос на выплату отправлен");
      setReqAmount(0);
      setReqDetails("");
      await load();
    } catch (e: any) {
      setMsg(e?.message || "Не удалось отправить запрос");
    }
  };

  return (
    <div className="container" style={{ paddingTop: 12, paddingBottom: 90 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <h2>Панель подручного</h2>
        <Link to="/profile" className="btn ghost">Назад в профиль</Link>
      </div>

      {loading ? (
        <div className="small-muted" style={{ marginTop: 12 }}>Загрузка…</div>
      ) : null}

      {msg ? (
        <div className="card" style={{ marginTop: 12, padding: 12 }}>{msg}</div>
      ) : null}

      <div className="card" style={{ marginTop: 12, padding: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontWeight: 800 }}>Баланс</div>
          <div style={{ fontWeight: 900 }}>{balance.toFixed(2)} ₽</div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 12, padding: 12 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Комиссии</div>
        {commissions.length === 0 ? (
          <div className="small-muted">Нет комиссий</div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {commissions.map((c, idx) => (
              <div key={c.id ?? idx} className="card" style={{ padding: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>Заказ #{c.order_id ?? "—"}</div>
                    <div className="small-muted">{c.created_at ? String(c.created_at) : ""}</div>
                  </div>
                  <div style={{ fontWeight: 900 }}>{Number(c.amount ?? 0).toFixed(2)} ₽</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 12, padding: 12 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Приведённые пользователи</div>
        {referred.length === 0 ? (
          <div className="small-muted">Нет</div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {referred.map((r, idx) => (
              <div key={r.user_id ?? idx} className="card" style={{ padding: 10 }}>
                <div style={{ fontWeight: 700 }}>User ID: {r.user_id ?? "—"}</div>
                {r.bound_at ? <div className="small-muted">bound at: {String(r.bound_at)}</div> : null}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 12, padding: 12 }}>
        <div style={{ fontWeight: 800, marginBottom: 10 }}>Запросить выплату</div>
        <div style={{ display: "grid", gap: 10 }}>
          <input
            type="number"
            className="input"
            value={reqAmount}
            onChange={(e) => setReqAmount(Number(e.target.value))}
            placeholder="Сумма"
          />
          <input
            className="input"
            value={reqDetails}
            onChange={(e) => setReqDetails(e.target.value)}
            placeholder="Реквизиты"
          />
          <button className="btn-primary" onClick={submitWithdraw} disabled={!reqAmount || !reqDetails}>
            Запросить
          </button>
        </div>
        <div className="small-muted" style={{ marginTop: 8 }}>
          Заявка отправляется менеджеру/админу и попадёт в список выплат.
        </div>
      </div>
    </div>
  );
}
