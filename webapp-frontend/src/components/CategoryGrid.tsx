// src/components/CategoryGrid.tsx
import React from "react";
import { Category } from "../types";
import { useNavigate } from "react-router-dom";

interface Props {
  categories: Category[];
  onSelect?: (categoryId: number) => void;
}

export default function CategoryGrid({ categories, onSelect }: Props) {
  const nav = useNavigate();

  const handleClick = (catId: number) => {
    if (onSelect) return onSelect(catId);
    // по умолчанию — переход в каталог с фильтром
    nav(`/catalog`);
    // можно добавить hash с ?category_id=...
    window.location.hash = `#/catalog`;
    // если нужно, можно использовать state/params
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 12 }}>
      {categories.map((cat) => (
        <button
          key={cat.id}
          onClick={() => handleClick(cat.id)}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: 14,
            borderRadius: 12,
            border: "1px solid #ececec",
            background: "#fff",
            cursor: "pointer",
            textAlign: "left",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
            <div style={{ fontWeight: 800, fontSize: 15 }}>{cat.name}</div>
            <div style={{ color: "#8b8b8b", fontSize: 13, marginTop: 6 }}>Перейти в категорию</div>
          </div>

          {cat.image_url ? (
            <img
              src={cat.image_url}
              alt={cat.name}
              style={{ width: 72, height: 72, objectFit: "cover", borderRadius: 10, marginLeft: 12 }}
            />
          ) : (
            <div style={{ width: 72, height: 72, borderRadius: 10, background: "#f4f4f4", marginLeft: 12 }} />
          )}
        </button>
      ))}
    </div>
  );
}
