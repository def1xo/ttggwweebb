import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import PaymentDetails from "../components/PaymentDetails";
import api from "../services/api";
import { useToast } from "../contexts/ToastContext";
import UploadProofModal from "../components/UploadProofModal";

type OrderAny = any;

type Step = { key: string; label: string };

const STEPS: Step[] = [
  { key: "awaiting_payment", label: "Ожидает оплату" },
  { key: "paid", label: "Чек загружен" },
  { key: "processing", label: "В обработке" },
  { key: "sent", label: "Отправлен" },
  { key: "received", label: "Получен" },
  { key: "delivered", label: "Доставлен" },
];

function normalizeStatus(s: any): string {
  if (!s) return "";
  const raw = String(s);
  // Enum may be like "OrderStatus.paid" or just "paid"
  const last = raw.split(".").pop() || raw;
  return last.trim();
}

function statusLabel(s: any): string {
  const key = normalizeStatus(s);
  const found = STEPS.find((x) => x.key === key);
  if (found) return found.label;
  if (!key) return "—";
  return key;
}

export default function OrderSuccess() {
  const { id } = useParams<{ id: string }>();
  const { notify } = useToast();

  const [order, setOrder] = useState<OrderAny | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [proofOpen, setProofOpen] = useState(false);

  async function load() {
    if (!id) return;
    setLoading(true);
    setErr(null);
    try {
      const res = await api.get(`/api/orders/${id}`);
      const data = (res as any).data ?? res;
      setOrder(data);
    } catch (e: any) {
      setOrder(null);
      setErr(e?.response?.data?.detail || e?.message || "Не удалось загрузить заказ");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const statusKey = useMemo(() => normalizeStatus(order?.status), [order?.status]);

  const currentStepIndex = useMemo(() => {
    const idx = STEPS.findIndex((s) => s.key === statusKey);
    return idx >= 0 ? idx : 0;
  }, [statusKey]);

  const canUpload = useMemo(() => {
    // allow re-upload if awaiting_payment or paid (replacement)
    return statusKey === "awaiting_payment" || statusKey === "paid" || !statusKey;
  }, [statusKey]);

  const paymentUrl = (order as any)?.payment_screenshot ? String((order as any).payment_screenshot) : null;

  return (
    <div className="container" style={{ paddingTop: 12, paddingBottom: 90 }}>
      <div className="card" style={{ padding: 14 }}>
        <div style={{ fontWeight: 900, fontSize: 18 }}>✅ Заказ оформлен</div>
        <div className="small-muted" style={{ marginTop: 6 }}>
          Номер заказа: <b>#{id}</b>
        </div>

        {loading ? <div className="small-muted" style={{ marginTop: 10 }}>Загрузка…</div> : null}
        {err ? <div style={{ color: "salmon", marginTop: 10 }}>{err}</div> : null}

        {!err ? (
          <div style={{ marginTop: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
              <div className="small-muted">Статус</div>
              <div style={{ fontWeight: 900 }}>{statusLabel(order?.status)}</div>
            </div>

            <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
              {STEPS.map((s, idx) => {
                const done = idx <= currentStepIndex;
                return (
                  <span
                    key={s.key}
                    className="chip"
                    style={{
                      borderColor: done ? "var(--ring)" : "var(--border)",
                      opacity: done ? 1 : 0.55,
                    }}
                  >
                    {s.label}
                  </span>
                );
              })}
            </div>

            <div className="small-muted" style={{ marginTop: 10 }}>
              После оплаты прикрепите чек и подтвердите отправку. Мы проверим оплату и уведомим вас.
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ marginTop: 12 }}>
        <PaymentDetails amount={Number((order as any)?.total_amount || (order as any)?.total || 0)} />
      </div>

      <div className="card" style={{ padding: 14, marginTop: 12 }}>
        <div style={{ fontWeight: 900, marginBottom: 10 }}>📎 Подтверждение оплаты</div>

        {paymentUrl ? (
          <div className="card" style={{ padding: 12, marginBottom: 10 }}>
            <div className="small-muted">Чек прикреплён</div>
            <a href={paymentUrl} target="_blank" rel="noreferrer" className="btn" style={{ marginTop: 8 }}>
              Открыть файл
            </a>
          </div>
        ) : null}

        <button
          className="btn-primary"
          style={{ width: "100%", marginTop: 12 }}
          onClick={() => setProofOpen(true)}
          disabled={!canUpload}
        >
          {canUpload ? "Подтвердить чек" : "Чек уже принят"}
        </button>

        <div style={{ marginTop: 12, display: "flex", gap: 10, justifyContent: "space-between" }}>
          <Link to="/profile" className="btn ghost">Профиль / Заказы</Link>
          <Link to="/catalog" className="btn">В магазин</Link>
        </div>
      </div>

      <div className="small-muted" style={{ marginTop: 12, textAlign: "center" }}>
        Если что-то не получается — напишите менеджеру в Telegram.
      </div>

      {id ? (
        <UploadProofModal
          open={proofOpen}
          orderId={id}
          onClose={() => setProofOpen(false)}
          onUploaded={async () => {
            await load();
            setProofOpen(false);
            notify("Спасибо за покупку! Чек отправлен на проверку 💙", "success");
          }}
        />
      ) : null}
    </div>
  );
}
