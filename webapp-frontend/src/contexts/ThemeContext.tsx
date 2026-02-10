import React, { createContext, useContext, useEffect, useState } from "react";

export type ThemeName = "dark" | "light";

const THEME_KEY = "theme";
export const THEME_CHANGE_EVENT = "theme-change";

const ThemeContext = createContext<{
  theme: ThemeName;
  setTheme: (t: ThemeName) => void;
}>({
  theme: "dark",
  setTheme: () => {},
});

function detectTheme(): ThemeName {
  // Product requirement: the app is dark-only.
  return "dark";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeName>(() => detectTheme());

  useEffect(() => {
    // apply theme to document and localStorage
    try {
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem(THEME_KEY, theme);
      // dispatch custom event for components listening (Logo etc.)
      const ev = new CustomEvent(THEME_CHANGE_EVENT, { detail: theme });
      window.dispatchEvent(ev);
    } catch (e) {
      // ignore
    }
  }, [theme]);

  function setTheme(t: ThemeName) {
    // dark-only
    setThemeState("dark");
  }

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
