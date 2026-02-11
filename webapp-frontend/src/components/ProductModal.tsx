import React, { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import api from "../services/api";
import ColorSwatch from "./ColorSwatch";

type Category = { id: number; name: string };
type AdminProduct = any;


function parseColors(input: string): string[] {
  const s = (input || "").trim();
  if (!s) return [];
  return Array.from(new Set(
    s.split(/[\n,;/]+/g).map((x) => x.trim()).filter(Boolean)
  ));
}

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
  const [stockQuantity, setStockQuantity] = useState<string>("0");
  const [description, setDescription] = useState("");
  const [categoryId, setCategoryId] = useState<string>("");
  const [visible, setVisible] = useState(true);
  const [categoryOpen, setCategoryOpen] = useState(false);

  const [sizesInput, setSizesInput] = useState("");
  const parsedSizes = useMemo(() => parseSizes(sizesInput), [sizesInput]);

  const [colorInput, setColorInput] = useState("");
  const parsedColors = useMemo(() => parseColors(colorInput), [colorInput]);

  const [files, setFiles] = useState<File[]>([]);
  const filePreviews = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);

  useEffect(() => {
    if (!open) return;
    (async () => {
      try {
        const r = await api.get("/api/categories");
        const data = (r as any)?.data ?? r;
        const list = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : Array.isArray(data?.categories) ? data.categories : [];
        setCategories(list);
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
    setCategoryOpen(false);
  }, [open, product]);

  useEffect(() => {
    return () => {
      filePreviews.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [filePreviews]);

  if (!open) return null;

  const existingImages: string[] = (product as any)?.images || ((product as any)?.default_image ? [(product as any).default_image] : []);

  const selectedCategory = useMemo(() => {
    if (!categoryId) return null;
    return categories.find((c) => String(c.id) === String(categoryId)) || null;
  }, [categories, categoryId]);

  const submit = async () => {
    if (!title.trim()) {
      alert("Название обязательно");
      return;
    }
    setSaving(true);
    try {
      const payload: any = {
        title: title.trim(),
        base_price: basePrice === "" ? 0 : Number(basePrice),
        description: description.trim() || undefined,
        category_id: categoryId ? Number(categoryId) : undefined,
        visible: !!visible,
        stock_quantity: Math.max(0, Number(stockQuantity || 0)),
      };
      if (parsedSizes.length) payload.sizes = parsedSizes.join(",");
      if (parsedColors.length) payload.color = parsedColors.join(", ");
      if (files.length === 1) payload.image = files[0];
      if (files.length > 1) payload.images = files;

      const res = product?.id
        ? await api.updateProduct(product.id, payload)
        : await api.createProduct(payload);

      if ((res as any)?.detail || (res as any)?.error) {
        throw new Error((res as any)?.detail || (res as any)?.error || "Ошибка сохранения");
      }
      onSaved();
    } catch (e: any) {
      alert(e?.response?.data?.detail || "Ошибка сохранения");
    } finally {
      setSaving(false);
    }
  };

  return createPortal(
    <div className="modal-overlay modal-overlay--product" role="dialog" aria-modal="true" style={{ alignItems: "flex-start", overflowY: "auto", padding: "calc(10px + env(safe-area-inset-top)) 0 calc(18px + env(safe-area-inset-bottom))" }}>
      <div className="modal card product-modal product-modal-scroll" style={{ maxWidth: 980, width: "min(96vw, 980px)", overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>{product ? "Редактирование" : "Новый товар"}</h2>
          <button className="btn ghost product-modal__close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="product-modal__body" style={{ marginTop: 12, display: "grid", gap: 12 }}>
          <div style={{ display: "grid", gap: 10 }}>
            <label className="small-muted">Название</label>
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Например: Nike Air Max" />
          </div>

          <div className="product-modal__row2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div style={{ display: "grid", gap: 10 }}>
              <label className="small-muted">Цена (₽)</label>
              <input className="input" value={basePrice} onChange={(e) => setBasePrice(e.target.value)} inputMode="decimal" placeholder="3990" />
            </div>
            <div style={{ display: "grid", gap: 10, position: "relative" }}>
              <label className="small-muted">Категория</label>
              <button
                type="button"
                className="input"
                onClick={() => setCategoryOpen((v) => !v)}
                style={{ textAlign: "left", display: "flex", justifyContent: "space-between", alignItems: "center" }}
              >
                <span>{selectedCategory?.name || "— не выбрано —"}</span>
                <span style={{ opacity: 0.7 }}>{categoryOpen ? "▴" : "▾"}</span>
              </button>
              {categoryOpen ? (
                <div className="card" style={{ padding: 8, maxHeight: 240, overflowY: "auto" }}>
                  <button
                    type="button"
                    className="btn ghost"
                    style={{ width: "100%", justifyContent: "flex-start", textAlign: "left" }}
                    onClick={() => {
                      setCategoryId("");
                      setCategoryOpen(false);
                    }}
                  >
                    — не выбрано —
                  </button>
                  {categories.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      className="btn ghost"
                      style={{ width: "100%", justifyContent: "flex-start", textAlign: "left", marginTop: 6 }}
                      onClick={() => {
                        setCategoryId(String(c.id));
                        setCategoryOpen(false);
                      }}
                    >
                      {c.name}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>

          <div style={{ display: "grid", gap: 10 }}>
            <label className="small-muted">Остаток (на все варианты)</label>
            <input className="input" type="number" min={0} step={1} value={stockQuantity} onChange={(e) => setStockQuantity(e.target.value)} placeholder="0" />
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
            <label className="small-muted">Цвета</label>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <input className="input" value={colorInput} onChange={(e) => setColorInput(e.target.value)} placeholder="черный, белый, фиолетовый" style={{ flex: 1 }} />
            </div>
            {parsedColors.length > 0 ? (
              <div className="chips">
                {parsedColors.map((c) => (
                  <span key={c} className="chip" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                    <ColorSwatch name={c} size={16} />
                    {c}
                  </span>
                ))}
              </div>
            ) : null}
            <div className="small-muted">Пиши через запятую или слеш. Мы покажем предпросмотр цветов.</div>
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

          <div className="product-modal__actions" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
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
    </div>,
    document.body
  );
}
