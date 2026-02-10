// ttggwweebb/server/index.js
const express = require("express");
const multer = require("multer");
const path = require("path");
const fs = require("fs");
const { Pool } = require("pg");
const jwt = require("jsonwebtoken");
const cors = require("cors");

const UPLOAD_DIR = path.join(__dirname, "uploads");
if (!fs.existsSync(UPLOAD_DIR)) fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const upload = multer({ dest: UPLOAD_DIR });
const app = express();
app.use(cors());
app.use(express.json());
app.use("/uploads", express.static(UPLOAD_DIR));

const PORT = process.env.PORT || 8000;
const DATABASE_URL = process.env.DATABASE_URL || null;
const JWT_SECRET = process.env.JWT_SECRET || null;

let pool = null;
let dbAvailable = false;

async function tryConnectDb() {
  if (!DATABASE_URL) {
    console.warn("[server] DATABASE_URL not set — running in fallback (in-memory) mode.");
    dbAvailable = false;
    return;
  }
  try {
    pool = new Pool({ connectionString: DATABASE_URL });
    // try a simple query
    await pool.query("SELECT 1");
    dbAvailable = true;
    console.log("[server] Connected to PostgreSQL.");
  } catch (err) {
    console.warn("[server] Could not connect to PostgreSQL, running in fallback mode. Error:", err.message || err);
    dbAvailable = false;
    pool = null;
  }
}
tryConnectDb();

// Simple in-memory stores for fallback mode (not persistent)
const mem = {
  users: new Map(), // key: user_id -> profile
  categories: [],
  products: [],
  managers: [],
  sales_raw: [],
};

// Auth middleware: verifies JWT if JWT_SECRET present; otherwise dev-mode auto-auth as admin
function authenticateJWT(req, res, next) {
  const auth = req.headers.authorization;
  if (!auth) {
    if (!JWT_SECRET) {
      // dev fallback: make a fake admin user
      req.user = { id: 1, role: "admin" };
      return next();
    }
    return res.status(401).json({ message: "No Authorization header" });
  }
  const parts = auth.split(" ");
  if (parts.length !== 2 || parts[0] !== "Bearer") return res.status(401).json({ message: "Invalid Authorization header" });
  const token = parts[1];
  if (!JWT_SECRET) {
    // Dev: accept any token and decode payload if present
    try {
      const payload = jwt.decode(token) || {};
      req.user = { id: payload.id || 1, role: payload.role || "admin" };
    } catch {
      req.user = { id: 1, role: "admin" };
    }
    return next();
  }
  try {
    const payload = jwt.verify(token, JWT_SECRET);
    req.user = payload;
    return next();
  } catch (err) {
    return res.status(401).json({ message: "Invalid token" });
  }
}

// Role guard
function requireRole(...roles) {
  return (req, res, next) => {
    if (!req.user) return res.status(401).json({ message: "Unauthorized" });
    if (!roles.includes(req.user.role)) return res.status(403).json({ message: "Forbidden" });
    next();
  };
}

/**
 * Utility: run query if db available, else throw
 */
async function dbQuery(sql, params = []) {
  if (!dbAvailable || !pool) throw new Error("DB not available");
  const { rows } = await pool.query(sql, params);
  return rows;
}

/* PATCH /api/auth/me
   Accepts JSON with first_name, username, avatar_url, display_name.
   If DB available -> update users table by id (req.user.id).
   Else -> store in mem.users map keyed by req.user.id.
*/
app.patch("/api/auth/me", authenticateJWT, async (req, res) => {
  const userId = Number(req.user?.id || 0) || 0;
  const payload = req.body || {};
  if (!userId) return res.status(400).json({ message: "Missing user id in token" });

  try {
    if (dbAvailable) {
      // safe update only provided fields
      const fields = [];
      const values = [];
      let idx = 1;
      for (const k of ["first_name", "username", "avatar_url", "display_name"]) {
        if (payload[k] !== undefined) {
          fields.push(`${k} = $${idx++}`);
          values.push(payload[k]);
        }
      }
      if (fields.length === 0) return res.status(400).json({ message: "Nothing to update" });
      values.push(userId);
      const sql = `UPDATE users SET ${fields.join(", ")} WHERE id = $${values.length} RETURNING id, telegram_id, username, first_name, last_name, avatar_url, display_name, role, balance`;
      const rows = await dbQuery(sql, values);
      return res.json(rows[0] || { ok: true });
    } else {
      const cur = mem.users.get(userId) || {};
      const updated = { ...cur, ...payload, id: userId };
      mem.users.set(userId, updated);
      return res.json(updated);
    }
  } catch (err) {
    console.error("PATCH /api/auth/me error:", err?.message || err);
    return res.status(500).json({ message: "Server error", detail: err?.message || String(err) });
  }
});

/* POST /api/uploads
   Accepts multipart/form-data with field 'file'
   Returns { url: <public-url> }.
   Works regardless of DB availability.
*/
app.post("/api/uploads", authenticateJWT, upload.single("file"), async (req, res) => {
  if (!req.file) return res.status(400).json({ message: "No file uploaded" });
  const url = `${req.protocol}://${req.get("host")}/uploads/${req.file.filename}`;
  return res.json({ url });
});

/* GET /api/admin/stats
   Requires admin role.
   If DB available -> read order_sales or orders tables and compute summary.
   If not -> return mem.sales_raw derived summary (empty by default).
*/
app.get("/api/admin/stats", authenticateJWT, requireRole("admin"), async (req, res) => {
  try {
    if (dbAvailable) {
      // try to read from order_sales if exists, else try orders + order_items
      try {
        const rows = await dbQuery(`SELECT id, total, cost, manager_percent, manager_id, created_at FROM order_sales ORDER BY created_at DESC LIMIT 10000`);
        // compute summary
        const now = Date.now();
        const oneDay = 24 * 60 * 60 * 1000;
        const weekAgo = new Date(now - 7 * oneDay);
        const monthAgo = new Date(now - 30 * oneDay);
        let week_total = 0, month_total = 0, all_time_total = 0;
        for (const r of rows) {
          const t = Number(r.total || 0);
          const created = r.created_at ? new Date(r.created_at) : null;
          if (!created || created >= weekAgo) week_total += t;
          if (!created || created >= monthAgo) month_total += t;
          all_time_total += t;
        }
        return res.json({ sales_summary: { week_total, month_total, all_time_total }, sales_raw: rows });
      } catch (err) {
        // fallback: try orders + order_items
        try {
          const sales = await dbQuery(
            `SELECT o.id, o.total_amount as total, o.created_at, oi.price as item_price, oi.quantity as item_qty
             FROM orders o
             LEFT JOIN order_items oi ON oi.order_id = o.id
             ORDER BY o.created_at DESC LIMIT 10000`
          );
          // aggregate by order id
          const byId = new Map();
          for (const s of sales) {
            const id = s.id;
            const cur = byId.get(id) || { id, total: 0, cost: 0, created_at: s.created_at };
            cur.total = Number(s.total || cur.total);
            byId.set(id, cur);
          }
          const rowsArr = Array.from(byId.values());
          return res.json({ sales_raw: rowsArr });
        } catch (err2) {
          // cannot compute from DB
          console.warn("Could not compute stats from DB:", err2?.message || err2);
          // return empty but informative
          return res.json({ sales_summary: { week_total: 0, month_total: 0, all_time_total: 0 }, sales_raw: [] });
        }
      }
    } else {
      // fallback using in-memory sales
      const rows = mem.sales_raw || [];
      const now = Date.now();
      const oneDay = 24 * 60 * 60 * 1000;
      const weekAgo = new Date(now - 7 * oneDay);
      const monthAgo = new Date(now - 30 * oneDay);
      let week_total = 0, month_total = 0, all_time_total = 0;
      for (const r of rows) {
        const t = Number(r.total || 0);
        const created = r.created_at ? new Date(r.created_at) : null;
        if (!created || created >= weekAgo) week_total += t;
        if (!created || created >= monthAgo) month_total += t;
        all_time_total += t;
      }
      return res.json({ sales_summary: { week_total, month_total, all_time_total }, sales_raw: rows });
    }
  } catch (err) {
    console.error("GET /api/admin/stats error:", err?.message || err);
    return res.status(500).json({ message: "Server error" });
  }
});

/* Categories CRUD (admin) */
app.get("/api/admin/categories", authenticateJWT, requireRole("admin"), async (req, res) => {
  try {
    if (dbAvailable) {
      const rows = await dbQuery("SELECT id, name, slug, description, image_url FROM categories ORDER BY id");
      return res.json({ categories: rows });
    } else {
      return res.json({ categories: mem.categories });
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

app.post("/api/admin/categories", authenticateJWT, requireRole("admin"), async (req, res) => {
  const { name, slug, description, image_url } = req.body || {};
  if (!name) return res.status(400).json({ message: "Name required" });
  try {
    if (dbAvailable) {
      const rows = await dbQuery("INSERT INTO categories(name, slug, description, image_url) VALUES($1,$2,$3,$4) RETURNING *", [name, slug, description, image_url]);
      return res.json(rows[0]);
    } else {
      const id = mem.categories.length ? mem.categories[mem.categories.length - 1].id + 1 : 1;
      const c = { id, name, slug, description, image_url };
      mem.categories.push(c);
      return res.json(c);
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

app.patch("/api/admin/categories/:id", authenticateJWT, requireRole("admin"), async (req, res) => {
  const id = Number(req.params.id);
  const payload = req.body || {};
  try {
    if (dbAvailable) {
      const sets = [];
      const vals = [];
      let idx = 1;
      for (const k of ["name", "slug", "description", "image_url"]) {
        if (payload[k] !== undefined) {
          sets.push(`${k} = $${idx++}`);
          vals.push(payload[k]);
        }
      }
      if (sets.length === 0) return res.status(400).json({ message: "Nothing to update" });
      vals.push(id);
      const rows = await dbQuery(`UPDATE categories SET ${sets.join(", ")} WHERE id = $${vals.length} RETURNING *`, vals);
      return res.json(rows[0]);
    } else {
      const idx = mem.categories.findIndex((c) => c.id === id);
      if (idx === -1) return res.status(404).json({ message: "Not found" });
      mem.categories[idx] = { ...mem.categories[idx], ...payload };
      return res.json(mem.categories[idx]);
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

app.delete("/api/admin/categories/:id", authenticateJWT, requireRole("admin"), async (req, res) => {
  const id = Number(req.params.id);
  try {
    if (dbAvailable) {
      await dbQuery("DELETE FROM categories WHERE id = $1", [id]);
      return res.json({ ok: true });
    } else {
      mem.categories = mem.categories.filter((c) => c.id !== id);
      return res.json({ ok: true });
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

/* Products CRUD (admin) - lightweight */
app.get("/api/admin/products", authenticateJWT, requireRole("admin"), async (req, res) => {
  try {
    if (dbAvailable) {
      const rows = await dbQuery("SELECT id, title, slug, description, base_price, category_id, default_image FROM products ORDER BY id");
      return res.json({ products: rows });
    } else {
      return res.json({ products: mem.products });
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

app.post("/api/admin/products", authenticateJWT, requireRole("admin"), async (req, res) => {
  const payload = req.body || {};
  if (!payload.title) return res.status(400).json({ message: "title required" });
  try {
    if (dbAvailable) {
      const rows = await dbQuery(
        `INSERT INTO products(title, slug, description, base_price, category_id, default_image, visible)
         VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING *`,
        [payload.title, payload.slug || payload.title.toLowerCase().replace(/\s+/g, "-"), payload.description || null, payload.base_price || 0, payload.category_id || null, payload.default_image || null, !!payload.visible]
      );
      return res.json(rows[0]);
    } else {
      const id = mem.products.length ? mem.products[mem.products.length - 1].id + 1 : 1;
      const p = { id, title: payload.title, price: payload.base_price || 0, category_id: payload.category_id || null, description: payload.description || null, default_image: payload.default_image || null };
      mem.products.push(p);
      return res.json(p);
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

app.patch("/api/admin/products/:id", authenticateJWT, requireRole("admin"), async (req, res) => {
  const id = Number(req.params.id);
  const payload = req.body || {};
  try {
    if (dbAvailable) {
      const sets = [];
      const vals = [];
      let idx = 1;
      for (const k of ["title", "slug", "description", "base_price", "category_id", "default_image", "visible"]) {
        if (payload[k] !== undefined) {
          sets.push(`${k} = $${idx++}`);
          vals.push(payload[k]);
        }
      }
      if (sets.length === 0) return res.status(400).json({ message: "Nothing to update" });
      vals.push(id);
      const rows = await dbQuery(`UPDATE products SET ${sets.join(", ")} WHERE id = $${vals.length} RETURNING *`, vals);
      return res.json(rows[0]);
    } else {
      const idx = mem.products.findIndex((p) => p.id === id);
      if (idx === -1) return res.status(404).json({ message: "Not found" });
      mem.products[idx] = { ...mem.products[idx], ...payload };
      return res.json(mem.products[idx]);
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

app.delete("/api/admin/products/:id", authenticateJWT, requireRole("admin"), async (req, res) => {
  const id = Number(req.params.id);
  try {
    if (dbAvailable) {
      await dbQuery("DELETE FROM products WHERE id = $1", [id]);
      return res.json({ ok: true });
    } else {
      mem.products = mem.products.filter((p) => p.id !== id);
      return res.json({ ok: true });
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

/* Managers CRUD (admin) - add by user_id (telegram user id expected in your Python models) */
app.get("/api/admin/managers", authenticateJWT, requireRole("admin"), async (req, res) => {
  try {
    if (dbAvailable) {
      const rows = await dbQuery("SELECT id, telegram_id, username, first_name, role, balance FROM users WHERE role IN ('manager','assistant','admin') ORDER BY id");
      return res.json({ managers: rows });
    } else {
      return res.json({ managers: mem.managers });
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

app.post("/api/admin/managers", authenticateJWT, requireRole("admin"), async (req, res) => {
  const { user_id } = req.body || {};
  if (!user_id) return res.status(400).json({ message: "user_id required" });
  try {
    if (dbAvailable) {
      // set role in users table
      await dbQuery("UPDATE users SET role = 'manager' WHERE id = $1", [user_id]);
      const rows = await dbQuery("SELECT id, telegram_id, username, first_name, role, balance FROM users WHERE id = $1", [user_id]);
      return res.json(rows[0] || { ok: true });
    } else {
      const m = { id: mem.managers.length ? mem.managers[mem.managers.length-1].id + 1 : 1, user_id, role: "manager" };
      mem.managers.push(m);
      return res.json(m);
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

app.patch("/api/admin/managers/:id", authenticateJWT, requireRole("admin"), async (req, res) => {
  const id = Number(req.params.id);
  const payload = req.body || {};
  try {
    if (dbAvailable) {
      // support updating role / balance
      const sets = [];
      const vals = [];
      let idx = 1;
      for (const k of ["role", "balance"]) {
        if (payload[k] !== undefined) {
          sets.push(`${k} = $${idx++}`);
          vals.push(payload[k]);
        }
      }
      if (sets.length === 0) return res.status(400).json({ message: "Nothing to update" });
      vals.push(id);
      const rows = await dbQuery(`UPDATE users SET ${sets.join(", ")} WHERE id = $${vals.length} RETURNING id, telegram_id, username, first_name, role, balance`, vals);
      return res.json(rows[0]);
    } else {
      const idx = mem.managers.findIndex((m) => m.id === id);
      if (idx === -1) return res.status(404).json({ message: "Not found" });
      mem.managers[idx] = { ...mem.managers[idx], ...payload };
      return res.json(mem.managers[idx]);
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

app.delete("/api/admin/managers/:id", authenticateJWT, requireRole("admin"), async (req, res) => {
  const id = Number(req.params.id);
  try {
    if (dbAvailable) {
      await dbQuery("UPDATE users SET role = 'user' WHERE id = $1", [id]);
      return res.json({ ok: true });
    } else {
      mem.managers = mem.managers.filter((m) => m.id !== id);
      return res.json({ ok: true });
    }
  } catch (err) {
    console.error(err);
    return res.status(500).json({ message: "Server error" });
  }
});

/* Basic health and info */
app.get("/health", (req, res) => {
  res.json({ ok: true, db: dbAvailable });
});

app.listen(PORT, () => {
  console.log(`[server] Listening on ${PORT}. DB available: ${dbAvailable}`);
});
