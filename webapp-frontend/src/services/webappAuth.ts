import { axiosInstance } from "./api";

export function isTelegramWebApp(): boolean {
  if (typeof window === "undefined") return false;
  const w: any = window;
  return !!(w.Telegram && w.Telegram.WebApp);
}

export function requireWebAppOrWarn(): boolean {
  const ok = isTelegramWebApp();
  if (!ok) console.warn("[WebApp] App opened outside Telegram WebApp");
  return ok;
}

export async function initWebAppAndAuth(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  const w: any = window;
  if (!w.Telegram || !w.Telegram.WebApp) {
    // Still allow auth via cached initData from URL parsing.
    // (Useful when the SDK isn't available for any reason.)
  }
  try { w.Telegram.WebApp.ready(); } catch {}
  let initData = w?.Telegram?.WebApp?.initData;
  if (!initData) {
    try { initData = sessionStorage.getItem("tg_init_data"); } catch {}
  }
  if (!initData) {
    try {
      const href = window.location?.href || "";
      const m = href.match(/[?#&](tgWebAppData|initData|init_data)=([^&#]+)/i);
      if (m && m[2]) initData = decodeURIComponent(m[2]);
    } catch {}
  }
  if (!initData) return false;
  try {
    const res = await axiosInstance.post("/api/auth/webapp_init", { init_data: initData });
    const data = res?.data ?? res;
    const token = data?.access_token || data?.token || data?.accessToken;
    if (token) {
      try { localStorage.setItem("access_token", token); } catch {}
      // /auth/webapp_init часто возвращает урезанного пользователя (без имени/username).
      // Поэтому сразу подтягиваем полный профиль через /auth/me и кешируем его.
      try {
        const meRes = await axiosInstance.get("/api/auth/me");
        const me = meRes?.data ?? meRes;
        try { localStorage.setItem("me", JSON.stringify(me)); } catch {}
      } catch {
        // fallback: хотя бы что-то, чтобы роль админа/менеджера не потерялась
        if (data.user) {
          try { localStorage.setItem("me", JSON.stringify({ ...data.user, _partial: true })); } catch {}
        }
      }
      return true;
    }
    return false;
  } catch (err) {
    console.error("[WebApp] auth failed", err);
    return false;
  }
}

export async function ensureWebAppAuth(): Promise<boolean> {
  const token = localStorage.getItem("access_token");
  if (token) return true;
  return await initWebAppAndAuth();
}

export function clearAuth() {
  try {
    localStorage.removeItem("access_token");
    localStorage.removeItem("me");
  } catch {}
}
