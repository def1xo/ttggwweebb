// src/components/BottomNav.tsx
import React from "react";
import { Link, useLocation } from "react-router-dom";
import { Icon } from "./Icons";
import { hapticSelection } from "../utils/tg";

export default function BottomNav() {
  const loc = useLocation();
  const path = loc.pathname || "/";

  let role = "";
  try {
    const raw = localStorage.getItem("me");
    if (raw) role = (JSON.parse(raw)?.role || "") + "";
  } catch {}
  const isAdmin = role === "admin" || role === "superadmin";
  const isManager = role === "manager" || isAdmin;

  const active = (p: string) => path === p || path.startsWith(p + "/");

  const items: Array<{ to: string; label: string; icon: any; show?: boolean }> = [
    { to: "/catalog", label: "Каталог", icon: "storefront" },
    { to: "/cart", label: "Корзина", icon: "cart" },
    { to: "/profile", label: "Профиль", icon: "user" },
    { to: "/manager", label: "Панель", icon: "briefcase", show: !isAdmin && isManager },
  ];

  return (
    <div className="bottom-nav" role="navigation" aria-label="Bottom navigation">
      <div className="bottom-nav-inner">
        {items
          .filter((x) => x.show === undefined || x.show)
          .map((it) => (
            <Link
              key={it.to}
              to={it.to}
              className={active(it.to) ? "active" : ""}
              onClick={() => {
                try { hapticSelection(); } catch {}
              }}
            >
              <Icon name={it.icon} />
              <span>{it.label}</span>
            </Link>
          ))}
      </div>
    </div>
  );
}
