// src/types.ts
export interface Category {
  id: number;
  name: string;
  image_url?: string | null;
}

export interface Product {
  id: number;
  name: string;
  title?: string;
  price: number;
  base_price?: number;
  category_id?: number | null;
  default_image?: string | null;
  images?: string[];
  description?: string | null;
  sizes?: string[]; // optional
  colors?: string[]; // optional
  variants?: Array<{
    id: number;
    price: number;
    stock?: number;
    size?: string | null;
    color?: string | null;
  }>; // optional
}

export interface CartItem {
  product: Product;
  qty: number;
  size?: string;
  color?: string;
}

export interface AssistantBalance {
  id: number;
  username?: string | null;
  full_name?: string | null;
  balance: number;
}
