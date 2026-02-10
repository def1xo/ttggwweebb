// webapp-frontend/src/pages/AdminWithdrawsList.tsx
import React, { useEffect, useState } from "react";
import api from "../services/api";

export default function AdminWithdrawsList() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(()=>{ load(); }, []);

  async function load() {
    try {
      const r = await api.get("/admin/withdraws");
      setRows(r.data || []);
    } catch (e) {
      console.error(e);
    }
  }

  async function approve(id:number) {
    await api.post(`/admin/withdraws/${id}/approve`, {});
    load();
  }
  async function markPaid(id:number) {
    await api.post(`/admin/withdraws/${id}/mark_paid`, {});
    load();
  }
  async function reject(id:number) {
    await api.post(`/admin/withdraws/${id}/reject`, { reason: "отклонено админом" });
    load();
  }

  return (
    <div className="max-w-6xl mx-auto p-6">
      <h2 className="text-2xl font-semibold mb-4">Заявки на выплату</h2>
      {rows.map(r => (
        <div key={r.id} className="p-4 mb-3 bg-white border rounded flex justify-between">
          <div>
            <div className="font-medium">#{r.id} — {r.amount} {r.currency}</div>
            <div className="text-sm text-gray-600">От: {r.requester_user_id} (менеджер: {r.manager_user_id})</div>
            <div className="text-sm text-gray-600">Детали: {JSON.stringify(r.target_details)}</div>
            <div className="text-sm text-gray-500">Статус: {r.status}</div>
          </div>
          <div className="flex flex-col gap-2">
            {r.status === "pending" && <button onClick={()=>approve(r.id)} className="px-3 py-2 bg-green-600 text-white rounded">Approve</button>}
            {r.status !== "paid" && <button onClick={()=>markPaid(r.id)} className="px-3 py-2 bg-black text-white rounded">Mark Paid</button>}
            {r.status === "pending" && <button onClick={()=>reject(r.id)} className="px-3 py-2 bg-red-600 text-white rounded">Reject</button>}
          </div>
        </div>
      ))}
    </div>
  );
}
