import React, { useEffect, useState } from "react";
import { getLatestNews, getProducts, getRecommendations } from "../services/api";
import ProductCard from "../components/ProductCard";

export default function Home() {
  const [news, setNews] = useState<any[]>([]);
  const [products, setProducts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const newsResp = await getLatestNews(3).catch(() => null);
        if (mounted) setNews(Array.isArray(newsResp) && newsResp.length ? newsResp : (window as any).demoNews ?? []);
      } catch {
        if (mounted) setNews((window as any).demoNews ?? []);
      }

      try {
        const recs = await getRecommendations().catch(() => null);
        if (recs && Array.isArray(recs) && recs.length) {
          if (mounted) setProducts(recs);
        } else {
          const prodsResp = await getProducts({ per_page: 10 }).catch(() => null);
          const items = prodsResp && Array.isArray(prodsResp.items) ? prodsResp.items : (window as any).demoProducts ?? [];
          const recent = Array.isArray(items)
            ? [...items].sort((a, b) => {
                const da = a.created_at ? new Date(a.created_at).getTime() : 0;
                const db = b.created_at ? new Date(b.created_at).getTime() : 0;
                return db - da;
              }).slice(0, 10)
            : [];
          const top = recent
            .slice()
            .sort((a, b) => (Number(b.price) || 0) - (Number(a.price) || 0))
            .slice(0, 4);
          if (mounted) setProducts(top.length ? top : (window as any).demoProducts ?? []);
        }
      } catch {
        if (mounted) setProducts((window as any).demoProducts ?? []);
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, []);

  return (
    <div className="container">
      <section style={{ marginBottom: 18 }}>
        <div style={{ marginBottom: 12 }}>
          <h2 className="h1">Новости</h2>
        </div>

        {news.length === 0 ? (
          <div className="card small-muted">Новостей пока нет</div>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {news.map((n) => (
              <article key={String(n.id)} className="card news-item">
                <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 800 }}>{n.title}</div>
                    <div className="small-muted" style={{ marginTop: 6 }}>{n.date || ""}</div>
                    <div style={{ marginTop: 10 }} className="small-muted">{n.text}</div>
                  </div>
                  {n.images && n.images[0] && (
                    <img src={n.images[0]} alt={n.title} style={{ width: 120, height: 80, objectFit: "cover", borderRadius: 10 }} />
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div className="h2">Рекомендуем</div>
        </div>

        {loading ? (
          <div className="card">Загрузка рекомендаций…</div>
        ) : (
          <div className="grid grid-4">
            {products.length === 0 && <div className="card small-muted">Нет рекомендованных товаров</div>}
            {products.map((p: any) => (
              <ProductCard key={p.id} product={p} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
