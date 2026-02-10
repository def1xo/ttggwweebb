import React from "react";

export default function Skeleton({
  height = 12,
  width = "100%",
  style,
  className = "",
}: {
  height?: number;
  width?: number | string;
  style?: React.CSSProperties;
  className?: string;
}) {
  return (
    <div
      className={`skeleton ${className}`}
      style={{ height, width, ...style }}
      aria-hidden="true"
    />
  );
}
