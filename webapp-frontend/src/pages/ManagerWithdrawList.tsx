// webapp-frontend/src/pages/ManagerWithdrawList.tsx
import React, { useEffect, useState } from "react";
import api from "../services/api";

export default function ManagerWithdrawList() {
  const [rows, setRows] = useState<any[]>([]);
  const [balance, setBalance] = useState<number>(0);
  const [hold, setHold] = useState<number>(0);
  const [loading, setLoading] = useState(false);

  useEffect(()=>{ load(); }, []);

  async function load() {
    setLoading(true);
    try {
      const r = await api.get("/manager/withdraws");
      const data = (r as any)?.data ?? r;
      setRows(data?.items || (Array.isArray(data) ? data : []));
      setBalance(Number(data?.balance || 0));
      setHold(Number(data?.balance_hold || 0));
    } catch (e) {
      console.error(e);
    } finally { setLoading(false); }
  }

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h2 className="text-xl font-semibold mb-4">Заявки (ваши и подручных)</h2>
      <div className="mb-4 p-3 rounded bg-white border">
        <div className="text-sm text-gray-600">Доступно: <b>{balance.toFixed(2)}</b> | В холде: <b>{hold.toFixed(2)}</b></div>
      </div>
      {rows.map(r => (
        <div key={r.id} className="p-3 mb-2 border rounded bg-white">
          <div className="flex justify-between">
            <div>
              <div className="font-medium">#{r.id} — {r.amount} {r.currency}</div>
              <div className="text-sm text-gray-600">От: {r.requester_user_id}</div>
              <div className="text-sm text-gray-600">Статус: {r.status}</div>
            </div>
            <div className="text-sm text-gray-500">{new Date(r.created_at).toLocaleString()}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
