// Simple color name -> hex mapping + gradient builder for composite colors.

export type ColorSwatchInfo = {
  raw: string;
  parts: string[];
  hex: string[];
  css: { backgroundColor?: string; backgroundImage?: string };
};

const COLOR_MAP: Array<{ re: RegExp; hex: string }> = [
  { re: /(black|черн)/i, hex: "#111827" },
  { re: /(white|бел)/i, hex: "#F9FAFB" },
  { re: /(gray|grey|сер)/i, hex: "#9CA3AF" },
  { re: /(red|красн)/i, hex: "#EF4444" },
  { re: /(blue|син)/i, hex: "#3B82F6" },
  { re: /(голуб|sky)/i, hex: "#60A5FA" },
  { re: /(green|зел)/i, hex: "#22C55E" },
  { re: /(yellow|желт)/i, hex: "#EAB308" },
  { re: /(orange|оранж)/i, hex: "#F97316" },
  { re: /(purple|violet|фиолет)/i, hex: "#A855F7" },
  { re: /(pink|роз)/i, hex: "#EC4899" },
  { re: /(brown|корич)/i, hex: "#92400E" },
  { re: /(beige|беж)/i, hex: "#F5F5DC" },
  { re: /(gold|золот)/i, hex: "#D4AF37" },
  { re: /(silver|сереб)/i, hex: "#C0C0C0" },
  { re: /(teal|бирюз)/i, hex: "#14B8A6" },
  { re: /(^|\b)navy(\b|$)|темно-син|тёмно-син/i, hex: "#1E3A8A" },
  { re: /(^|\b)sky_blue(\b|$)|голуб/i, hex: "#60A5FA" },
  { re: /(^|\b)turquoise(\b|$)/i, hex: "#40E0D0" },
  { re: /(^|\b)mint(\b|$)/i, hex: "#98FF98" },
  { re: /(^|\b)olive(\b|$)/i, hex: "#6B8E23" },
  { re: /(^|\b)lime(\b|$)/i, hex: "#84CC16" },
  { re: /(^|\b)burgundy(\b|$)|бордов/i, hex: "#7F1D1D" },
  { re: /(^|\b)maroon(\b|$)/i, hex: "#7A1F3D" },
  { re: /(^|\b)coral(\b|$)/i, hex: "#FB7185" },
  { re: /(^|\b)peach(\b|$)/i, hex: "#FDBA74" },
  { re: /(^|\b)lavender(\b|$)/i, hex: "#C4B5FD" },
  { re: /(^|\b)lilac(\b|$)|сирен/i, hex: "#A78BFA" },
  { re: /(^|\b)violet(\b|$)/i, hex: "#8B5CF6" },
  { re: /(^|\b)khaki(\b|$)/i, hex: "#A3A35C" },
  { re: /(^|\b)sand(\b|$)/i, hex: "#E9D8A6" },
  { re: /(^|\b)camel(\b|$)/i, hex: "#C19A6B" },
  { re: /(^|\b)cream(\b|$)/i, hex: "#FFFDD0" },
  { re: /(^|\b)off_white(\b|$)/i, hex: "#FAF9F6" },
  { re: /(^|\b)bronze(\b|$)/i, hex: "#CD7F32" },
  { re: /(^|\b)multi(\b|$)|мульти/i, hex: "#9CA3AF" },
  { re: /(^|\b)none(\b|$)/i, hex: "#D1D5DB" },
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
