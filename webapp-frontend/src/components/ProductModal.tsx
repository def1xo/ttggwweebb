import React, { useEffect, useMemo, useState } from "react";
import axiosInstance from "../services/api";
import ColorSwatch from "./ColorSwatch";

type Category = { id: number; name: string };
type AdminProduct = any;

function parseSizes(input: string): string[] {
  const s = (input || "").trim();
  if (!s) return [];
  const normalized = s.replace(/–|—/g, "-");
  const parts = normalized.split(/[\n,]/g).map((x) => x.trim()).filter(Boolean);
  const out: Array<number> = [];
  const extras: Array<number> = [];

  for (const p of parts) {
    const m = p.match(/^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$/);
    if (m) {
      const a = Number(m[1]);
      const b = Number(m[2]);
      if (Number.isFinite(a) && Number.isFinite(b)) {
        const start = Math.min(a, b);
        const end = Math.max(a, b);
        // step 1 for ranges
        const iStart = Math.ceil(start);
        const iEnd = Math.floor(end);
        for (let v = iStart; v <= iEnd; v += 1) out.push(v);
        continue;
      }
    }

    // split by spaces
    const bits = p.split(/\s+/g).map((x) => x.trim()).filter(Boolean);
    for (const b of bits) {
      const v = Number(b);
      if (Number.isFinite(v)) extras.push(v);
    }
  }

  const all = Array.from(new Set([...out, ...extras])).sort((x, y) => x - y);
  return all.map((x) => {
    const s = String(x);
    return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
  });
}

export default function ProductModal({
  open,
  onClose,
  product,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  product?: AdminProduct | null;
  onSaved: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [categories, setCategories] = useState<Category[]>([]);

  const [title, setTitle] = useState("");
  const [basePrice, setBasePrice] = useState<string>("");
  const [description, setDescription] = useState("");
  const [categoryId, setCategoryId] = useState<string>("");
  const [visible, setVisible] = useState(true);

  const [sizesInput, setSizesInput] = useState("");
  const parsedSizes = useMemo(() => parseSizes(sizesInput), [sizesInput]);

  const [colorInput, setColorInput] = useState("");

  const [files, setFiles] = useState<File[]>([]);
  const filePreviews = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);

  useEffect(() => {
    if (!open) return;
    (async () => {
      try {
        const r = await axiosInstance.get("/api/categories");
        const data = (r as any).data ?? r;
        setCategories(Array.isArray(data) ? data : (data?.items || []));
      } catch (e) {
        setCategories([]);
      }
    })();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const p: any = product || {};
    setTitle(p.title || p.name || "");
    setBasePrice(String(p.base_price ?? p.price ?? ""));
    setDescription(p.description || "");
    setCategoryId(p.category_id ? String(p.category_id) : "");
    setVisible(p.visible ?? true);
    setSizesInput((p.sizes && Array.isArray(p.sizes) ? p.sizes.join(", ") : "") || "");
    setColorInput((p.colors && Array.isArray(p.colors) ? p.colors.join(" / ") : "") || "");
    setFiles([]);
  }, [open, product]);

  useEffect(() => {
    return () => {
      filePreviews.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [filePreviews]);

  if (!open) return null;

  const existingImages: string[] = (product as any)?.images || ((product as any)?.default_image ? [(product as any).default_image] : []);

  const submit = async () => {
    if (!title.trim()) {
      alert("Название обязательно");
      return;
    }
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("title", title.trim());
      if (basePrice !== "") fd.append("base_price", String(basePrice));
      if (description.trim()) fd.append("description", description.trim());
      if (categoryId) fd.append("category_id", categoryId);
      fd.append("visible", String(!!visible));

      if (parsedSizes.length) fd.append("sizes", parsedSizes.join(","));
      if (colorInput.trim()) fd.append("color", colorInput.trim());

      // multiple images
      for (const f of files) fd.append("images", f);

      if (product?.id) {
        await axiosInstance.put(`/api/admin/products/${product.id}`, fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      } else {
        await axiosInstance.post(`/api/admin/products`, fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
      }
      onSaved();
    } catch (e: any) {
      alert(e?.response?.data?.detail || "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal card" style={{ maxWidth: 720, width: "min(92vw, 720px)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>{product ? "Редактирование" : "Новый товар"}</h2>
          <button className="btn ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div style={{ marginTop: 12, display: "grid", gap: 12 }}>
          <div style={{ display: "grid", gap: 10 }}>
            <label className="small-muted">Название</label>
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Например: Nike Air Max" />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div style={{ display: "grid", gap: 10 }}>
              <label className="small-muted">Цена (₽)</label>
              <input className="input" value={basePrice} onChange={(e) => setBasePrice(e.target.value)} inputMode="decimal" placeholder="3990" />
            </div>
            <div style={{ display: "grid", gap: 10 }}>
              <label className="small-muted">Категория</label>
              <select className="input" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
                <option value="">— не выбрано —</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ display: "grid", gap: 10 }}>
            <label className="small-muted">Описание</label>
            <textarea className="input" value={description} onChange={(e) => setDescription(e.target.value)} rows={4} placeholder="Материал, особенности, советы по уходу..." />
          </div>

          <div style={{ display: "grid", gap: 10 }}>
            <label className="small-muted">Размеры</label>
            <input
              className="input"
              value={sizesInput}
              onChange={(e) => setSizesInput(e.target.value)}
              placeholder="40-45, 40.5, 41.5 (диапазон шагом 1, дробные через запятую)"
            />
            {!!parsedSizes.length && (
              <div className="chips">
                {parsedSizes.map((s) => (
                  <button
                    type="button"
                    key={s}
                    className="chip"
                    title="Нажми чтобы убрать"
                    onClick={() => {
                      const next = parsedSizes.filter((x) => x !== s);
                      setSizesInput(next.join(", "));
                    }}
                  >
                    {s}
                    <span style={{ opacity: 0.7, marginLeft: 6 }}>×</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div style={{ display: "grid", gap: 10 }}>
            <label className="small-muted">Цвет</label>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <input className="input" value={colorInput} onChange={(e) => setColorInput(e.target.value)} placeholder="черно-красный" style={{ flex: 1 }} />
              <ColorSwatch name={colorInput} size={22} />
            </div>
            <div className="small-muted">Можно писать через дефис/слеш: «черно-красный», «белый/черный» — превью строится автоматически.</div>
          </div>

          <div style={{ display: "grid", gap: 10 }}>
            <label className="small-muted">Фото</label>
            <label className="btn ghost" style={{ width: "fit-content", cursor: "pointer" }}>
              Выбрать файлы
              <input
                type="file"
                accept="image/*"
                multiple
                style={{ display: "none" }}
                onChange={(e) => {
                  const list = Array.from(e.target.files || []);
                  setFiles(list);
                }}
              />
            </label>
            <div className="small-muted">
              {files.length > 0 ? `Выбрано файлов: ${files.length}` : "Файлы не выбраны"}
            </div>

            {(filePreviews.length > 0 || existingImages.length > 0) && (
              <div className="thumb-grid">
                {filePreviews.map((u, idx) => (
                  <img key={`new-${idx}`} src={u} alt="" className="thumb" />
                ))}
                {filePreviews.length === 0 && existingImages.slice(0, 6).map((u, idx) => (
                  <img key={`old-${idx}`} src={u} alt="" className="thumb" />
                ))}
              </div>
            )}
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <input type="checkbox" checked={visible} onChange={(e) => setVisible(e.target.checked)} />
              <span className="small-muted">Показывать в каталоге</span>
            </label>

            <div style={{ display: "flex", gap: 10 }}>
              <button className="btn ghost" onClick={onClose} disabled={saving}>
                Отмена
              </button>
              <button className="btn" onClick={submit} disabled={saving}>
                {saving ? "Сохраняю..." : "Сохранить"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
