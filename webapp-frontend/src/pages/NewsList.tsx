import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getLatestNews } from "../services/api";
import Skeleton from "../components/Skeleton";

type NewsItem = {
  id: string | number;
  title?: string;
  excerpt?: string;
  body?: string;
  created_at?: string;
};

export default function NewsList() {
  const [news, setNews] = useState<NewsItem[] | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const res: any = await getLatestNews(10);
        let items: NewsItem[] = [];
        if (!res) {
          items = [];
        } else if (Array.isArray(res)) {
          items = res;
        } else if (Array.isArray(res.items)) {
          items = res.items;
        } else if (Array.isArray(res.data)) {
          items = res.data;
        } else if (Array.isArray((res as any).news)) {
          items = (res as any).news;
        } else if (typeof res === "object") {
          const possible = (Object.values(res) || []).find((v) => Array.isArray(v));
          items = Array.isArray(possible) ? possible : [];
        } else {
          items = [];
        }
        setNews(items);
      } catch (e: any) {
        setErr(e?.message || "Ошибка при загрузке новостей");
        setNews([]);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="container" style={{ paddingTop: 12 }}>
        <div className="card">
          <div className="panel-title">Новости</div>
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 12, marginTop: 12 }}>
            {Array.from({ length: 6 }).map((_, idx) => (
              <li key={idx} className="card" style={{ padding: 12 }}>
                <Skeleton height={16} width="60%" />
                <div style={{ height: 8 }} />
                <Skeleton height={12} width="90%" />
                <div style={{ height: 6 }} />
                <Skeleton height={12} width="80%" />
                <div style={{ height: 10 }} />
                <Skeleton height={10} width="40%" />
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  if (err) {
    return <div className="container card" style={{ color: "red" }}>{err}</div>;
  }

  return (
    <div className="container" style={{ paddingTop: 12 }}>
      <div className="card">
        <div className="panel-title">Новости</div>
        <div style={{ marginTop: 12 }}>
          {!news || news.length === 0 ? (
            <div className="small-muted">Новостей пока нет</div>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 12 }}>
              {news.map((n) => (
                <li key={String(n.id)} className="card" style={{ padding: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
                    <div>
                      <div style={{ fontWeight: 700 }}>{n.title || "Без названия"}</div>
                      <div className="small-muted" style={{ marginTop: 6 }}>{n.excerpt || (n.body ? (n.body.length > 200 ? n.body.slice(0, 200) + "…" : n.body) : "")}</div>
                      <div className="small-muted" style={{ marginTop: 6, fontSize: 12 }}>{n.created_at ? new Date(n.created_at).toLocaleString() : ""}</div>
                    </div>
                    <div>
                      <Link to={`/news/${n.id}`} className="btn">Открыть</Link>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
