// src/api/api.ts
import axios from "axios";

// VITE_API_URL is sometimes configured as "/api" (when using same-origin nginx proxy)
// or as "http://host:8000/api". Our code below already prefixes requests with "/api/...",
// so strip a trailing "/api" here to avoid "/api/api/...".
const RAW_API_BASE_URL = (import.meta.env.VITE_API_URL ?? "") as string;
const API_BASE_URL = RAW_API_BASE_URL
  .replace(/\/$/, "")
  .replace(/\/api$/, "");

export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
});

function getTelegramInitData(): string | null {
  try {
    const tg = (window as any)?.Telegram?.WebApp;
    const live = tg?.initData;
    if (typeof live === "string" && live.length > 0) {
      try {
        sessionStorage.setItem("tg_init_data", live);
      } catch {}
      return live;
    }
  } catch {}
  // Fallback: Telegram may pass initData in the URL as tgWebAppData
  // (especially with hash routing). Extract it if present.
  try {
    const href = window.location?.href || "";
    const m = href.match(/[?#&](tgWebAppData|initData|init_data)=([^&#]+)/i);
    if (m && m[2]) {
      const decoded = decodeURIComponent(m[2]);
      if (decoded && decoded.length > 0) {
        try {
          sessionStorage.setItem("tg_init_data", decoded);
        } catch {}
        return decoded;
      }
    }
  } catch {}
  try {
    const saved = sessionStorage.getItem("tg_init_data");
    return saved && saved.length > 0 ? saved : null;
  } catch {
    return null;
  }
}

// Attach Telegram WebApp initData (and JWT if present) to every request.
api.interceptors.request.use((config) => {
  try {
    const token =
      localStorage.getItem("access_token") ||
      localStorage.getItem("jwt") ||
      localStorage.getItem("token") ||
      null;
    if (token) {
      config.headers = config.headers || {};
      (config.headers as any)["Authorization"] = `Bearer ${token}`;
    }
  } catch {}

  try {
    const initData = getTelegramInitData();
    if (initData) {
      config.headers = config.headers || {};
      (config.headers as any)["X-Telegram-Init-Data"] = initData;
    }
  } catch {}

  return config;
});

export interface ProductQuery {
  min_price?: number;
  max_price?: number;
  sort_by?: "newest" | "price_asc" | "price_desc" | "popularity";
  page?: number;
  per_page?: number;
  category_id?: number;
}

/* Products */
export const getProducts = async (params: ProductQuery) => {
  const { data } = await api.get("/api/products", { params });
  return data;
};

export const getProduct = async (productId: number) => {
  const { data } = await api.get(`/api/products/${productId}`);
  return data;
};

/* Categories */
export const getCategories = async () => {
  const { data } = await api.get("/api/categories");
  return data;
};

/* Cart / Orders */
export interface CreateOrderRequest {
  items: { product_id: number; qty: number; size?: string; color?: string }[];
  promo_code?: string | null;
  fio: string;
  delivery_pvz: string;
  payment_screenshot?: string | null;
  phone?: string | null;
}
export const createOrder = async (payload: CreateOrderRequest) => {
  const { data } = await api.post("/api/orders", payload);
  return data;
};

/* Promo code */
export const applyPromo = async (code: string, total: number) => {
  const { data } = await api.post("/api/promos/apply", { code, total });
  return data;
};

/* Manager */
export const getAssistantsBalances = async () => {
  const { data } = await api.get("/api/manager/assistants_balances");
  return data;
};

export const payAssistant = async (assistant_id: number, amount: number) => {
  const { data } = await api.post(`/api/manager/pay_assistant`, null, {
    params: { assistant_id, amount },
  });
  return data;
};

/* User */
export const getMyProfile = async () => {
  const { data } = await api.get("/api/me");
  return data;
};
