import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

type ToastType = "info" | "success" | "error";

export type ToastItem = {
  id: string;
  type: ToastType;
  message: string;
};

const ToastContext = createContext<{ notify: (message: string, type?: ToastType) => void }>({
  notify: () => {},
});

function genId() {
  return `${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

/**
 * ToastProvider
 * - Provides `notify()` hook.
 * - Also listens to global `window` event `tg-toast` (used from services/api.ts).
 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const notify = useMemo(() => {
    return (message: string, type: ToastType = "info") => {
      const id = genId();
      setItems((prev) => [...prev, { id, type, message }]);
      // auto-remove
      window.setTimeout(() => {
        setItems((prev) => prev.filter((x) => x.id !== id));
      }, type === "error" ? 4500 : 2500);
    };
  }, []);

  useEffect(() => {
    const handler = (ev: any) => {
      const detail = ev?.detail;
      if (!detail) return;
      const msg = String(detail.message ?? detail.msg ?? "").trim();
      if (!msg) return;
      const type = (detail.type as ToastType) || "info";
      notify(msg, type);
    };
    window.addEventListener("tg-toast", handler as any);
    return () => window.removeEventListener("tg-toast", handler as any);
  }, [notify]);

  return (
    <ToastContext.Provider value={{ notify }}>
      {children}
      <div className="toast-host" aria-live="polite" aria-relevant="additions">
        {items.map((t) => (
          <div key={t.id} className={`toast toast-${t.type}`}> {t.message} </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
