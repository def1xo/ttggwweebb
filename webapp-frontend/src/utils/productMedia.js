export function normalizeColorValue(raw) {
  return String(raw || "").trim().toLowerCase();
}

function normalizeMediaUrl(raw) {
  if (!raw) return null;
  const url = String(raw).trim();
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  const base = String(import.meta?.env?.VITE_BACKEND_URL || import.meta?.env?.VITE_API_URL || "")
    .trim()
    .replace(/\/+$/, "")
    .replace(/\/api$/, "");
  if (url.startsWith("/")) return base ? `${base}${url}` : url;
  return base ? `${base}/${url}` : url;
}

function splitImageCandidates(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.flatMap((item) => splitImageCandidates(item));
  if (typeof raw === "object") {
    const obj = raw;
    return splitImageCandidates(obj.url || obj.src || obj.image || obj.image_url);
  }
  const value = String(raw).trim();
  if (!value) return [];
  const chunks = value.replace(/[\n\r\t]+/g, " ").split(/[;,|]+/g).map((x) => x.trim()).filter(Boolean);
  if (chunks.length > 1) return chunks;
  return [value];
}

function uniq(arr) {
  return Array.from(new Set(arr.filter(Boolean)));
}

function collectProductImages(product) {
  if (!product) return [];
  const buckets = [product.images, product.image_urls, product.imageUrls, product.gallery, product.photos, product.default_image];
  const out = [];
  for (const bucket of buckets) {
    for (const candidate of splitImageCandidates(bucket)) {
      const normalized = normalizeMediaUrl(candidate);
      if (normalized) out.push(normalized);
    }
  }
  return uniq(out);
}

export function getImagesForSelectedColor(product, selectedColor) {
  if (!product) return [];
  if (!selectedColor) return collectProductImages(product);
  const selected = normalizeColorValue(selectedColor);

  const fromVariantImages = (Array.isArray(product?.variants) ? product.variants : [])
    .filter((v) => normalizeColorValue(v?.color?.name || v?.color) === selected)
    .flatMap((v) => splitImageCandidates(v?.images || v?.image_urls))
    .map((item) => normalizeMediaUrl(item))
    .filter(Boolean);
  if (fromVariantImages.length) return uniq(fromVariantImages);

  const byColor = product?.images_by_color;
  if (byColor && typeof byColor === "object") {
    const matchKey = Object.keys(byColor).find((k) => normalizeColorValue(k) === selected);
    if (matchKey) {
      const fromMap = splitImageCandidates(byColor[matchKey]).map((item) => normalizeMediaUrl(item)).filter(Boolean);
      if (fromMap.length) return uniq(fromMap);
    }
  }

  const groups = Array.isArray(product?.color_variants) ? product.color_variants : [];
  const hit = groups.find((g) => normalizeColorValue(g?.color) === selected);
  const fromGroup = splitImageCandidates(hit?.images).map((item) => normalizeMediaUrl(item)).filter(Boolean);
  if (fromGroup.length) return uniq(fromGroup);

  return collectProductImages(product);
}

export function isColorInStock(variants, color) {
  if (!color) return true;
  const selected = normalizeColorValue(color);
  return (Array.isArray(variants) ? variants : []).some((v) => {
    const c = normalizeColorValue(v?.color?.name || v?.color);
    const stock = Number(v?.stock_quantity ?? v?.stock ?? v?.quantity ?? v?.qty ?? 0);
    return c === selected && Number.isFinite(stock) && stock > 0;
  });
}
