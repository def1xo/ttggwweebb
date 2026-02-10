// src/components/ErrorBoundary.tsx
import React from "react";

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
    if (this.state.hasError) {
      return (
        <div style={{ padding: 20 }}>
          <h2 style={{ color: "red" }}>Произошла ошибка в приложении</h2>
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
