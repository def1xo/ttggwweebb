/* src/components/Recommendations.tsx */
import React, { useEffect, useState } from 'react';
import { getRecommendations } from '../services/api';

export default function Recommendations() {
  const [items, setItems] = useState<any[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    getRecommendations()
      .then((data) => { if (mounted) setItems(data); })
      .catch((e: any) => { if (mounted) setErr(e?.message || 'Ошибка'); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  if (loading) return <div className="small-muted">Загрузка рекомендаций…</div>;
  if (err) return <div style={{ color: 'red' }}>{err}</div>;
  if (!items || items.length === 0) return <div className="small-muted">Нет рекомендаций</div>;

  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
      {items.map(item => (
        <div key={item.id} className="card" style={{ width: 160 }}>
          <img src={item.image ?? '/assets/no-image.png'} alt={item.title} style={{ width: '100%', height: 100, objectFit: 'cover', borderRadius: 8 }} />
          <div style={{ padding: 8 }}>
            <div style={{ fontWeight: 700, fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.title}</div>
            <div className="small-muted" style={{ marginTop: 6 }}>{item.price ? `${item.price} ₽` : '—'}</div>
            <div style={{ marginTop: 8 }}>
              <button className="btn" onClick={() => window.location.href = `#/product/${item.id}`}>В товар</button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
