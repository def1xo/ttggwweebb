import React from "react";
import { Link } from "react-router-dom";

type Props = {
  id: number;
  name: string;
  slug?: string;
  image?: string; // url path like /uploads/categories/...
};

export default function CategoryTile({ id, name, slug, image }: Props) {
  return (
    <Link to={`/catalog/${slug || id}`} className="category-full-tile" style={{display:'flex', alignItems:'center', gap:12}}>
      <div style={{width:78, height:78, flex:'0 0 78px', overflow:'hidden', borderRadius:10, background:'var(--glass)'}}>
        {image ? <img src={image} alt={name} style={{width:'100%', height:'100%', objectFit:'cover'}} /> : <div style={{width:'100%',height:'100%',display:'flex',alignItems:'center',justifyContent:'center',color:'var(--muted)'}}>—</div>}
      </div>
      <div style={{flex:1}}>
        <div style={{fontWeight:900, fontSize:16, color:'var(--panel)'}}>{name}</div>
        {/* optional subtitle */}
      </div>
    </Link>
  );
}
