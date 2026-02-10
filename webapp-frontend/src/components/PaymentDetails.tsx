// src/components/PaymentDetails.tsx
import React, { useEffect, useState } from "react";
import { getPaymentRequisites } from "../services/api";

/**
 * Простой и четкий блок реквизитов.
 * Заменяй значения в константах ниже на свои реальные (телефон, карта, банк, ФИО).
 *
 * Не забудь: если будешь хранить реальные реквизиты в коде — это твоя ответственность.
 */

type Requisites = {
  recipient_name?: string | null;
  phone?: string | null;
  card_number?: string | null;
  bank_name?: string | null;
  note?: string | null;
};

function Row({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1300);
    } catch {
      // fallback
      const ta = document.createElement("textarea");
      ta.value = value;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 1300);
    }
  };

  return (
    <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
      <div style={{ minWidth: 100, color: "var(--muted)", fontSize: 13 }}>{label}</div>
      <div style={{ flex: 1, background: "rgba(255,255,255,0.02)", padding: 10, borderRadius: 10, border: "1px solid var(--border)", wordBreak: "break-word" }}>
        <div style={{ fontWeight: 700 }}>{value}</div>
      </div>
      <button className="btn ghost" onClick={copy} aria-label={`Copy ${label}`}>
        {copied ? "Скопировано" : "Копировать"}
      </button>
    </div>
  );
}

export default function PaymentDetails({ amount }: { amount?: number | null }) {
  const [req, setReq] = useState<Requisites | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const data: any = await getPaymentRequisites();
        setReq({
          recipient_name: data?.recipient_name ?? null,
          phone: data?.phone ?? null,
          card_number: data?.card_number ?? null,
          bank_name: data?.bank_name ?? null,
          note: data?.note ?? null,
        });
      } catch {
        setReq(null);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const fio = req?.recipient_name || "—";
  const phone = req?.phone || "—";
  const card = req?.card_number || "—";
  const bank = req?.bank_name || "—";
  const amountNum = Number(amount || 0);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 12 }}>
      <div style={{ fontWeight: 900, fontSize: 16, marginBottom: 6 }}>Реквизиты для оплаты</div>
      {amountNum > 0 ? (
        <div className="card" style={{ padding: 12 }}>
          <div className="small-muted">Сумма к оплате</div>
          <div style={{ marginTop: 4, fontSize: 24, fontWeight: 900 }}>
            {new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 }).format(amountNum)}
          </div>
        </div>
      ) : null}

      <div className="card" style={{ padding: 12 }}>
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 6 }}>Получатель</div>
          <div style={{ fontWeight: 800 }}>{fio}</div>
        </div>

        <Row label="Телефон (для оплаты / связь)" value={phone} />
        <Row label="Номер карты" value={card} />
        <Row label="Банк" value={bank} />

        {req?.note ? (
          <div className="small-muted" style={{ marginTop: 8 }}>{req.note}</div>
        ) : (
          <div className="small-muted" style={{ marginTop: 8 }}>
            После оплаты обязательно загрузите чек (jpg/png/webp/pdf) — без чека заказ не будет подтверждён.
          </div>
        )}

        {loading ? <div className="small-muted" style={{ marginTop: 8 }}>Загрузка реквизитов…</div> : null}
      </div>
    </div>
  );
}
