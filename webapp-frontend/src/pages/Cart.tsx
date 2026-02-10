import React, { useEffect, useState } from "react";

type CartItem = {
  variant_id: number;
  quantity: number;
  title?: string;
  price?: number;
  image?: string;
};

export default function Cart() {
  const [items, setItems] = useState<CartItem[]>([]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("cart");
      if (raw) setItems(JSON.parse(raw));
    } catch {
      setItems([]);
    }
  }, []);

  const updateQty = (idx: number, qty: number) => {
    const copy = [...items];
    copy[idx].quantity = Math.max(1, qty);
    setItems(copy);
    localStorage.setItem("cart", JSON.stringify(copy));
  };

  const removeItem = (idx: number) => {
    const copy = [...items];
    copy.splice(idx, 1);
    setItems(copy);
    localStorage.setItem("cart", JSON.stringify(copy));
  };

  const total = items.reduce((s, it) => s + (Number(it.price || 0) * it.quantity), 0);

  return (
    <div className="p-4">
      <h2 className="text-xl font-bold">Корзина</h2>
      <div className="mt-4 space-y-2">
        {items.length === 0 && <div>Корзина пуста</div>}
        {items.map((it, idx) => (
          <div key={idx} className="p-2 border rounded flex items-center gap-2">
            <div style={{ width: 64, height: 64, background: "#f3f3f3" }}>
              {it.image ? <img src={it.image} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : null}
            </div>
            <div className="flex-1">
              <div className="font-semibold">{it.title}</div>
              <div className="text-sm">{it.price} ₽</div>
            </div>
            <div className="flex items-center gap-2">
              <input type="number" className="border p-1 w-20" value={it.quantity} onChange={(e) => updateQty(idx, Number(e.target.value))} />
              <button className="px-2 py-1 border rounded" onClick={() => removeItem(idx)}>Удалить</button>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4">
        <div className="font-semibold">Итого: {total.toFixed(2)} ₽</div>
        <div className="mt-2">
          <a href="#/checkout" className="px-3 py-2 bg-green-600 text-white rounded inline-block">Оформить</a>
        </div>
      </div>
    </div>
  );
}
