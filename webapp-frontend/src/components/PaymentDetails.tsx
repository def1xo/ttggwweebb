// src/components/PaymentDetails.tsx
import React, { useEffect, useMemo, useState } from "react";
import { getPaymentRequisites } from "../services/api";

type Requisites = {
  recipient_name?: string | null;
  phone?: string | null;
  card_number?: string | null;
  bank_name?: string | null;
  note?: string | null;
};

function formatPhone(raw: string): string {
  const digits = String(raw || "").replace(/\D/g, "");
  if (digits.length === 11 && (digits.startsWith("7") || digits.startsWith("8"))) {
    const normalized = `7${digits.slice(1)}`;
    return `+${normalized[0]} ${normalized.slice(1, 4)} ${normalized.slice(4, 7)}-${normalized.slice(7, 9)}-${normalized.slice(9, 11)}`;
  }
  if (digits.length === 10) {
    return `+7 ${digits.slice(0, 3)} ${digits.slice(3, 6)}-${digits.slice(6, 8)}-${digits.slice(8, 10)}`;
  }
  return raw;
}

function formatCard(raw: string): string {
  const digits = String(raw || "").replace(/\D/g, "");
  if (!digits || digits.length < 12 || digits.length > 19 || digits.length !== String(raw || "").trim().length) {
    return raw;
  }
  return digits.match(/.{1,4}/g)?.join(" ") || raw;
}

function Row({ label, value, copyValue }: { label: string; value: string; copyValue?: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    const text = copyValue ?? value;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1300);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 1300);
    }
  };

  return (
    <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
      <div style={{ minWidth: 100, color: "var(--muted)", fontSize: 13, flex: "0 0 100%" }}>{label}</div>
      <div style={{ flex: "1 1 220px", minWidth: 0, background: "rgba(255,255,255,0.02)", padding: 10, borderRadius: 10, border: "1px solid var(--border)", overflowX: "auto", whiteSpace: "nowrap" }}>
        <div style={{ fontWeight: 700 }}>{value}</div>
      </div>
      <button className="btn ghost" onClick={copy} aria-label={`Copy ${label}`} style={{ flex: "0 0 auto" }}>
        {copied ? "Скопировано" : "Копировать"}
      </button>
    </div>
  );
}

export default function PaymentDetails({ amount, subtotal, discount }: { amount?: number | null; subtotal?: number | null; discount?: number | null }) {
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
  const rawPhone = req?.phone || "—";
  const rawCard = req?.card_number || "—";
  const bank = req?.bank_name || "—";
  const phone = useMemo(() => formatPhone(rawPhone), [rawPhone]);
  const card = useMemo(() => formatCard(rawCard), [rawCard]);
  const amountNum = Number(amount || 0);
  const subtotalNum = Number(subtotal || 0);
  const discountNum = Number(discount || 0);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 12 }}>
      <div style={{ fontWeight: 900, fontSize: 16, marginBottom: 6 }}>Реквизиты для оплаты</div>
      {amountNum > 0 ? (
        <div className="card" style={{ padding: 12 }}>
          <div className="small-muted">Сумма к оплате</div>
          <div style={{ marginTop: 4, fontSize: 24, fontWeight: 900 }}>
            {new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 }).format(amountNum)}
          </div>
          {discountNum > 0 ? (
            <div className="small-muted" style={{ marginTop: 6 }}>
              Со скидкой: -{new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 }).format(discountNum)}
              {subtotalNum > 0 ? ` от ${new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 }).format(subtotalNum)}` : ""}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="card" style={{ padding: 12 }}>
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 6 }}>Получатель</div>
          <div style={{ fontWeight: 800 }}>{fio}</div>
        </div>

        <Row label="Телефон (для оплаты / связь)" value={phone} copyValue={rawPhone} />
        <Row label="Номер карты" value={card} copyValue={rawCard} />
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
