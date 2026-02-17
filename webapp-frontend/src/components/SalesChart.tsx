import React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export type SalesPoint = {
  date: string; // ISO date or label
  amount: number;
};

type Props = {
  data: SalesPoint[];
  height?: number;
  selectedDate?: string | null;
  onSelect?: (p: SalesPoint) => void;
};

function formatMoney(n: number) {
  if (!isFinite(n)) return "0";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(n);
}

function formatLabel(label: any) {
  const s = String(label || "");
  // If ISO date, show DD.MM
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    const [y, m, d] = s.split("-");
    return `${d}.${m}`;
  }
  return s;
}

const Dot: React.FC<any> = (props) => {
  const { cx, cy, payload, onSelect, selectedDate } = props;
  if (cx == null || cy == null) return null;
  const isSel = selectedDate && payload?.date === selectedDate;
  const r = isSel ? 6 : 3;
  const handleClick = () => {
    if (onSelect && payload) onSelect({ date: payload.date, amount: Number(payload.amount || 0) });
  };
  return (
    <circle
      cx={cx}
      cy={cy}
      r={r}
      fill="var(--accent)"
      stroke="var(--text)"
      strokeWidth={1}
      style={{ cursor: "pointer" }}
      onClick={handleClick}
      onTouchEnd={handleClick}
    />
  );
};

export default function SalesChart({ data, height = 260, selectedDate = null, onSelect }: Props) {
  const normalized = (data || []).map((p) => ({
    date: p.date,
    amount: Number(p.amount || 0),
  }));

  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={normalized} margin={{ top: 10, right: 18, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
          <XAxis dataKey="date" tickFormatter={formatLabel} stroke="rgba(255,255,255,0.7)" />
          <YAxis tickFormatter={(v) => formatMoney(Number(v))} stroke="rgba(255,255,255,0.7)" />
          <Tooltip
            formatter={(value: any) => [formatMoney(Number(value)), "₽"]}
            labelFormatter={(label: any) => formatLabel(label)}
            contentStyle={{
              background: "rgba(17,17,20,0.94)",
              border: "1px solid rgba(255,255,255,0.10)",
              borderRadius: 12,
              boxShadow: "0 10px 28px rgba(0,0,0,0.45)",
            }}
            itemStyle={{ color: "#e9edf3" }}
            labelStyle={{ color: "rgba(233,237,243,0.72)", fontWeight: 700 }}
          />
          <Line
            type="monotone"
            dataKey="amount"
            stroke="var(--accent)"
            strokeWidth={2}
            dot={<Dot onSelect={onSelect} selectedDate={selectedDate} />}
            activeDot={{ r: 6, fill: "#ffffff", stroke: "var(--accent)", strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
