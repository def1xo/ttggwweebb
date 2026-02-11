import React from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "./App";
import { ThemeProvider } from "./contexts/ThemeContext";
import { ToastProvider } from "./contexts/ToastContext";
import { FavoritesProvider } from "./contexts/FavoritesContext";
import "./main.css";

// Telegram WebApp: call ready() as early as possible so initData is populated
// before the app starts firing API requests.
(function initTelegramWebApp() {
  try {
    const w: any = window as any;
    const tg = w?.Telegram?.WebApp;
    if (tg?.ready) tg.ready();
    if (tg?.expand) tg.expand();
    try {
      let initData = tg?.initData;
      // If SDK isn't available (or initData wasn't populated yet), Telegram may
      // still provide it in the URL as tgWebAppData.
      if (!initData) {
        const href = window.location?.href || "";
        const m = href.match(/[?#&](tgWebAppData|initData|init_data)=([^&#]+)/i);
        if (m && m[2]) initData = decodeURIComponent(m[2]);
      }
      if (typeof initData === "string" && initData.length > 0) {
        sessionStorage.setItem("tg_init_data", initData);
      }
    } catch {}
  } catch {}
})();


(function bindViewportHeightVar() {
  const apply = () => {
    try {
      const h = window.visualViewport?.height || window.innerHeight || 0;
      if (h > 0) {
        document.documentElement.style.setProperty("--vh", `${h * 0.01}px`);
      }
    } catch {}
  };

  apply();
  window.addEventListener("resize", apply, { passive: true });
  window.addEventListener("orientationchange", apply, { passive: true });
  try { window.visualViewport?.addEventListener("resize", apply, { passive: true } as any); } catch {}
})();

(function installGlobalErrorOverlay() {
  if (typeof window === "undefined") return;
  try {
    if ((window as any)?.Telegram?.WebApp) return;
  } catch {}
  // In production we don't show a full-screen debug overlay (Telegram users hate it).
  // Errors are still printed to console and reported to backend via /logs/client-error.
  try {
    const env: any = (import.meta as any)?.env;
    if (env?.PROD) return;
  } catch {}
  const showOverlay = (text: string) => {
    let el = document.getElementById("global-error-overlay");
    if (!el) {
      el = document.createElement("div");
      el.id = "global-error-overlay";
      Object.assign((el as HTMLElement).style, {
        position: "fixed",
        left: "0",
        top: "0",
        right: "0",
        bottom: "0",
        background: "#000000cc",
        color: "#fff",
        zIndex: "999999",
        padding: "18px",
        fontFamily: "monospace",
        whiteSpace: "pre-wrap",
        overflow: "auto"
      });
      try { document.body.appendChild(el); } catch {}
    }
    el.textContent = text;
    (el as HTMLElement).style.display = "block";
  };

  function safeStringify(obj: any) {
    try {
      if (obj instanceof Error) {
        return `${obj.name}: ${obj.message}\n${obj.stack || ""}`;
      }
      const seen = new WeakSet();
      return JSON.stringify(obj, function (_, value) {
        if (typeof value === "function") return value.toString();
        if (typeof value === "object" && value !== null) {
          if (seen.has(value)) return "[Circular]";
          seen.add(value);
        }
        return value;
      }, 2);
    } catch {
      try { return String(obj); } catch { return "Unable to stringify error"; }
    }
  }

  window.addEventListener("error", (e: ErrorEvent) => {
    try {
      const msg = `Error: ${e.message}\nSource: ${e.filename || "?"}:${e.lineno || "?"}:${e.colno || "?"}\n\nStack:\n${(e.error && (e.error as any).stack) || "no stack"}`;
      console.error(msg);
      showOverlay(msg);
    } catch (ex) {
      console.error("Overlay failed", ex);
    }
  });

  window.addEventListener("unhandledrejection", (ev: PromiseRejectionEvent) => {
    try {
      const reason = ev.reason;
      let text = "";
      if (!reason && reason !== 0) {
        text = "UnhandledRejection: <empty reason>";
      } else if (typeof reason === "string") {
        text = `UnhandledRejection: ${reason}`;
      } else if (reason instanceof Error) {
        text = `UnhandledRejection: ${reason.name}: ${reason.message}\n\n${reason.stack || ""}`;
      } else {
        text = `UnhandledRejection (object):\n${safeStringify(reason)}`;
      }
      console.error("UnhandledRejection captured:", reason);
      showOverlay(text);
      try { ev.preventDefault(); } catch {}
    } catch (ex) {
      console.error("Overlay failed on unhandledrejection", ex);
    }
  });
})();

const originalFetch = window.fetch.bind(window);
window.fetch = async function(input: any, init?: any) {
  // Auto-attach Telegram initData + JWT to *any* fetch call (some pages use fetch directly)
  let nextInit: any = init ? { ...init } : {};
  let nextInput: any = input;
  let initDataValue: string | null = null;
  try {
    const headers = new Headers((nextInit && nextInit.headers) || undefined);

    // JWT (if present)
    try {
      const urlStr = typeof input === "string" ? input : (input && input.url ? input.url : "");
      const isAdmin = /(^|\/)(api\/)?admin(\/|$)/.test(urlStr);
      const token = isAdmin
        ? (localStorage.getItem("admin_token") || null)
        : (
            localStorage.getItem("access_token") ||
            localStorage.getItem("jwt") ||
            localStorage.getItem("token") ||
            null
          );
      if (token && !headers.has("Authorization")) {
        headers.set("Authorization", `Bearer ${token}`);
      }
    } catch {}

    // Telegram initData
    try {
      const tg = (window as any)?.Telegram?.WebApp;
      const live = tg?.initData;
      if (typeof live === "string" && live.length > 0) {
        try { sessionStorage.setItem("tg_init_data", live); } catch {}
        initDataValue = live;
        if (!headers.has("X-Telegram-Init-Data")) headers.set("X-Telegram-Init-Data", live);
      } else {
        const saved = sessionStorage.getItem("tg_init_data");
        if (saved && saved.length > 0 && !headers.has("X-Telegram-Init-Data")) {
          initDataValue = saved;
          headers.set("X-Telegram-Init-Data", saved);
        }
      }
    } catch {}

    nextInit.headers = headers;
  } catch {}

  try {
    const resp = await originalFetch(nextInput, nextInit);
    if (!resp.ok) {
      const clone = resp.clone();
      let bodyText = "";
      try { bodyText = await clone.text(); } catch {}
      console.error("FETCH non-ok:", { url: input, status: resp.status, body: bodyText });
    }
    return resp;
  } catch (err) {
    console.error("FETCH failed:", { url: input, err });
    throw err;
  }
};


const rootEl = document.getElementById("root") || document.getElementById("app");
if (!rootEl) {
  const r = document.createElement("div");
  r.id = "root";
  document.body.appendChild(r);
}

const root = createRoot(document.getElementById("root") as HTMLElement);
root.render(
  <React.StrictMode>
    <ThemeProvider>
      <ToastProvider>
        <FavoritesProvider>
          <HashRouter>
            <App />
          </HashRouter>
        </FavoritesProvider>
      </ToastProvider>
    </ThemeProvider>
  </React.StrictMode>
);
