import React from "react";
import { getColorSwatchInfo } from "../utils/colorUtils";

type Props = {
  name?: string | null;
  size?: number;
  title?: string;
};

export default function ColorSwatch({ name, size = 18, title }: Props) {
  const info = getColorSwatchInfo(name || "");
  const label = title ?? (info.raw || "цвет");
  const style: React.CSSProperties = {
    width: size,
    height: size,
    borderRadius: 999,
    border: "1px solid rgba(255,255,255,0.18)",
    boxShadow: "0 1px 8px rgba(0,0,0,0.25)",
    ...info.css,
  };

  return <span className="color-swatch" title={label} style={style} />;
}
