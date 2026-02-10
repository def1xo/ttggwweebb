// webapp-frontend/src/pages/ProductDetail.tsx
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import api from "../services/api";
import Skeleton from "../components/Skeleton";

export default function ProductDetail() {
  const { id } = useParams();
  const [product, setProduct] = useState<any>(null);
  const [main, setMain] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setError(null);
        const res = await api.get(`/api/products/${id}`);
        const p = res.data || res;
        setProduct(p);
        setMain(p.default_image || (p.images && p.images[0]) || null);
      } catch (e: any) {
        setError("Не удалось загрузить товар");
      }
    })();
  }, [id]);

  if (error) return <div className="container card" style={{ marginTop: 12 }}>{error}</div>;

  if (!product) {
    return (
      <div className="container" style={{ paddingTop: 12 }}>
        <div className="card">
          <Skeleton height={28} width="60%" />
        </div>
        <div style={{ height: 12 }} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 12 }}>
          <div style={{ background: "var(--card)", borderRadius: 12, padding: 12 }}>
            <Skeleton height={360} style={{ borderRadius: 10 }} />
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              {Array.from({ length: 4 }).map((_, idx) => (
                <Skeleton key={idx} height={80} width={80} style={{ borderRadius: 8 }} />
              ))}
            </div>
          </div>
          <div className="card">
            <Skeleton height={22} width="70%" />
            <div style={{ height: 8 }} />
            <Skeleton height={18} width="30%" />
            <div style={{ height: 12 }} />
            <Skeleton height={12} width="95%" />
            <div style={{ height: 8 }} />
            <Skeleton height={12} width="90%" />
            <div style={{ height: 8 }} />
            <Skeleton height={12} width="75%" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="app-header"><h1 style={{margin:'0 auto'}}>{product.name}</h1></div>
      <div style={{display:'grid', gridTemplateColumns:'1fr', gap:12}}>
        <div style={{background:'var(--card)', borderRadius:12, padding:12}}>
          {main && <img src={main} alt={product.name} style={{width:'100%', height:360, objectFit:'cover', borderRadius:10}} />}
          <div style={{display:'flex', gap:8, marginTop:8, overflowX:'auto'}}>
            {(product.images || []).map((im:string)=>(
              <img key={im} src={im} alt="" style={{width:80, height:80, objectFit:'cover', borderRadius:8, cursor:'pointer'}} onClick={()=>setMain(im)} />
            ))}
          </div>
        </div>
        <div className="card">
          <div style={{fontWeight:900, fontSize:20}}>{product.name}</div>
          <div style={{fontWeight:800, fontSize:18, marginTop:6}}>{product.base_price} ₽</div>
          <div style={{marginTop:10, color:'var(--muted)'}}>{product.description}</div>
        </div>
      </div>
    </div>
  );
}
