import axios from "axios";

const baseURL = (import.meta as any).env?.VITE_BACKEND_URL ?? "";

// создаём инстанс axios с базовым URL и withCredentials если нужно
const api = axios.create({
  baseURL,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

// добавляем интерцептор, чтобы автоматически подставлять Authorization из localStorage
api.interceptors.request.use(
  (config) => {
    try {
      const token = localStorage.getItem("access_token");
      if (token) {
        config.headers = config.headers ?? {};
        config.headers["Authorization"] = `Bearer ${token}`;
      }
    } catch (e) {
      // ignore (SSR / build time)
    }
    return config;
  },
  (err) => Promise.reject(err)
);

export default api;
