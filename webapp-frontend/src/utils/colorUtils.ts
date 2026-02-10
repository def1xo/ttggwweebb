// Simple color name -> hex mapping + gradient builder for composite colors.

export type ColorSwatchInfo = {
  raw: string;
  parts: string[];
  hex: string[];
  css: { backgroundColor?: string; backgroundImage?: string };
};

const COLOR_MAP: Array<{ re: RegExp; hex: string }> = [
  { re: /\b(black|черн)/i, hex: "#111827" },
  { re: /\b(white|бел)/i, hex: "#F9FAFB" },
  { re: /\b(gray|grey|сер)/i, hex: "#9CA3AF" },
  { re: /\b(red|красн)/i, hex: "#EF4444" },
  { re: /\b(blue|син)/i, hex: "#3B82F6" },
  { re: /\b(голуб|sky)/i, hex: "#60A5FA" },
  { re: /\b(green|зел)/i, hex: "#22C55E" },
  { re: /\b(yellow|желт)/i, hex: "#EAB308" },
  { re: /\b(orange|оранж)/i, hex: "#F97316" },
  { re: /\b(purple|violet|фиолет)/i, hex: "#A855F7" },
  { re: /\b(pink|роз)/i, hex: "#EC4899" },
  { re: /\b(brown|корич)/i, hex: "#92400E" },
  { re: /\b(beige|беж)/i, hex: "#F5F5DC" },
  { re: /\b(gold|золот)/i, hex: "#D4AF37" },
  { re: /\b(silver|сереб)/i, hex: "#C0C0C0" },
  { re: /\b(teal|бирюз)/i, hex: "#14B8A6" },
];

function partToHex(part: string): string {
  const p = part.trim().toLowerCase();
  if (!p) return "#9CA3AF";
  for (const m of COLOR_MAP) {
    if (m.re.test(p)) return m.hex;
  }
  return "#9CA3AF";
}

export function splitColorName(raw?: string): string[] {
  if (!raw) return [];
  const s = String(raw)
    .trim()
    .replace(/–|—/g, "-")
    .replace(/\s+/g, " ");
  if (!s) return [];
  // common separators: -, /, +, &, comma
  const parts = s
    .split(/[-/+,;&]|\sи\s/gi)
    .map((x) => x.trim())
    .filter(Boolean);
  // special case: "черно" -> treat as "черный" etc (prefix match works)
  return parts.length ? parts : [s];
}

export function getColorSwatchInfo(raw?: string): ColorSwatchInfo {
  const safeRaw = (raw || "").trim();
  const parts = splitColorName(safeRaw);
  const hex = parts.map(partToHex);

  const css: { backgroundColor?: string; backgroundImage?: string } = {};
  if (hex.length <= 1) {
    css.backgroundColor = hex[0] || "#9CA3AF";
  } else if (hex.length === 2) {
    // 50/50 with a soft transition
    css.backgroundImage = `linear-gradient(90deg, ${hex[0]} 0%, ${hex[0]} 46%, ${hex[1]} 54%, ${hex[1]} 100%)`;
  } else {
    const stops = hex.map((c, idx) => {
      const p = Math.round((idx / hex.length) * 100);
      return `${c} ${p}%`;
    });
    css.backgroundImage = `conic-gradient(${stops.join(",")})`;
  }

  return { raw: safeRaw, parts, hex, css };
}
