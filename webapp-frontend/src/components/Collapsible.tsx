import React, { useLayoutEffect, useMemo, useRef, useState } from "react";

type Props = {
  open: boolean;
  children: React.ReactNode;
  /** ms */
  duration?: number;
  className?: string;
  style?: React.CSSProperties;
};

/**
 * Smooth accordion container (max-height + opacity).
 * - No external deps
 * - Works well inside Telegram WebApp
 */
export default function Collapsible({ open, children, duration = 220, className = "", style }: Props) {
  const innerRef = useRef<HTMLDivElement | null>(null);
  const [h, setH] = useState<number>(0);

  const transition = useMemo(
    () => `max-height ${duration}ms ease, opacity ${duration}ms ease`,
    [duration]
  );

  useLayoutEffect(() => {
    const el = innerRef.current;
    if (!el) return;

    const measure = () => {
      try {
        const next = el.scrollHeight || 0;
        setH(next);
      } catch {}
    };

    // measure immediately
    measure();

    // keep height updated while open (content may change)
    let ro: ResizeObserver | null = null;
    if (open && typeof ResizeObserver !== "undefined") {
      try {
        ro = new ResizeObserver(() => measure());
        ro.observe(el);
      } catch {
        ro = null;
      }
    }

    return () => {
      try {
        ro?.disconnect();
      } catch {}
    };
  }, [open, children]);

  return (
    <div
      className={`collapsible ${open ? "open" : ""} ${className}`.trim()}
      style={{
        overflow: "hidden",
        maxHeight: open ? h : 0,
        opacity: open ? 1 : 0,
        transition,
        ...style,
      }}
    >
      <div ref={innerRef} className="collapsible-inner">
        {children}
      </div>
    </div>
  );
}
