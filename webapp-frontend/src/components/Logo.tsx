import React, { useEffect, useState } from "react";
import { useTheme } from "../contexts/ThemeContext";
import { THEME_CHANGE_EVENT } from "../contexts/ThemeContext";
import { Link } from "react-router-dom";

export default function Logo({ className = "h-10" }: { className?: string }) {
  const { theme } = useTheme();
  const [visible, setVisible] = useState(true);
  const [src, setSrc] = useState<string>(() => {
    // initial src based on initial theme
    return theme === "dark" ? "/logo_white.png" : "/logo_black.png";
  });

  useEffect(() => {
    // animate swap: fade out -> change src -> fade in
    setVisible(false);
    const t = setTimeout(() => {
      // NOTE: dark -> white logo, light -> black logo
      setSrc(theme === "dark" ? "/logo_white.png" : "/logo_black.png");
      setVisible(true);
    }, 140);
    return () => clearTimeout(t);
  }, [theme]);

  // Also listen to external theme-change events (in case something else toggles theme)
  useEffect(() => {
    const onTheme = (e: Event) => {
      try {
        const d = (e as CustomEvent).detail;
        if (d === "dark" || d === "light") {
          // context уже обновит theme; это просто защитный слушатель
        }
      } catch {}
    };
    window.addEventListener(THEME_CHANGE_EVENT, onTheme as EventListener);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, onTheme as EventListener);
  }, []);

  const img = (
    <img
      alt="logo"
      src={src}
      className={`${className} transition-opacity duration-300 ${visible ? "opacity-100" : "opacity-0"}`}
      style={{ objectFit: "contain", height: "2.5rem" }}
      onError={(e) => {
        const el = e.currentTarget as HTMLImageElement;
        if (!el.dataset.fallback) {
          el.dataset.fallback = "1";
          el.src = "/LOGO.png";
        }
      }}
    />
  );

  // Делать кликабельным логотип: ведёт на страницу /news (главная с новостями/рекомендациями)
  return (
    <Link to="/news" aria-label="На главную">
      {img}
    </Link>
  );
}
