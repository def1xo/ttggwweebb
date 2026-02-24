import assert from 'node:assert/strict';
import { getImagesForSelectedColor, isColorInStock } from '../src/utils/productMedia.js';

const product = {
  images: ['default-1.jpg', 'default-2.jpg'],
  variants: [
    { color: 'Black', stock: 2, images: ['black-1.jpg', 'black-2.jpg'] },
    { color: 'White', stock: 0, images: ['white-1.jpg'] },
  ],
};

assert.equal(isColorInStock(product.variants, 'Black'), true);
assert.equal(isColorInStock(product.variants, 'White'), false);
assert.deepEqual(getImagesForSelectedColor(product, 'Black'), ['black-1.jpg', 'black-2.jpg']);
assert.deepEqual(getImagesForSelectedColor(product, 'White'), ['white-1.jpg']);
assert.deepEqual(getImagesForSelectedColor(product, 'Missing'), ['default-1.jpg', 'default-2.jpg']);
console.log('ok');
