// src/components/ManagerPanelMini.tsx
import React, { useEffect, useState } from "react";
import { getMyProfile } from "../services/api";
import { Link } from "react-router-dom";

export default function ManagerPanelMini() {
  const [me, setMe] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data = await getMyProfile();
        setMe(data);
      } catch (e) {
        setMe(null);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="small-muted" style={{ padding: 8 }}>Загрузка…</div>;
  if (!me) return null;

  const role = me?.role || "user";
  const isManager = role === "manager" || role === "supermanager";
  const isAssistant = role === "assistant";
  const isAdmin = role === "admin" || role === "superadmin";

  if (!isManager && !isAssistant && !isAdmin) return null;

  return (
    <div className="card mini-panel-card">
      <div style={{ fontWeight: 700, marginBottom: 8 }}>{isAdmin ? "Админ-панель" : isManager ? "Менеджерская" : "Ваша панель"}</div>
      <div className="small-muted" style={{ marginBottom: 8 }}>
        {isManager && "Быстрый доступ к панели менеджера."}
        {isAssistant && "Панель подручного: запрос выплат и история."}
        {isAdmin && "Доступ в админку."}
      </div>

      <div className="mini-panel-actions">
        {isManager && (
          <Link to="/manager" className="btn mini-panel-btn" style={{ textDecoration: "none" }}>
            Перейти в панель менеджера
          </Link>
        )}

        {isAssistant && (
          <Link to="/assistant" className="btn mini-panel-btn" style={{ textDecoration: "none" }}>
            Перейти в панель подручного
          </Link>
        )}

        {isAdmin && (
          <Link to="/admin" className="btn mini-panel-btn" style={{ textDecoration: "none" }}>
            Перейти в админку
          </Link>
        )}
      </div>

      <div style={{ marginTop: 10 }} className="small-muted">
        {me?.balance !== undefined ? <>Баланс: <strong>{me.balance} ₽</strong></> : null}
      </div>
    </div>
  );
}
