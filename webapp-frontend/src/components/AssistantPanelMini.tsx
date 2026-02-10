// src/components/AssistantPanelMini.tsx
import React, { useEffect, useState } from "react";
import { getMyProfile } from "../services/api";

/**
 * Панель подручного: выглядит похожей на менеджерскую,
 * но функционал обрезан: нет управления подручными и выплаты ими.
 * Подручный не увидит ярлык \"Подручный\" — в профиле это просто ваша панель.
 */

export default function AssistantPanelMini() {
  const [me, setMe] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await getMyProfile();
      setMe(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(()=>{ load(); }, []);

  return (
    <div className="card mini-panel-card">
      <div className="panel-title">Ваша панель</div>
      <div className="small-muted">Здесь отображается ваш баланс и история операций (когда подключим историю, она появится здесь).</div>

      <div style={{ marginTop:12 }}>
        <div style={{ display:"flex", justifyContent:"space-between", gap:8, alignItems:"center" }}>
          <div>
            <div style={{ fontWeight:800, fontSize:18 }}>{me?.full_name || me?.username || "Вы"}</div>
            <div className="small-muted">Баланс: <strong>{me?.balance ?? 0} ₽</strong></div>
          </div>
        </div>

        <div style={{ marginTop:12 }} className="mini-panel-actions">
          <button className="btn mini-panel-btn" onClick={()=> alert("Запрос на выплату отправлен менеджеру (пока заглушка).")}>Запросить выплату</button>
          <button className="btn ghost mini-panel-btn" onClick={load}>Обновить</button>
        </div>
      </div>
    </div>
  );
}
