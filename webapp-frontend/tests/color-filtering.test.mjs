import assert from 'node:assert/strict';

function buildDisplayColorsLikeFrontend(product) {
  const explicitKeys = Array.isArray(product?.color_keys)
    ? product.color_keys.map((x) => String(x || '').trim().toLowerCase()).filter(Boolean)
    : [];
  const unique = Array.from(new Set(explicitKeys)).slice(0, 2);
  return unique.map((canonical) => ({ canonical, label: canonical }));
}

function imagesForColorLikeProductPage(p, color) {
  if (!p) return [];
  if (!color) return p.images || [];
  const byColor = p?.images_by_color && typeof p.images_by_color === 'object' ? p.images_by_color : {};
  const raw = Array.isArray(byColor?.[color]) ? byColor[color] : [];
  return raw.length ? raw : (p.images || []);
}

const A = 'black/gray';
const B = 'gray/beige';
const product = {
  color_keys: [A, B],
  images: ['u0', 'u1', 'u2', 'u3'],
  images_by_color: {
    [A]: ['u0', 'u1'],
    [B]: ['u2', 'u3'],
  },
};

const chips = buildDisplayColorsLikeFrontend(product);
assert.deepEqual(chips.map((c) => c.canonical), [A, B]);
assert.deepEqual(imagesForColorLikeProductPage(product, A), ['u0', 'u1']);
assert.deepEqual(imagesForColorLikeProductPage(product, B), ['u2', 'u3']);
console.log('ok');
