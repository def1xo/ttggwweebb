import React, { useState, useEffect } from "react";
import api from "../services/api";

const Checkout: React.FC = () => {
  const [cart, setCart] = useState<any[]>([]);
  const [fio, setFio] = useState("");
  const [deliveryType, setDeliveryType] = useState("cdek_pvz");
  const [deliveryAddress, setDeliveryAddress] = useState("");
  const [promoCode, setPromoCode] = useState("");
  const [screenshot, setScreenshot] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await api.axiosInstance.get("/cart/", { validateStatus: () => true });
        if (res && res.status >= 200 && res.data && res.data.items) {
          setCart(res.data.items);
          return;
        }
      } catch (e) {}
      const raw = localStorage.getItem("cart");
      setCart(raw ? JSON.parse(raw) : []);
    })();
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setScreenshot(e.target.files[0]);
    }
  };

  const submit = async () => {
    if (cart.length === 0) {
      setMessage("Корзина пуста");
      return;
    }
    if (!fio) {
      setMessage("Введите ФИО");
      return;
    }
    setLoading(true);
    try {
      const form = new FormData();
      form.append("fio", fio);
      form.append("delivery_type", deliveryType);
      form.append("delivery_address", deliveryAddress);
      if (promoCode) form.append("promo_code", promoCode);
      form.append("items", JSON.stringify(cart.map((c) => ({ variant_id: c.variant_id, quantity: c.quantity }))));
      if (screenshot) form.append("payment_screenshot", screenshot);
      const res = await api.axiosInstance.post("/api/orders", form, { headers: { "Content-Type": "multipart/form-data" } });
      if (res && res.data && res.data.order_id) {
        setMessage("Заказ создан. Номер: " + res.data.order_id);
        try {
          await api.axiosInstance.delete("/api/cart/clear");
        } catch (e) {}
        localStorage.removeItem("cart");
        setCart([]);
      } else {
        setMessage("Заказ создан");
      }
    } catch (err: any) {
      setMessage(err?.response?.data?.detail || String(err?.message || "Ошибка при создании заказа"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6 bg-white p-6 rounded-lg shadow-sm">
      <h1 className="text-2xl font-semibold tracking-tight">Оформление заказа</h1>

      <div className="border rounded p-4">
        <h2 className="text-lg font-medium mb-2">Товары</h2>
        {cart.length === 0 && <div className="text-sm text-gray-500">Ваша корзина пуста</div>}
        {cart.map((c: any) => (
          <div key={c.variant_id} className="flex justify-between py-2 border-b last:border-b-0">
            <div className="text-sm">{c.title || `Вариант ${c.variant_id}`}</div>
            <div className="text-sm font-medium">{c.quantity} × {c.price || "—"} ₽</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4">
        <label>
          <div className="text-xs text-gray-600 mb-1">ФИО</div>
          <input value={fio} onChange={(e) => setFio(e.target.value)} className="w-full p-3 border border-gray-200 rounded bg-white" />
        </label>

        <label>
          <div className="text-xs text-gray-600 mb-1">Тип доставки</div>
          <select value={deliveryType} onChange={(e) => setDeliveryType(e.target.value)} className="w-full p-3 border border-gray-200 rounded bg-white">
            <option value="cdek_pvz">ПВЗ СДЭК (пост. оплата)</option>
            <option value="ozon_pvz">ПВЗ Ozon</option>
            <option value="yandex">Яндекс.Доставка</option>
          </select>
        </label>

        <label>
          <div className="text-xs text-gray-600 mb-1">Адрес / ПВЗ</div>
          <input value={deliveryAddress} onChange={(e) => setDeliveryAddress(e.target.value)} placeholder="Введите адрес ПВЗ, доставка платная" className="w-full p-3 border border-gray-200 rounded bg-white" />
        </label>

        <label>
          <div className="text-xs text-gray-600 mb-1">Промокод (опционально)</div>
          <input value={promoCode} onChange={(e) => setPromoCode(e.target.value)} className="w-full p-3 border border-gray-200 rounded bg-white" />
        </label>

        <label>
          <div className="text-xs text-gray-600 mb-1">Скрин оплаты (загрузите после оплаты)</div>
          <input type="file" accept="image/*" onChange={handleFileChange} />
        </label>
      </div>

      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-600">Доставка оплачивается отдельно — укажите ПВЗ/адрес и ожидайте расчёта менеджера</div>
        <button onClick={submit} disabled={loading} className="px-5 py-3 bg-black text-white rounded-lg font-medium shadow-sm">
          {loading ? "Отправка..." : "Оформить заказ"}
        </button>
      </div>

      {message && <div className="mt-2 p-3 rounded border border-gray-100 text-sm bg-gray-50">{message}</div>}
    </div>
  );
};

export default Checkout;
