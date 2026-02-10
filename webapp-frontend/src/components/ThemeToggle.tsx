import React, { useEffect, useState } from "react";

export default function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    try {
      const t = localStorage.getItem("theme");
      return t === "light" ? "light" : "dark";
    } catch {
      return "dark";
    }
  });

  useEffect(() => {
    try {
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem("theme", theme);
    } catch {}
  }, [theme]);

  return (
    <button
      className="btn ghost"
      onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
      aria-label="Переключить тему"
      style={{ height: 34 }}
    >
      {theme === "dark" ? "Светлая" : "Тёмная"}
    </button>
  );
}
