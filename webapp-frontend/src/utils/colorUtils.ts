// Simple color name -> hex mapping + gradient builder for composite colors.

export type ColorSwatchInfo = {
  raw: string;
  parts: string[];
  hex: string[];
  css: { backgroundColor?: string; backgroundImage?: string };
};

export type DisplayColor = { canonical: string; label: string };

const COLOR_PRIORITY = [
  "black", "white", "gray", "navy", "blue", "light_blue", "teal", "turquoise", "green", "lime", "olive",
  "yellow", "orange", "red", "burgundy", "pink", "purple", "lavender", "beige", "brown", "silver", "gold", "multicolor",
];

const COLOR_LABEL_RU: Record<string, string> = {
  black: "чёрный",
  white: "белый",
  gray: "серый",
  beige: "бежевый",
  brown: "коричневый",
  navy: "тёмно-синий",
  purple: "фиолетовый",
  blue: "синий",
  light_blue: "голубой",
  teal: "бирюзовый",
  turquoise: "бирюзовый",
  green: "зелёный",
  lime: "лаймовый",
  olive: "оливковый",
  yellow: "жёлтый",
  orange: "оранжевый",
  red: "красный",
  burgundy: "бордовый",
  pink: "розовый",
  lavender: "лавандовый",
  silver: "серебристый",
  gold: "золотой",
  multicolor: "мультиколор",
};

const COLOR_ALIASES: Record<string, string> = {
  grey: "gray",
  violet: "purple",
  lilac: "lavender",
  offwhite: "white",
  "off-white": "white",
  cream: "beige",
  sky: "light_blue",
  mint: "teal",
  aqua: "turquoise",
  maroon: "burgundy",
  "чёрный": "black",
  "черный": "black",
  "белый": "white",
  "серый": "gray",
  "фиолетовый": "purple",
  "фиолет": "purple",
  "зелёный": "green",
  "зеленый": "green",
  "синий": "blue",
  "голубой": "blue",
  "тёмно-синий": "navy",
  "темно-синий": "navy",
  "бордовый": "burgundy",
  "лавандовый": "lavender",
  "бирюзовый": "turquoise",
  "оливковый": "olive",
  "лаймовый": "lime",
  "серебристый": "silver",
  "золотой": "gold",
  "красный": "red",
  "жёлтый": "yellow",
  "желтый": "yellow",
  "оранжевый": "orange",
  "коричневый": "brown",
  "бежевый": "beige",
  "розовый": "pink",
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

export function normalizeCanonicalColor(raw?: string): string {
  const parts = splitColorName(raw)
    .map((p) => String(p || "").trim().toLowerCase())
    .map((p) => COLOR_ALIASES[p] || p)
    .filter((p) => Boolean(COLOR_LABEL_RU[p]));
  const uniq = Array.from(new Set(parts));
  const sorted = uniq.sort((a, b) => {
    const ai = COLOR_PRIORITY.indexOf(a);
    const bi = COLOR_PRIORITY.indexOf(b);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
  return sorted.slice(0, 2).join("/") || "multicolor";
}

function toRuLabel(canonical: string): string {
  if (!canonical) return "";
  return canonical
    .split("/")
    .map((p) => COLOR_LABEL_RU[p] || p)
    .join("/");
}

export function buildDisplayColors(product: any): DisplayColor[] {
  const explicitKeys = Array.isArray(product?.color_keys)
    ? product.color_keys.map((x: any) => normalizeCanonicalColor(String(x || ""))).filter(Boolean)
    : [];
  if (explicitKeys.length) {
    const first = explicitKeys[0];
    return [{ canonical: first, label: toRuLabel(first) }];
  }

  const canonicalDirect = normalizeCanonicalColor(product?.canonical_color || product?.detected_color || "");
  if (canonicalDirect && canonicalDirect !== "multicolor") {
    return [{ canonical: canonicalDirect, label: toRuLabel(canonicalDirect) }];
  }
  const variants = Array.isArray(product?.variants) ? product.variants : [];
  const candidate = [
    product?.detected_color,
    product?.selected_color,
    ...(Array.isArray(product?.available_colors) ? product.available_colors : []),
    ...(Array.isArray(product?.colors) ? product.colors : []),
    ...variants.map((v: any) => v?.color?.name || v?.color),
  ]
    .map((x) => String(x || ""))
    .filter(Boolean);

  const canon = Array.from(new Set(candidate.map((c) => normalizeCanonicalColor(c)).filter(Boolean)));
  if (!canon.length) return [];

  // Drop redundant single color when composite already contains it.
  const filtered = canon.filter((c) => {
    if (!c.includes("/")) {
      return !canon.some((cc) => cc.includes("/") && cc.split("/").includes(c));
    }
    return true;
  });
  return filtered
    .sort((a, b) => {
      const ac = a.includes("/") ? 0 : 1;
      const bc = b.includes("/") ? 0 : 1;
      if (ac !== bc) return ac - bc;
      return a.localeCompare(b);
    })
    .slice(0, 2)
    .map((c) => ({ canonical: c, label: toRuLabel(c) }));
}

export function buildDisplayColorChips(product: any, _locale: "ru" | "en" = "ru"): DisplayColor[] {
  return buildDisplayColors(product);
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
