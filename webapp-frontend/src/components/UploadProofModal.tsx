import React, { useEffect, useMemo, useRef, useState } from "react";
import { uploadPaymentProof } from "../services/api";
import { useToast } from "../contexts/ToastContext";

type Props = {
  open: boolean;
  orderId: string | number;
  onClose: () => void;
  onUploaded?: () => void;
};

function formatBytes(n: number) {
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function isPdf(file: File | null) {
  if (!file) return false;
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

export default function UploadProofModal({ open, orderId, onClose, onUploaded }: Props) {
  const { notify } = useToast();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  // 12MB hard-limit to avoid huge uploads on mobile
  const MAX_BYTES = 12 * 1024 * 1024;

  const previewUrl = useMemo(() => {
    if (!file) return null;
    if (isPdf(file)) return null;
    try {
      return URL.createObjectURL(file);
    } catch {
      return null;
    }
  }, [file]);

  useEffect(() => {
    return () => {
      if (previewUrl) {
        try {
          URL.revokeObjectURL(previewUrl);
        } catch {}
      }
    };
  }, [previewUrl]);

  useEffect(() => {
    if (!open) {
      setFile(null);
      setBusy(false);
      setError(null);
      setDragOver(false);
    }
  }, [open]);

  if (!open) return null;

  const pickFile = () => {
    try {
      inputRef.current?.click();
    } catch {}
  };

  const setFileSafe = (f: File | null) => {
    setError(null);
    if (!f) {
      setFile(null);
      return;
    }
    const okType =
      f.type.startsWith("image/") ||
      f.type === "application/pdf" ||
      f.name.toLowerCase().endsWith(".pdf");
    if (!okType) {
      setFile(null);
      setError("Только jpg/png/webp или pdf");
      return;
    }
    if (f.size > MAX_BYTES) {
      setFile(null);
      setError(`Файл слишком большой (${formatBytes(f.size)}). Максимум ${formatBytes(MAX_BYTES)}.`);
      return;
    }
    setFile(f);
  };

  const onDrop = (ev: React.DragEvent<HTMLDivElement>) => {
    ev.preventDefault();
    ev.stopPropagation();
    setDragOver(false);
    const f = ev.dataTransfer?.files?.[0] || null;
    setFileSafe(f);
  };

  const doUpload = async () => {
    if (!file) {
      setError("Сначала выбери файл");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await uploadPaymentProof(orderId, file);
      notify("Чек загружен ✅", "success");
      try { onUploaded?.(); } catch {}
      onClose();
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || "Не удалось загрузить чек";
      setError(String(msg));
      notify("Не удалось загрузить чек", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onMouseDown={onClose}>
      <div className="modal modal-proof" onMouseDown={(e) => e.stopPropagation()} style={{ maxWidth: 560, width: "min(92vw, 560px)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div style={{ fontWeight: 900, fontSize: 16 }}>📎 Подтверждение чека</div>
          <button className="btn ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="small-muted" style={{ marginTop: 8 }}>
          Принимаем <b>jpg/png/webp</b> или <b>pdf</b>. После подтверждения заказ уйдёт на модерацию.
        </div>

        <input
          ref={inputRef}
          type="file"
          accept="image/*,application/pdf"
          style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0] || null;
            setFileSafe(f);
          }}
        />

        <div
          className="screenshot-drop"
          style={{
            marginTop: 12,
            borderColor: dragOver ? "var(--ring)" : undefined,
            boxShadow: dragOver ? "0 0 0 2px rgba(150, 220, 255, 0.15)" : undefined,
            cursor: "pointer",
            userSelect: "none",
          }}
          onClick={pickFile}
          onDragOver={(ev) => {
            ev.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          {file ? (
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                <div style={{ textAlign: "left" }}>
                  <div style={{ fontWeight: 800, overflow: "hidden", textOverflow: "ellipsis" }}>{file.name}</div>
                  <div style={{ fontSize: 12, color: "var(--muted)" }}>{formatBytes(file.size)}</div>
                </div>
              </div>

              {previewUrl ? (
                <div style={{ borderRadius: 12, overflow: "hidden", border: "1px solid var(--border)" }}>
                  <img src={previewUrl} alt="preview" style={{ width: "100%", height: 260, objectFit: "cover" }} />
                </div>
              ) : isPdf(file) ? (
                <div className="card" style={{ padding: 12, borderRadius: 12, display: "flex", gap: 10, alignItems: "center" }}>
                  <div style={{ fontSize: 26 }}>📄</div>
                  <div style={{ textAlign: "left" }}>
                    <div style={{ fontWeight: 800 }}>PDF документ</div>
                    <div className="small-muted">Откроется после загрузки в админке</div>
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <div>
              <div style={{ fontWeight: 900 }}>Прикрепи файл чека</div>
              <div className="small-muted" style={{ marginTop: 6 }}>Максимум {formatBytes(MAX_BYTES)}. Лучше скрин из банка/чек одним файлом.</div>
            </div>
          )}
        </div>

        {error ? <div style={{ color: "salmon", marginTop: 10 }}>{error}</div> : null}

        <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
          <button className="btn" style={{ flex: 1 }} onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button className="btn-primary" style={{ flex: 1 }} onClick={doUpload} disabled={busy || !file}>
            {busy ? "Подтверждаем…" : "Подтвердить чек"}
          </button>
        </div>
      </div>
    </div>
  );
}
