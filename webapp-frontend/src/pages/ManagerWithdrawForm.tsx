// webapp-frontend/src/pages/ManagerWithdrawForm.tsx
import React, { useState } from "react";
import api from "../services/api";

export default function ManagerWithdrawForm() {
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("card");
  const [fio, setFio] = useState("");
  const [details, setDetails] = useState("");
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");

  const submit = async () => {
    setLoading(true);
    setMsg("");
    try {
      const payload = {
        amount: Number(amount),
        currency: "RUB",
        target_details: { fio, method, details },
        comment: ""
      };
      const res = await api.post("/manager/withdraws", payload);
      setMsg("Заявка создана: " + res.data.withdraw_id);
    } catch (err:any) {
      setMsg(err?.response?.data?.detail || "Ошибка");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto p-6 bg-white rounded shadow">
      <h2 className="text-xl font-semibold mb-4">Запрос на выплату</h2>
      <label className="block mb-2">
        <div className="text-sm text-gray-600">Сумма</div>
        <input value={amount} onChange={e=>setAmount(e.target.value)} className="mt-1 w-full p-2 border rounded" />
      </label>
      <label className="block mb-2">
        <div className="text-sm text-gray-600">ФИО</div>
        <input value={fio} onChange={e=>setFio(e.target.value)} className="mt-1 w-full p-2 border rounded" />
      </label>
      <label className="block mb-2">
        <div className="text-sm text-gray-600">Метод</div>
        <select value={method} onChange={e=>setMethod(e.target.value)} className="mt-1 w-full p-2 border rounded">
          <option value="card">Карта</option>
          <option value="phone">Телефон</option>
          <option value="bank">Банк</option>
        </select>
      </label>
      <label className="block mb-4">
        <div className="text-sm text-gray-600">Детали (номер карты/телефон/реквизиты)</div>
        <input value={details} onChange={e=>setDetails(e.target.value)} className="mt-1 w-full p-2 border rounded" />
      </label>

      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-500">{msg}</div>
        <button onClick={submit} disabled={loading} className="px-4 py-2 bg-black text-white rounded">
          {loading ? "Отправка..." : "Запросить выплату"}
        </button>
      </div>
    </div>
  );
}
