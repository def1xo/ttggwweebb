import axios, { AxiosRequestConfig } from "axios";
import { initWebAppAndAuth } from "./webappAuth";

function emitToast(message: string, type: "info" | "success" | "error" = "info") {
  try {
    window.dispatchEvent(new CustomEvent("tg-toast", { detail: { message, type } }));
  } catch {}
}

function formatApiErrorMessage(raw: any): string {
  if (raw == null) return "";
  if (typeof raw === "string") return raw;
  // FastAPI validation errors (422) обычно: {detail: [{loc,msg,type}, ...]}
  if (Array.isArray(raw)) {
    try {
      return raw
        .map((e) => {
          if (!e) return "";
          const loc = Array.isArray(e.loc) ? e.loc.join(".") : "";
          const msg = e.msg || e.message || "";
          const s = [loc, msg].filter(Boolean).join(": ");
          return s || JSON.stringify(e);
        })
        .filter(Boolean)
        .join("; ");
    } catch {
      return JSON.stringify(raw);
    }
  }
  try {
    return JSON.stringify(raw);
  } catch {
    return String(raw);
  }
}

function isAdminUrl(rawUrl: string): boolean {
  const url = (rawUrl || "").toString();
  return /\/admin(\/|$)/.test(url) || /\/api\/admin(\/|$)/.test(url) || /\/v1\/admin(\/|$)/.test(url);
}

function isAdminRequest(config?: AxiosRequestConfig): boolean {
  try {
    return isAdminUrl(String(config?.url || ""));
  } catch {
    return false;
  }
}

// VITE_BACKEND_URL/VITE_API_URL may be set to "/api" (nginx proxy) or ".../api".
// The code below already prefixes endpoints with "/api/...", so strip a trailing
// "/api" to avoid "/api/api/...".
const API_BASE_URL = (
  (import.meta as any).env?.VITE_BACKEND_URL ||
  (import.meta as any).env?.VITE_API_URL ||
  ""
)
  .replace(/\/$/, "")
  .replace(/\/api$/, "");

export const axiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20000,
  withCredentials: false,
  headers: {
    Accept: "application/json",
  },
});

function getTelegramInitData(): string | null {
  try {
    const tg = (window as any)?.Telegram?.WebApp;
    const live = tg?.initData;
    if (typeof live === "string" && live.length > 0) {
      try { sessionStorage.setItem("tg_init_data", live); } catch {}
      return live;
    }
  } catch {}
  // Fallback: Telegram may pass initData in the URL as tgWebAppData (especially
  // when using hash routing). If the SDK isn't available yet, extract it here.
  try {
    const href = window.location?.href || "";
    const m = href.match(/[?#&](tgWebAppData|initData|init_data)=([^&#]+)/i);
    if (m && m[2]) {
      const decoded = decodeURIComponent(m[2]);
      if (decoded && decoded.length > 0) {
        try { sessionStorage.setItem("tg_init_data", decoded); } catch {}
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


// Attach Telegram WebApp initData (and JWT if present) to axios requests.
// We prefer headers to avoid leaking initData in access logs.
// If a request gets 401 (missing auth), the response interceptor will attempt webapp_init.
function attachTelegramAuth(config: any) {
  try {
    const url = String(config?.url || "");
    const isAdmin = isAdminRequest(config);

    // Skip Telegram initData on admin endpoints and noisy endpoints.
    const skipInitData = isAdmin || /\/health(\?|$)/.test(url) || /\/logs\/client-error/.test(url);

    if (!skipInitData) {
      const initData = getTelegramInitData();
      if (initData) {
        config.headers = config.headers || {};
        config.headers["X-Telegram-Init-Data"] = initData;
      }
    }
  } catch {}

  // Attach the correct token:
  // - admin routes use `admin_token` (password login)
  // - regular routes use Telegram `access_token` (or legacy keys)
  try {
    const isAdmin = isAdminRequest(config);
    const token = isAdmin
      ? (localStorage.getItem("admin_token") || null)
      : (
          localStorage.getItem("access_token") ||
          localStorage.getItem("jwt") ||
          localStorage.getItem("token") ||
          null
        );

    if (token) {
      config.headers = config.headers || {};
      // don't override caller-provided Authorization
      if (!config.headers["Authorization"] && !config.headers.Authorization) {
        config.headers["Authorization"] = `Bearer ${token}`;
      }
    }
  } catch {}

  return config;
}

axiosInstance.interceptors.request.use((config: AxiosRequestConfig) => attachTelegramAuth(config));
axios.interceptors.request.use((config) => attachTelegramAuth(config));

export async function reportClientError(payload: any) {
  try {
    await axios.post(`${API_BASE_URL}/api/logs/client-error`, payload, { timeout: 5000 });
    return true;
  } catch (e) {
    try {
      await axios.post(`/api/logs/client-error`, payload, { timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  }
}

axiosInstance.interceptors.response.use(
  (response) => response,
  async (error) => {
    try {
      const originalRequest = error.config;
      if (!originalRequest || originalRequest._retry) {
        const info = {
          message: error?.message,
          status: error?.response?.status,
          url: error?.config?.url,
          method: error?.config?.method,
          responseData: error?.response?.data,
          headers: error?.response?.headers,
          phase: "no-retry",
        };
        try { await reportClientError(info); } catch {}
        console.error("AXIOS ERROR NO-RETRY:", info);
        return Promise.reject(error);
      }
      const status = error?.response?.status;
      if (status === 401) {
        originalRequest._retry = true;
        const adminReq = isAdminRequest(originalRequest);

        // Admin endpoints must rely on the admin token (password login).
        // Don't auto-retry them via Telegram initData, otherwise you'll get
        // random re-prompts / loops.
        if (adminReq) {
          try { localStorage.removeItem("admin_token"); } catch {}
          return Promise.reject(error);
        }

        // Regular endpoints: try Telegram WebApp auth once and retry.
        const ok = await initWebAppAndAuth();
        const token =
          localStorage.getItem("access_token") ||
          localStorage.getItem("jwt") ||
          localStorage.getItem("token") ||
          null;
        if (ok && token) {
          originalRequest.headers = originalRequest.headers || {};
          originalRequest.headers["Authorization"] = `Bearer ${token}`;
          return axiosInstance.request(originalRequest);
        }
      }

      // Friendly UX: show a short toast for common network/auth errors.
      if (status === 401) {
        emitToast("Нужна авторизация. Перезайдите в WebApp.", "error");
      } else if (status === 403) {
        emitToast("Недостаточно прав для этого действия.", "error");
      } else if (status >= 500) {
        emitToast("Сервер временно недоступен. Попробуйте позже.", "error");
      } else if (!status) {
        emitToast("Нет соединения с сервером.", "error");
      }
      const info = {
        message: error?.message,
        status: error?.response?.status,
        url: error?.config?.url,
        method: error?.config?.method,
        responseData: error?.response?.data,
        headers: error?.response?.headers,
        phase: "interceptor",
      };
      try { await reportClientError(info); } catch {}
      console.error("AXIOS ERROR:", info);
      // show user-friendly toast
      // FastAPI может вернуть detail как объект/массив (422), чтобы не видеть "[object Object]" — красиво форматируем
      const raw = (error?.response?.data?.detail ?? error?.response?.data?.message ?? error?.response?.data) as any;
      const serverMsg = formatApiErrorMessage(raw);

      const msg = serverMsg || (status === 0 ? "Сеть недоступна" : "Ошибка запроса");
      emitToast(msg, "error");
    } catch (e) {
      console.error("AXIOS INTERCEPTOR FAILURE", e);
    }
    return Promise.reject(error);
  }
);

function handleAxiosError(err: any): never {
  if (err?.response) {
    const data = err.response.data;
    const raw = data?.detail ?? data?.message ?? data;
    const msg = formatApiErrorMessage(raw) || "Ошибка";
    throw new Error(msg);
  }
  throw err;
}

async function tryCandidates<T = any>(candidates: string[], config: AxiosRequestConfig = {}): Promise<T> {
  for (const cand of candidates) {
    try {
      const isAbsolute = /^https?:\/\//i.test(cand);
      const client = axiosInstance; // always use axiosInstance so interceptors attach Telegram initData/JWT
      const url = cand;
      const method = (config.method || "get").toLowerCase();
      let res;
      if (method === "get" || method === "delete") {
        res = await client.request({ url, method, params: config.params, headers: config.headers, timeout: config.timeout ?? 20000 });
      } else {
        res = await client.request({ url, method, data: config.data, params: config.params, headers: config.headers, timeout: config.timeout ?? 20000 });
      }
      if (res && res.status >= 200 && res.status < 300) {
        return res.data;
      }
    } catch (err: any) {
      const status = err?.response?.status;
      if (status === 404 || status === 400 || !err?.response) {
        continue;
      }
      if (candidates.indexOf(cand) < candidates.length - 1) {
        continue;
      }
      return Promise.reject(err);
    }
  }
  throw new Error("No backend endpoint responded (tried multiple candidates).");
}

const CANDIDATES = {
  news: [
    `${API_BASE_URL}/api/news`,
    `${API_BASE_URL}/api/v1/news`,
    `${API_BASE_URL}/news`,
    `/api/news`,
    `/news`,
  ],
  products: [
    `${API_BASE_URL}/api/products`,
    `${API_BASE_URL}/api/v1/products`,
    `${API_BASE_URL}/products`,
    `/api/products`,
    `/products`,
  ],
  recommendations: [
    `${API_BASE_URL}/api/recommendations`,
    `${API_BASE_URL}/api/v1/recommendations`,
    `${API_BASE_URL}/recommendations`,
    `/api/recommendations`,
    `/recommendations`,
  ],
  me: [
    `${API_BASE_URL}/api/auth/me`,
    `${API_BASE_URL}/api/v1/auth/me`,
    `${API_BASE_URL}/auth/me`,
    `/api/auth/me`,
    `/auth/me`,
  ],
  cart: [
    `${API_BASE_URL}/api/cart`,
    `${API_BASE_URL}/api/v1/cart`,
    `${API_BASE_URL}/cart`,
    `/api/cart`,
    `/cart`,
  ],
  favorites_ids: [
    `${API_BASE_URL}/api/favorites/ids`,
    `${API_BASE_URL}/api/v1/favorites/ids`,
    `${API_BASE_URL}/favorites/ids`,
    `/api/favorites/ids`,
    `/favorites/ids`,
  ],
  favorites: [
    `${API_BASE_URL}/api/favorites`,
    `${API_BASE_URL}/api/v1/favorites`,
    `${API_BASE_URL}/favorites`,
    `/api/favorites`,
    `/favorites`,
  ],
  payment_requisites: [
    `${API_BASE_URL}/api/payment/requisites`,
    `${API_BASE_URL}/api/v1/payment/requisites`,
    `${API_BASE_URL}/payment/requisites`,
    `/api/payment/requisites`,
    `/payment/requisites`,
  ],
};

// -------- Cart (server-side) --------

export async function getCart() {
  try {
    return await tryCandidates(CANDIDATES.cart, { method: "get" });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function addCartItem(variant_id: number, quantity: number = 1) {
  try {
    const candidates = [
      `${API_BASE_URL}/api/cart/items/add`,
      `${API_BASE_URL}/api/v1/cart/items/add`,
      `/api/cart/items/add`,
      `/cart/items/add`,
    ];
    return await tryCandidates(candidates, { method: "post", data: { variant_id, quantity } });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function setCartItem(variant_id: number, quantity: number) {
  try {
    const candidates = [
      `${API_BASE_URL}/api/cart/items`,
      `${API_BASE_URL}/api/v1/cart/items`,
      `/api/cart/items`,
      `/cart/items`,
    ];
    return await tryCandidates(candidates, { method: "post", data: { variant_id, quantity } });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function deleteCartItem(variant_id: number) {
  try {
    const candidates = [
      `${API_BASE_URL}/api/cart/items/${variant_id}`,
      `${API_BASE_URL}/api/v1/cart/items/${variant_id}`,
      `/api/cart/items/${variant_id}`,
      `/cart/items/${variant_id}`,
    ];
    return await tryCandidates(candidates, { method: "delete" });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function clearCart() {
  try {
    const candidates = [
      `${API_BASE_URL}/api/cart/clear`,
      `${API_BASE_URL}/api/v1/cart/clear`,
      `/api/cart/clear`,
      `/cart/clear`,
    ];
    // backend uses DELETE /cart/clear
    return await tryCandidates(candidates, { method: "delete" });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function applyCartPromo(code: string) {
  try {
    const candidates = [
      `${API_BASE_URL}/api/cart/promo`,
      `${API_BASE_URL}/api/v1/cart/promo`,
      `/api/cart/promo`,
      `/cart/promo`,
    ];
    return await tryCandidates(candidates, { method: "post", data: { code } });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function removeCartPromo() {
  try {
    const candidates = [
      `${API_BASE_URL}/api/cart/promo`,
      `${API_BASE_URL}/api/v1/cart/promo`,
      `/api/cart/promo`,
      `/cart/promo`,
    ];
    return await tryCandidates(candidates, { method: "delete" });
  } catch (e) {
    return handleAxiosError(e);
  }
}

// -------- Payment requisites + proof upload --------

export async function getPaymentRequisites() {
  try {
    return await tryCandidates(CANDIDATES.payment_requisites, { method: "get" });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function uploadPaymentProof(orderId: number | string, file: File) {
  try {
    const fd = new FormData();
    fd.append("file", file);
    const candidates = [
      `${API_BASE_URL}/api/orders/${orderId}/payment-proof`,
      `${API_BASE_URL}/api/v1/orders/${orderId}/payment-proof`,
      `/api/orders/${orderId}/payment-proof`,
      `/orders/${orderId}/payment-proof`,
    ];
    return await tryCandidates(candidates, { method: "post", data: fd, headers: { "Content-Type": "multipart/form-data" } });
  } catch (e) {
    return handleAxiosError(e);
  }
}

// -------- Favorites --------

export async function getFavoriteIds() {
  try {
    return await tryCandidates(CANDIDATES.favorites_ids, { method: "get" });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getFavorites() {
  try {
    return await tryCandidates(CANDIDATES.favorites, { method: "get" });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function addFavorite(productId: number | string) {
  try {
    const candidates = [
      `${API_BASE_URL}/api/favorites/${productId}`,
      `${API_BASE_URL}/api/v1/favorites/${productId}`,
      `${API_BASE_URL}/favorites/${productId}`,
      `/api/favorites/${productId}`,
      `/favorites/${productId}`,
    ];
    return await tryCandidates(candidates, { method: "post" });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function removeFavorite(productId: number | string) {
  try {
    const candidates = [
      `${API_BASE_URL}/api/favorites/${productId}`,
      `${API_BASE_URL}/api/v1/favorites/${productId}`,
      `${API_BASE_URL}/favorites/${productId}`,
      `/api/favorites/${productId}`,
      `/favorites/${productId}`,
    ];
    return await tryCandidates(candidates, { method: "delete" });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getProducts(params?: Record<string, any>) {
  try {
    return await tryCandidates(CANDIDATES.products, { method: "get", params });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getProduct(id: number | string) {
  try {
    const candidates = [
      `${API_BASE_URL}/api/products/${id}`,
      `${API_BASE_URL}/api/v1/products/${id}`,
      `/api/products/${id}`,
      `/products/${id}`,
    ];
    return await tryCandidates(candidates);
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getCategories(params?: Record<string, any>) {
  try {
    const candidates = [
      `${API_BASE_URL}/api/categories`,
      `${API_BASE_URL}/api/v1/categories`,
      `/api/categories`,
      `/categories`,
    ];
    return await tryCandidates(candidates, { method: "get", params });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getLatestNews(limit = 5) {
  try {
    const candidates = CANDIDATES.news;
    return await tryCandidates(candidates, { method: "get", params: { limit } });
  } catch (e: any) {
    console.warn("getLatestNews failed, returning empty list", e?.message || e);
    return [];
  }
}

export async function createOrder(payload: any) {
  try {
    const hasFile =
      payload &&
      (payload.payment_screenshot instanceof File ||
        payload.payment_screenshot instanceof Blob ||
        (payload.files && Array.isArray(payload.files) && payload.files.length > 0));
    if (hasFile) {
      const form = new FormData();
      if (payload.fio) form.append("fio", payload.fio);
      if (payload.delivery_type) form.append("delivery_type", payload.delivery_type);
      if (payload.delivery_address) form.append("delivery_address", payload.delivery_address);
      if (payload.promo_code) form.append("promo_code", payload.promo_code);
      if (payload.phone) form.append("phone", payload.phone);
      if (payload.note) form.append("note", payload.note);
      if (payload.items) form.append("items", JSON.stringify(payload.items));
      if (payload.payment_screenshot instanceof File || payload.payment_screenshot instanceof Blob) {
        form.append("payment_screenshot", payload.payment_screenshot);
      }
      if (payload.files && Array.isArray(payload.files)) {
        payload.files.forEach((f: File, idx: number) => form.append(`file_${idx}`, f));
      }
      const candidates = [
        `${API_BASE_URL}/api/orders`,
        `${API_BASE_URL}/api/v1/orders`,
        `/api/orders`,
        `/orders`,
      ];
      return await tryCandidates(candidates, { method: "post", data: form, headers: { "Content-Type": "multipart/form-data" } });
    } else {
      const body = {
        fio: payload.fio,
        delivery_type: payload.delivery_type,
        delivery_address: payload.delivery_address,
        items: payload.items,
        promo_code: payload.promo_code,
        phone: payload.phone,
        note: payload.note,
      };
      const candidates = [
        `${API_BASE_URL}/api/orders`,
        `${API_BASE_URL}/api/v1/orders`,
        `/api/orders`,
        `/orders`,
      ];
      return await tryCandidates(candidates, { method: "post", data: body });
    }
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function confirmOrderPayment(orderId: number) {
  try {
    const endpoints = [
      `/api/orders/${orderId}/confirm_payment`,
      `/orders/${orderId}/confirm_payment`,
      `/api/admin/orders/${orderId}/confirm`,
      `/admin/orders/${orderId}/confirm`,
    ];
    return await tryCandidates(endpoints, { method: "post" });
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function applyPromo(code: string, total?: number) {
  try {
    const payload: any = { code };
    if (typeof total === "number" && Number.isFinite(total)) payload.total = total;

    const candidates = [
      `${API_BASE_URL}/api/promo/apply`,
      `${API_BASE_URL}/api/promos/apply`,
      `${API_BASE_URL}/api/v1/promo/apply`,
      `${API_BASE_URL}/api/v1/promos/apply`,
      `/api/promo/apply`,
      `/api/promos/apply`,
      `/promo/apply`,
      `/promos/apply`,
      `/api/v1/promo/apply`,
      `/api/v1/promos/apply`,
      `/v1/promo/apply`,
      `/v1/promos/apply`,
    ];

    const data = await tryCandidates(candidates, { method: "post", data: payload });
    return data;
  } catch (e: any) {
    throw handleAxiosError(e);
  }
}

// Basic memoization to avoid spamming /auth/me from multiple components
let _meCache: any = null;
let _meCacheAt = 0;
let _meInflight: Promise<any> | null = null;
const ME_CACHE_TTL_MS = 60_000;

export async function getMyProfile(forceRefresh: boolean = false) {
  const now = Date.now();

  if (!forceRefresh) {
    if (_meCache && now - _meCacheAt < ME_CACHE_TTL_MS) return _meCache;

    try {
      const raw = localStorage.getItem("me");
      if (raw) {
        const parsed = JSON.parse(raw);
        // Иногда в localStorage попадает "неполный" user из /auth/webapp_init (без имени/юзернейма).
        // Тогда не кешируем его как итоговый профиль — запрашиваем /auth/me.
        const isPartial =
          parsed &&
          (parsed.telegram_id || parsed.id) &&
          !parsed.first_name &&
          !parsed.last_name &&
          !parsed.username &&
          !parsed.name;
        if (!isPartial) {
          _meCache = parsed;
          _meCacheAt = now;
          return parsed;
        }
      }
    } catch {}

    if (_meInflight) return _meInflight;
  }

  const candidates = [
    `${API_BASE_URL}/api/auth/me`,
    `${API_BASE_URL}/api/v1/auth/me`,
    `/api/auth/me`,
    `/api/v1/auth/me`,
    `${API_BASE_URL}/auth/me`,
    `${API_BASE_URL}/v1/auth/me`,
    `/auth/me`,
    `/v1/auth/me`,
  ];

  _meInflight = tryCandidates(candidates, { method: "get" }, "auth/me")
    .then((data) => {
      _meCache = data;
      _meCacheAt = Date.now();
      try { localStorage.setItem("me", JSON.stringify(data)); } catch {}
      return data;
    })
    .finally(() => {
      _meInflight = null;
    });

  return _meInflight;
}


export async function getAssistantsBalances() {
  try {
    const res = await axiosInstance.get("/api/manager/assistants");
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function payAssistant(payload: any) {
  try {
    const res = await axiosInstance.post("/api/assistants/pay", payload);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getManagerAssistants() {
  try {
    const res = await axiosInstance.get("/api/manager/assistants");
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function addManagerAssistant(payload: { user_id: number; percent: number }) {
  try {
    const res = await axiosInstance.post("/api/manager/assistants", payload);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function patchManagerAssistant(id: number, payload: { percent: number }) {
  try {
    const res = await axiosInstance.patch(`/api/manager/assistants/${id}`, payload);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getManagerCommissions(page = 1, per_page = 50) {
  try {
    const res = await axiosInstance.get(`/api/manager/commissions`, { params: { page, per_page } });
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getManagerWithdraws() {
  try {
    const res = await axiosInstance.get("/api/manager/withdraws");
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function requestManagerWithdraw(payload: { amount: number; target_details: string }) {
  try {
    const body = new URLSearchParams();
    body.append("amount", String(payload.amount));
    body.append("target_details", payload.target_details);
    const res = await axiosInstance.post("/api/manager/request_withdrawal", body);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getAssistantDashboard() {
  try {
    const res = await axiosInstance.get("/api/assistant/dashboard");
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function assistantRequestWithdraw(amount: number, target_details: string) {
  try {
    const body = new URLSearchParams();
    body.append("amount", String(amount));
    body.append("target_details", target_details);
    const res = await axiosInstance.post("/api/assistant/request_withdraw", body);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}



export async function adminLogin(user_id: number, password: string) {
  try {
    const res = await axiosInstance.post("/api/admin/login", { user_id, password });
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getAdminStats(range: "week" | "month" | "all" = "month") {
  try {
    const res = await axiosInstance.get("/api/admin/stats", { params: { range } });
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function downloadAdminSalesXlsx(scope: "month" | "week" | "all" = "month") {
  try {
    const res = await axiosInstance.get("/api/admin/export/sales.xlsx", {
      params: { scope },
      responseType: "blob",
    });
    return res;
  } catch (e) {
    return handleAxiosError(e);
  }
}
export async function getAdminOrders(params?: Record<string, any>) {
  try {
    const res = await axiosInstance.get("/api/admin/orders", { params });
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

// -------- Admin: payment settings --------

export async function getAdminPaymentSettings() {
  try {
    const res = await axiosInstance.get("/api/admin/payment-settings");
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function patchAdminPaymentSettings(payload: {
  recipient_name?: string | null;
  phone?: string | null;
  card_number?: string | null;
  bank_name?: string | null;
  note?: string | null;
}) {
  try {
    const res = await axiosInstance.patch("/api/admin/payment-settings", payload);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

// -------- Admin: special promos --------

export async function getAdminPromos(params?: Record<string, any>) {
  try {
    const res = await axiosInstance.get("/api/admin/promos", { params });
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function createAdminPromo(payload: {
  code: string;
  value: number;
  currency?: string;
  expires_at?: string | null;
  usage_limit?: number | null;
}) {
  try {
    const res = await axiosInstance.post("/api/admin/promos", payload);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function patchAdminPromo(id: number, payload: any) {
  try {
    const res = await axiosInstance.patch(`/api/admin/promos/${id}`, payload);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function deleteAdminPromo(id: number) {
  try {
    const res = await axiosInstance.delete(`/api/admin/promos/${id}`);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getAdminWithdraws() {
  try {
    const res = await axiosInstance.get("/api/admin/withdraws");
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function approveWithdraw(withdrawId: number, approve = true) {
  try {
    const res = await axiosInstance.post(`/api/admin/approve_withdrawal/${withdrawId}`, { approve });
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}


export async function getAdminManagers() {
  try {
    const res = await axiosInstance.get("/api/admin/managers");
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function addAdminManager(payload: { user_id?: number; telegram_id?: number }) {
  const uid = Number(payload?.user_id ?? payload?.telegram_id);
  if (!Number.isFinite(uid) || uid <= 0) {
    return { detail: "Некорректный user_id" };
  }

  try {
    // primary payload expected by most backends
    const res = await axiosInstance.post("/api/admin/managers", { user_id: uid });
    return res.data;
  } catch (e: any) {
    const status = e?.response?.status;
    // fallback for backends that expect telegram_id instead of user_id
    if (status === 400 || status === 404 || status === 422) {
      try {
        const res = await axiosInstance.post("/api/admin/managers", { telegram_id: uid });
        return res.data;
      } catch (e2) {
        return handleAxiosError(e2);
      }
    }
    return handleAxiosError(e);
  }
}

export async function patchAdminManager(id: number, payload: { role?: string; balance?: number }) {
  try {
    const res = await axiosInstance.patch(`/api/admin/managers/${id}`, payload);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function deleteAdminManager(id: number) {
  try {
    const res = await axiosInstance.delete(`/api/admin/managers/${id}`);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function getAdminProducts() {
  try {
    const res = await axiosInstance.get("/api/admin/products");
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function createProduct(payload: any) {
  try {
    const hasFile = payload?.image instanceof File || (payload?.images && Array.isArray(payload.images));
    if (hasFile) {
      const form = new FormData();
      form.append("title", payload.title || "");
      form.append("description", payload.description || "");
      form.append("base_price", String(payload.base_price ?? payload.price ?? 0));
      if (payload.category_id) form.append("category_id", String(payload.category_id));
      if (payload.sizes) form.append("sizes", String(payload.sizes));
      if (payload.color) form.append("color", String(payload.color));
      if (payload.image instanceof File) form.append("images", payload.image);
      if (payload.images && Array.isArray(payload.images)) payload.images.forEach((f: File) => form.append("images", f));
      const res = await axiosInstance.post("/api/admin/products", form, { headers: { "Content-Type": "multipart/form-data" } });
      return res.data;
    } else {
      const res = await axiosInstance.post("/api/admin/products", payload);
      return res.data;
    }
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function updateProduct(id: number, payload: any) {
  try {
    const hasFile = payload?.image instanceof File || (payload?.images && Array.isArray(payload.images));
    if (hasFile) {
      const form = new FormData();
      if (payload.title != null) form.append("title", payload.title || "");
      if (payload.description != null) form.append("description", payload.description || "");
      if (payload.base_price != null || payload.price != null) form.append("base_price", String(payload.base_price ?? payload.price ?? 0));
      if (payload.category_id) form.append("category_id", String(payload.category_id));
      if (payload.visible != null) form.append("visible", payload.visible ? "true" : "false");
      if (payload.sizes) form.append("sizes", String(payload.sizes));
      if (payload.color) form.append("color", String(payload.color));
      if (payload.image instanceof File) form.append("images", payload.image);
      if (payload.images && Array.isArray(payload.images)) payload.images.forEach((f: File) => form.append("images", f));
      const res = await axiosInstance.patch(`/api/admin/products/${id}`, form, { headers: { "Content-Type": "multipart/form-data" } });
      return res.data;
    }
    const res = await axiosInstance.patch(`/api/admin/products/${id}`, payload);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function deleteProduct(id: number) {
  try {
    const res = await axiosInstance.delete(`/api/admin/products/${id}`);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function createCategory(payload: { name: string }) {
  try {
    const body: any = { name: payload?.name || "" };
    if ((payload as any)?.slug) body.slug = String((payload as any).slug);
    const res = await axiosInstance.post("/api/admin/categories", body);
    return res.data;
  } catch (e) {
    const status = (e as any)?.response?.status;
    // Some backends (e.g. FastAPI) validate this endpoint as form-data and respond 422 for JSON.
    if (status === 415 || status === 422) {
      try {
        const form = new FormData();
        form.append("name", payload?.name || "");
        if ((payload as any)?.slug) form.append("slug", String((payload as any).slug));
        const res = await axiosInstance.post("/api/admin/categories", form, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        return res.data;
      } catch (retryErr) {
        return handleAxiosError(retryErr);
      }
    }
    return handleAxiosError(e);
  }
}

export async function getAdminCategories() {
  try {
    const res = await axiosInstance.get("/api/admin/categories");
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}

export async function createAdminCategory(payload: { name: string; slug?: string }) {
  return createCategory(payload);
}

export async function deleteAdminCategory(id: number) {
  return deleteCategory(id);
}

export async function getRecommendations(limitRecent = 10, resultCount = 4) {
  try {
    const candidates = CANDIDATES.recommendations.map((u) => `${u}?limit_recent=${limitRecent}&result_count=${resultCount}`);
    return await tryCandidates(candidates, { method: "get" });
  } catch (err) {
    return handleAxiosError(err);
  }
}

export async function deleteCategory(id: number) {
  try {
    const res = await axiosInstance.delete(`/api/admin/categories/${id}`);
    return res.data;
  } catch (e) {
    return handleAxiosError(e);
  }
}



const api: any = axiosInstance;
api.getProducts = getProducts;
api.getProduct = getProduct;
api.getCategories = getCategories;
api.getLatestNews = getLatestNews;
api.createOrder = createOrder;
api.getCart = getCart;
api.addCartItem = addCartItem;
api.setCartItem = setCartItem;
api.deleteCartItem = deleteCartItem;
api.clearCart = clearCart;
api.applyCartPromo = applyCartPromo;
api.removeCartPromo = removeCartPromo;
api.getPaymentRequisites = getPaymentRequisites;
api.uploadPaymentProof = uploadPaymentProof;
api.getFavoriteIds = getFavoriteIds;
api.getFavorites = getFavorites;
api.addFavorite = addFavorite;
api.removeFavorite = removeFavorite;
api.confirmOrderPayment = confirmOrderPayment;
api.applyPromo = applyPromo;
api.getMyProfile = getMyProfile;
api.getAssistantsBalances = getAssistantsBalances;
api.payAssistant = payAssistant;
api.getManagerAssistants = getManagerAssistants;
api.addManagerAssistant = addManagerAssistant;
api.patchManagerAssistant = patchManagerAssistant;
api.getManagerCommissions = getManagerCommissions;
api.getManagerWithdraws = getManagerWithdraws;
api.requestManagerWithdraw = requestManagerWithdraw;
api.getAssistantDashboard = getAssistantDashboard;
api.assistantRequestWithdraw = assistantRequestWithdraw;
api.getAdminOrders = getAdminOrders;
api.getAdminManagers = getAdminManagers;
api.addAdminManager = addAdminManager;
api.patchAdminManager = patchAdminManager;
api.deleteAdminManager = deleteAdminManager;
api.getAdminCategories = getAdminCategories;
api.createAdminCategory = createAdminCategory;
api.deleteAdminCategory = deleteAdminCategory;
api.adminLogin = adminLogin;
api.getAdminStats = getAdminStats;
api.downloadAdminSalesXlsx = downloadAdminSalesXlsx;
api.getAdminWithdraws = getAdminWithdraws;
api.approveWithdraw = approveWithdraw;
api.getAdminPaymentSettings = getAdminPaymentSettings;
api.patchAdminPaymentSettings = patchAdminPaymentSettings;
api.getAdminPromos = getAdminPromos;
api.createAdminPromo = createAdminPromo;
api.patchAdminPromo = patchAdminPromo;
api.deleteAdminPromo = deleteAdminPromo;
api.getAdminProducts = getAdminProducts;
api.createProduct = createProduct;
api.updateProduct = updateProduct;
api.deleteProduct = deleteProduct;
api.createCategory = createCategory;
api.deleteCategory = deleteCategory;
api.getRecommendations = getRecommendations;
api.reportClientError = reportClientError;

export default api;
