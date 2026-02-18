// ttggwweebb/webapp-frontend/src/App.tsx
import React, { Suspense, lazy, useEffect } from "react";
import { Routes, Route, Navigate, useLocation, useNavigate } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import BottomNav from "./components/BottomNav";
import Logo from "./components/Logo";
import "./main.css";
import { ensureWebAppAuth } from "./services/webappAuth";


function shouldRecoverFromDynamicImportError(err: unknown): boolean {
  const msg = String((err as any)?.message || err || "");
  return /Failed to fetch dynamically imported module/i.test(msg)
    || /Importing a module script failed/i.test(msg)
    || /Loading chunk [\d]+ failed/i.test(msg)
    || /ChunkLoadError/i.test(msg);
}

const DYNAMIC_IMPORT_RELOAD_KEY = "dynamic_import_reload_once";

function recoverFromDynamicImportError(err: unknown): never {
  if (typeof window !== "undefined" && shouldRecoverFromDynamicImportError(err)) {
    try {
      const alreadyTried = sessionStorage.getItem(DYNAMIC_IMPORT_RELOAD_KEY) === "1";
      if (!alreadyTried) {
        sessionStorage.setItem(DYNAMIC_IMPORT_RELOAD_KEY, "1");
        window.location.reload();
      }
    } catch {
      window.location.reload();
    }
  }
  throw err;
}

function safeLazy<T extends React.ComponentType<any>>(factory: () => Promise<{ default: T }>) {
  return lazy(() => factory().catch((err) => recoverFromDynamicImportError(err)));
}

const Home = safeLazy(() => import("./pages/Home"));
const Catalog = safeLazy(() => import("./pages/Catalog"));
const CategoryView = safeLazy(() => import("./pages/CategoryView"));
const ProductPage = safeLazy(() => import("./pages/ProductPage"));
const CartComponent = safeLazy(() => import("./components/Cart"));
const OrderSuccess = safeLazy(() => import("./pages/OrderSuccess"));
const Profile = safeLazy(() => import("./pages/Profile"));
const Orders = safeLazy(() => import("./pages/Orders"));
const Favorites = safeLazy(() => import("./pages/Favorites"));
const ManagerDashboard = safeLazy(() => import("./pages/ManagerDashboard"));
const AssistantDashboard = safeLazy(() => import("./pages/AssistantDashboard"));
const NewsList = safeLazy(() => import("./pages/NewsList"));
const NewsDetail = safeLazy(() => import("./pages/NewsDetail"));
const AdminDashboard = safeLazy(() => import("./pages/AdminDashboard"));

export default function App() {
  const loc = useLocation();
  const nav = useNavigate();
  const viewKey = `${loc.pathname || ""}${loc.search || ""}`;

  useEffect(() => {
    const onVitePreloadError = () => {
      try {
        const alreadyTried = sessionStorage.getItem(DYNAMIC_IMPORT_RELOAD_KEY) === "1";
        if (!alreadyTried) {
          sessionStorage.setItem(DYNAMIC_IMPORT_RELOAD_KEY, "1");
          window.location.reload();
        }
      } catch {
        window.location.reload();
      }
    };

    window.addEventListener("vite:preloadError", onVitePreloadError as EventListener);
    return () => {
      window.removeEventListener("vite:preloadError", onVitePreloadError as EventListener);
    };
  }, []);

  useEffect(() => {
    // Telegram WebApp integration (non-fatal if opened in browser)
    // Initialize WebApp auth once; stores access_token + user in localStorage
    try { ensureWebAppAuth(); } catch {}
    try {
      const w: any = window as any;
      const tg = w?.Telegram?.WebApp;
      if (!tg) return;
      try { tg.ready(); } catch {}
      try { tg.expand(); } catch {}
    } catch {}
  }, []);

  useEffect(() => {
    try {
      const w: any = window as any;
      const tg = w?.Telegram?.WebApp;
      if (!tg) return;
      const p = loc.pathname || "/";
      const roots = new Set(["/", "/catalog", "/cart", "/profile", "/news", "/orders", "/favorites", "/manager", "/assistant", "/admin"]);
      const showBack = !roots.has(p);
      const onBack = () => {
        try { nav(-1); } catch { window.history.back(); }
      };

      if (showBack) {
        tg.BackButton.show();
        tg.BackButton.onClick(onBack);
      } else {
        tg.BackButton.hide();
      }

      return () => {
        try { tg.BackButton.offClick(onBack); } catch {}
      };
    } catch {}
  }, [loc.pathname, nav]);

  return (
    <ErrorBoundary>
      <div className="app-header" role="banner" aria-label="Header" style={{ position: "relative", padding: 8 }}>
        <div style={{ position: "absolute", left: "50%", transform: "translateX(-50%)" }}>
          <Logo />
        </div>
      </div>

      <Suspense fallback={<div style={{ padding: 30 }}>Загрузка…</div>}>
        <div className="route-view" key={viewKey}>
          <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/catalog" element={<Catalog />} />
          <Route path="/catalog/:id" element={<CategoryView />} />
          <Route path="/product/:id" element={<ProductPage />} />
          <Route path="/cart" element={<CartComponent />} />
          <Route path="/favorites" element={<Favorites />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/order/success/:id" element={<OrderSuccess />} />
          {/* legacy */}
          <Route path="/order-success/:id" element={<Navigate to={(loc.pathname || "").replace("/order-success/", "/order/success/")} replace />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/manager" element={<ManagerDashboard />} />
          <Route path="/assistant" element={<AssistantDashboard />} />
          <Route path="/news" element={<NewsList />} />
          <Route path="/news/:id" element={<NewsDetail />} />
          <Route path="/admin" element={<AdminDashboard />} />
          <Route path="*" element={<Navigate to="/news" replace />} />
          </Routes>
        </div>
      </Suspense>

      {!loc.pathname.startsWith("/admin") && <BottomNav />}
    </ErrorBoundary>
  );
}
