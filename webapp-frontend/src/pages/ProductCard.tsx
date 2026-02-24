// webapp-frontend/src/components/ProductCard.tsx
import React from "react";
import { Link } from "react-router-dom";

export default function ProductCard({ product }: any) {
  const preview = product.default_image || (product.images && product.images[0]) || '/placeholder.jpg';
  return (
    <div className="card" style={{display:'flex', gap:12, alignItems:'center'}}>
      <Link to={`/product/${product.id}`} style={{display:'flex', alignItems:'center', gap:12, textDecoration:'none', color:'inherit'}}>
        <img src={preview} alt={product.name} loading="lazy" className="image-fade-in" style={{width:100, height:100, objectFit:'cover', borderRadius:8}}/>
        <div style={{flex:1}}>
          <div style={{fontWeight:800}}>{product.name}</div>
          <div style={{color:'var(--muted)'}}>{product.short_description || ''}</div>
        </div>
        <div style={{fontWeight:900}}>{product.base_price} ₽</div>
      </Link>
    </div>
  );
}
