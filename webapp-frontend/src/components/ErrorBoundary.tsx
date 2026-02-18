// src/components/ErrorBoundary.tsx
import React from "react";

const DYNAMIC_IMPORT_RELOAD_KEY = "dynamic_import_reload_once";

function isDynamicImportError(error?: Error | null): boolean {
  const msg = String(error?.message || "");
  return /Failed to fetch dynamically imported module/i.test(msg)
    || /Importing a module script failed/i.test(msg)
    || /Loading chunk [\d]+ failed/i.test(msg)
    || /ChunkLoadError/i.test(msg);
}

type State = {
  hasError: boolean;
  error?: Error | null;
  info?: React.ErrorInfo | null;
};

export default class ErrorBoundary extends React.Component<{}, State> {
  constructor(props: {}) {
    super(props);
    this.state = { hasError: false, error: null, info: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error, info: null };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info);
    this.setState({ hasError: true, error, info });
  }

  render() {
    const dynamicImportError = isDynamicImportError(this.state.error);

    const reloadApp = () => {
      try { sessionStorage.setItem(DYNAMIC_IMPORT_RELOAD_KEY, "1"); } catch {}
      window.location.reload();
    };

    if (this.state.hasError) {
      return (
        <div style={{ padding: 20 }}>
          <h2 style={{ color: "red" }}>Произошла ошибка в приложении</h2>
          {dynamicImportError ? (
            <div className="card" style={{ padding: 12, marginTop: 10 }}>
              Похоже, приложение обновилось на сервере, а у тебя в браузере осталась старая версия чанков.
              <div style={{ marginTop: 10 }}>
                <button className="btn btn-primary" onClick={reloadApp}>Обновить приложение</button>
              </div>
            </div>
          ) : null}
          <div style={{ whiteSpace: "pre-wrap", marginTop: 12 }}>
            <strong>Ошибка:</strong>
            <div>{this.state.error?.message}</div>
            <details style={{ marginTop: 12 }}>
              <summary>Стек (показать)</summary>
              <pre>{this.state.error?.stack}</pre>
              <pre>{this.state.info ? JSON.stringify(this.state.info, null, 2) : ""}</pre>
            </details>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
