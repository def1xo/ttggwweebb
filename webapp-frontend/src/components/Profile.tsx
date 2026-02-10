// src/pages/Profile.tsx
import React, { useEffect, useRef, useState } from "react";
import { getMyProfile, axiosInstance, reportClientError } from "../services/api";
import ManagerPanelMini from "../components/ManagerPanelMini";
import AssistantPanelMini from "../components/AssistantPanelMini";
import "../main.css";
import { initWebAppAndAuth } from "../services/webappAuth";
import { Link } from "react-router-dom";

type OrderShort = {
  id: string | number;
  created_at?: string;
  total?: number;
  status?: string;
};

function normalizeRole(rawRole: any) {
  if (!rawRole) return "user";
  let r = String(rawRole).toLowerCase();
  r = r.replace(/^userrole[:\._-]*/i, "");
  r = r.replace(/^role[:\._-]*/i, "");
  r = r.replace(/[^a-z0-9]/gi, "_");
  if (r.includes("admin")) return "admin";
  if (r.includes("manager")) return "manager";
  if (r.includes("assistant")) return "assistant";
  return "user";
}

export default function Profile() {
  const [me, setMe] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [orders, setOrders] = useState<OrderShort[] | null>(null);
  const [ordersLoading, setOrdersLoading] = useState(false);
  const [ordersErr, setOrdersErr] = useState<string | null>(null);
  const [ordersOpen, setOrdersOpen] = useState(false);

  const [editExpanded, setEditExpanded] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [avatarPreview, setAvatarPreview] = useState<string | null>(localStorage.getItem("avatar_preview") || null);
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [avatarFileName, setAvatarFileName] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const [promoEditOpen, setPromoEditOpen] = useState(false);
  const [promoValue, setPromoValue] = useState<string | null>(null);
  const [promoSaving, setPromoSaving] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [backendOk, setBackendOk] = useState<boolean | null>(null);

  const isWebAppAvailable = typeof window !== "undefined" && !!((window as any).Telegram && (window as any).Telegram.WebApp);

  useEffect(() => {
    const onError = (ev: ErrorEvent) => {
      try { ev.preventDefault?.(); } catch {}
      const payload = {
        message: ev.message,
        filename: ev.filename,
        lineno: ev.lineno,
        colno: ev.colno,
        stack: ev.error?.stack ?? null,
        ua: navigator.userAgent,
        ts: Date.now(),
      };
      try { reportClientError(payload).catch(() => {}); } catch {}
      setErr("Произошла ошибка в скрипте. Обновите страницу или попробуйте позже.");
      console.error("Captured error event:", payload);
      return true;
    };
    const onRejection = (ev: PromiseRejectionEvent) => {
      const payload = {
        message: ev.reason?.message ?? String(ev.reason),
        stack: ev.reason?.stack ?? null,
        ua: navigator.userAgent,
        ts: Date.now(),
      };
      try { reportClientError(payload).catch(() => {}); } catch {}
      setErr("Необработанное исключение. Попробуйте перезагрузить.");
      console.error("Captured unhandledrejection:", payload);
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  async function probeBackend(): Promise<boolean> {
    try {
      const base = (import.meta as any).env?.VITE_BACKEND_URL ?? "";
      const candidates = [`${base}/health`, `/health`, `${base}/api/health`];
      for (const u of candidates) {
        try {
          const r = await fetch(u, { method: "GET" });
          if (r.ok) return true;
        } catch {}
      }
    } catch {}
    return false;
  }

  useEffect(() => {
    (async () => {
      setBackendOk(null);
      const ok = await probeBackend();
      setBackendOk(ok);
    })();
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        try {
          const data = await getMyProfile();
          setMe({ ...data, role: normalizeRole(data?.role) });
          setDisplayName(data?.first_name ?? data?.name ?? "");
          setUsername(data?.username ?? "");
          if (data?.avatar_url && !localStorage.getItem("avatar_preview")) setAvatarPreview(data.avatar_url);
          setPromoValue(data?.promo_code ?? null);
        } catch (e) {
          try {
            await initWebAppAndAuth();
            const data = await getMyProfile();
            setMe({ ...data, role: normalizeRole(data?.role) });
            setDisplayName(data?.first_name ?? data?.name ?? "");
            setUsername(data?.username ?? "");
            if (data?.avatar_url && !localStorage.getItem("avatar_preview")) setAvatarPreview(data.avatar_url);
            setPromoValue(data?.promo_code ?? null);
          } catch (e2: any) {
            if (!isWebAppAvailable && (e2?.message?.includes("No backend endpoint responded") || e2?.message?.includes("Network Error"))) {
              setErr(null);
            } else {
              setErr(e2?.message || "Ошибка при получении профиля");
            }
          }
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!backendOk) return;
    (async () => {
      const unsaved = localStorage.getItem("profile_unsaved");
      if (!unsaved) return;
      try {
        let token = localStorage.getItem("access_token");
        if (!token) {
          try {
            await initWebAppAndAuth();
            token = localStorage.getItem("access_token");
          } catch {}
        }
        if (!token) return;
        const payload = JSON.parse(unsaved);
        await axiosInstance.patch("/api/auth/me", payload);
        localStorage.removeItem("profile_unsaved");
        setSaveMsg("Локальные изменения синхронизированы на сервере.");
        try {
          const updated = await getMyProfile();
          setMe({ ...updated, role: normalizeRole(updated?.role) });
        } catch {}
      } catch (e) {}
    })();
  }, [backendOk]);

  async function loadOrders() {
    setOrdersErr(null);
    setOrdersLoading(true);
    setOrders(null);
    try {
      let token = localStorage.getItem("access_token");
      if (!token) {
        try {
          await initWebAppAndAuth();
          token = localStorage.getItem("access_token");
        } catch {}
      }
      const base = (import.meta as any).env?.VITE_BACKEND_URL ?? "";
      const endpoints = ["/api/orders/me", "/api/orders", "/api/my/orders", "/orders/me"];
      let success = false;
      for (const ep of endpoints) {
        const url = `${base}${ep}`;
        try {
          const resp = await fetch(url, {
            method: "GET",
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          });
          if (resp.status >= 200 && resp.status < 300) {
            const data = await resp.json();
            const list: OrderShort[] = Array.isArray(data)
              ? data
              : Array.isArray(data.items)
              ? data.items
              : Array.isArray((data as any).orders)
              ? (data as any).orders
              : [];
            setOrders(list);
            success = true;
            break;
          } else {
            if (resp.status === 401 || resp.status === 403) {
              setOrdersErr("Не авторизованы для просмотра заказов");
              return;
            }
            continue;
          }
        } catch {
          continue;
        }
      }
      if (!success) setOrdersErr("Не удалось загрузить заказы. Проверьте доступность бэкенда.");
    } finally {
      setOrdersLoading(false);
    }
  }

  function toggleOrders() {
    setOrdersOpen((v) => {
      const nv = !v;
      if (nv && !orders && !ordersLoading && !ordersErr) loadOrders();
      return nv;
    });
  }

  async function uploadAvatar(file: File): Promise<string> {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("subdir", "avatars");
    const resp = await axiosInstance.post("/api/uploads", fd, { headers: { "Content-Type": "multipart/form-data" } });
    const data = resp?.data ?? resp;
    const url = data?.url || data?.location || data?.file_url || data?.path || null;
    if (!url) throw new Error("Не удалось получить URL загруженного файла");
    return url;
  }

  async function handleSave() {
    setErr(null);
    setSaving(true);
    setSaveMsg(null);
    try {
      let avatar_url = avatarPreview;
      if (avatarFile) {
        setUploading(true);
        try {
          avatar_url = await uploadAvatar(avatarFile);
          setAvatarPreview(avatar_url);
          localStorage.setItem("avatar_preview", avatar_url);
        } catch {
          setSaveMsg("Аватар сохранён локально, загрузка на сервер не удалась.");
        } finally {
          setUploading(false);
        }
      }

      try {
        await axiosInstance.patch("/api/auth/me", { first_name: displayName, username, avatar_url });
        setSaveMsg("Изменения успешно сохранены на сервере.");
        try {
          const updated = await getMyProfile();
          setMe({ ...updated, role: normalizeRole(updated?.role) });
        } catch {}
        localStorage.removeItem("profile_unsaved");
      } catch (e: any) {
        const local = { first_name: displayName, username, avatar_preview: avatarPreview };
        localStorage.setItem("profile_unsaved", JSON.stringify(local));
        setSaveMsg("Сервер недоступен — изменения сохранены локально.");
        try { reportClientError({ phase: "save-fallback", error: String(e?.message || e) }).catch(()=>{}); } catch {}
      }

      setEditExpanded(false);
      setAvatarFile(null);
      setAvatarFileName(null);
    } catch (e: any) {
      setErr(e?.message || "Ошибка при сохранении профиля");
    } finally {
      setSaving(false);
    }
  }

  async function handlePromoSave() {
    if (!me) return;
    setPromoSaving(true);
    try {
      await axiosInstance.patch("/api/auth/me", { promo_code: promoValue });
      setPromoEditOpen(false);
      try {
        const updated = await getMyProfile();
        setMe({ ...updated, role: normalizeRole(updated?.role) });
        setPromoValue(updated?.promo_code ?? null);
      } catch {}
    } catch {
      setSaveMsg("Не удалось сохранить промокод на сервере.");
    } finally {
      setPromoSaving(false);
    }
  }

  function openFileDialog() {
    try {
      fileInputRef.current?.click();
    } catch (e: any) {
      setErr("Не удалось открыть диалог выбора файла");
    }
  }

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    try {
      const f = e.target.files?.[0] || null;
      if (f) {
        setAvatarFile(f);
        setAvatarFileName(f.name);
        try {
          setAvatarPreview(URL.createObjectURL(f));
        } catch {
          setAvatarPreview(null);
        }
      }
    } catch (e: any) {
      setErr("Ошибка при выборе файла");
    }
  }

  function clearSelectedFile() {
    setAvatarFile(null);
    setAvatarFileName(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const shownName = (displayName && displayName.trim()) || me?.first_name || me?.name || "Гость";

  const role = me?.role || "user";
  const isAdmin = role === "admin" || role === "superadmin" || (typeof role === "string" && role.includes("admin"));
  const isManager = role === "manager" || (typeof role === "string" && role.includes("manager"));
  const isAssistant = role === "assistant" || (typeof role === "string" && role.includes("assistant"));

  if (loading) return <div className="container card">Загрузка профиля…</div>;
  if (err)
    return (
      <div className="container card" style={{ color: "red" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>{err}</div>
          <div>
            <button className="btn ghost" onClick={() => setErr(null)}>
              Закрыть
            </button>
          </div>
        </div>
      </div>
    );

  return (
    <div className="container" style={{ paddingTop: 8 }}>
      <div style={{ display: "flex", justifyContent: "center", marginBottom: 12 }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 92, height: 92, borderRadius: 9999, overflow: "hidden", margin: "0 auto", boxShadow: "0 8px 24px rgba(0,0,0,0.6)", background: "#111" }}>
            {avatarPreview ? (
              <img src={avatarPreview} alt="avatar" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            ) : (
              <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 800 }}>
                {String((shownName || "U").charAt(0)).toUpperCase()}
              </div>
            )}
          </div>

          <div style={{ marginTop: 10, fontWeight: 900, fontSize: 18 }}>{shownName}</div>
          <div className="small-muted" style={{ marginTop: 6 }}>{me?.username ? `@${me.username}` : ""}</div>

          <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center" }}>
            <button className="btn" onClick={() => setEditExpanded((v) => !v)}>
              {editExpanded ? "Закрыть" : "Редактировать профиль"}
            </button>
            <Link to="/news" className="btn ghost">
              Новости
            </Link>
                      </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div>
              <div className="panel-title">Аккаунт</div>
              <div className="small-muted" style={{ marginTop: 6 }}>{me?.email || ""}</div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {(isManager || isAssistant || isAdmin) ? (
              <>
                <div style={{ minWidth: 120 }}>
                  <ManagerPanelMini />
                </div>
                <AssistantPanelMini />
              </>
            ) : null}
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
          <div>
            <div className="small-muted">Статус аккаунта</div>
            <div style={{ fontWeight: 700, marginTop: 6, textTransform: "capitalize" }}>{role}</div>
          </div>
          <div>
            <div className="small-muted">Промокод</div>
            <div style={{ marginTop: 6, display: "flex", gap: 8, alignItems: "center" }}>
              <div style={{ fontWeight: 800 }}>{me?.promo_code ?? "-"}</div>
              {(isManager || isAdmin) && (
                <button className="btn ghost" onClick={() => { setPromoEditOpen((v) => !v); setPromoValue(me?.promo_code ?? ""); }}>
                  {promoEditOpen ? "Отмена" : "Ред."}
                </button>
              )}
            </div>
            {promoEditOpen && (
              <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                <input className="input" value={promoValue ?? ""} onChange={(e) => setPromoValue(e.target.value)} />
                <button className="btn" onClick={handlePromoSave} disabled={promoSaving}>
                  {promoSaving ? "Сох..." : "Сохранить"}
                </button>
              </div>
            )}
          </div>
        </div>

        <div style={{ marginTop: 12, display: "flex", gap: 12, color: "var(--muted,#9aa0a6)" }}>
          <div style={{ fontSize: 13 }}>{me?.created_at ? `Зарегистрирован: ${new Date(me.created_at).toLocaleDateString()}` : ""}</div>
          <div style={{ fontSize: 13 }}>{me?.telegram_id ? `tg:${me.telegram_id}` : ""}</div>
        </div>
      </div>

      {editExpanded && (
        <div className="card" style={{ marginBottom: 12, transition: "all .2s ease" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div className="panel-title">Редактирование профиля</div>
            <div className="small-muted">Изменения сохраняются на сервере. Если сервер недоступен — сохраняются локально.</div>
          </div>

          <div style={{ display: "flex", gap: 14, marginTop: 12 }}>
            <div style={{ width: 120 }}>
              <div style={{ width: 96, height: 96, borderRadius: 12, overflow: "hidden", background: "#111" }}>
                {avatarPreview ? (
                  <img src={avatarPreview} alt="avatar" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                ) : (
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#fff", fontWeight: 800 }}>
                    {String((displayName || "U").charAt(0)).toUpperCase()}
                  </div>
                )}
              </div>

              <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center" }}>
                <input ref={fileInputRef} type="file" accept="image/*" onChange={onFileChange} style={{ display: "none" }} />
                <button className="btn ghost" onClick={openFileDialog}>
                  {avatarFileName ? "Изменить изображение" : "Выбрать изображение"}
                </button>
                {avatarFileName && <button className="btn" onClick={clearSelectedFile}>Удалить</button>}
              </div>

              <div className="small-muted" style={{ marginTop: 6, fontSize: 12 }}>
                {avatarFileName ? avatarFileName : "Формат: JPG/PNG. Макс. 5MB."}
              </div>
            </div>

            <div style={{ flex: 1 }}>
              <label className="small-muted">Имя для отображения</label>
              <input className="input" value={displayName} onChange={(e) => { try { setDisplayName(e.target.value); } catch { setErr("Ошибка при вводе имени"); } }} />

              <label className="small-muted" style={{ marginTop: 10 }}>Username (telegram)</label>
              <input className="input" value={username} onChange={(e) => { try { setUsername(e.target.value); } catch { setErr("Ошибка при вводе username"); } }} />

              <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                <button className="btn" onClick={handleSave} disabled={saving || uploading}>{saving ? "Сохранение…" : "Сохранить"}</button>
                <button className="btn ghost" onClick={() => { setEditExpanded(false); setAvatarFile(null); setSaveMsg(null); }}>
                  Отмена
                </button>
              </div>

              {saveMsg && <div style={{ marginTop: 10 }} className="small-muted">{saveMsg}</div>}
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div className="panel-title">Личные данные и активность</div>
          <div>
            <button className="btn ghost" onClick={toggleOrders}>{ordersOpen ? "Скрыть заказы" : "Показать заказы"}</button>
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          {ordersOpen ? (
            ordersLoading ? (
              <div className="small-muted">Загрузка заказов…</div>
            ) : ordersErr ? (
              <div style={{ color: "var(--danger,#c0392b)" }}>{ordersErr}</div>
            ) : orders && orders.length > 0 ? (
              <div style={{ display: "grid", gap: 10 }}>
                {orders.map((o) => (
                  <div key={String(o.id)} style={{ padding: 10, borderRadius: 10, background: "rgba(255,255,255,0.02)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div>
                      <div style={{ fontWeight: 700 }}>Заказ #{o.id}</div>
                      <div className="small-muted" style={{ marginTop: 6 }}>{o.status ?? "—"} • {o.created_at ? new Date(o.created_at).toLocaleString() : ""}</div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontWeight: 800 }}>{o.total ?? "—"} ₽</div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="small-muted">У вас пока нет заказов</div>
            )
          ) : (
            <div className="small-muted">Здесь появятся рекомендации и персональные подборки.</div>
          )}
        </div>
      </div>
    </div>
  );
}
