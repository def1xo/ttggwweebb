require('dotenv').config();

const { Telegraf } = require('telegraf');
const axios = require('axios');
const FormData = require('form-data');
const { S3Client, PutObjectCommand } = require('@aws-sdk/client-s3');
const crypto = require('crypto');

const BOT_TOKEN = String(process.env.BOT_TOKEN || process.env.TELEGRAM_BOT_TOKEN || "").trim();
const BACKEND_URL = process.env.BACKEND_URL || process.env.VITE_BACKEND_URL || process.env.VITE_API_URL || process.env.API_URL;
const S3_BUCKET = process.env.S3_BUCKET || process.env.VITE_S3_BUCKET;
const S3_REGION = process.env.S3_REGION || process.env.AWS_REGION || 'us-east-1';
const AWS_ACCESS_KEY_ID = process.env.AWS_ACCESS_KEY_ID;
const AWS_SECRET_ACCESS_KEY = process.env.AWS_SECRET_ACCESS_KEY;
const ADMIN_CHAT_ID = process.env.ADMIN_CHAT_ID; // optional
const IMPORTER_API_KEY = process.env.IMPORTER_API_KEY || process.env.BACKEND_IMPORTER_KEY || '';

function deriveBackendBase(url) {
  try {
    const u = new URL(url);
    return `${u.protocol}//${u.host}`;
  } catch (e) {
    const idx = (url || '').indexOf('/api/');
    if (idx >= 0) return (url || '').slice(0, idx);
    return (url || '').replace(/\/+$/, '');
  }
}

const BACKEND_BASE_URL = process.env.BACKEND_BASE_URL || deriveBackendBase(BACKEND_URL);

function looksLikePlaceholder(v) {
  const s = String(v || '').trim();
  if (!s) return true;
  const upper = s.toUpperCase();
  if (upper.includes('REPLACE_ME') || upper.includes('CHANGEME') || upper.includes('YOUR_TOKEN')) return true;
  // common dummy values
  if (s === '0' || s === 'token') return true;
  return false;
}

function looksLikeTelegramToken(v) {
  const s = String(v || '').trim();
  // Telegram bot token format: <digits>:<35-ish chars>
  return /^\d{5,}:[A-Za-z0-9_-]{20,}$/.test(s);
}

if (!BOT_TOKEN) {
  console.error('ERROR: BOT_TOKEN or TELEGRAM_BOT_TOKEN is required in env');
  process.exit(1);
}
if (looksLikePlaceholder(BOT_TOKEN) || !looksLikeTelegramToken(BOT_TOKEN)) {
  const redacted = String(BOT_TOKEN || '').slice(0, 5) + '…';
  console.error('ERROR: TELEGRAM_BOT_TOKEN looks invalid/placeholder. Set a real token in .env.production. Current:', redacted);
  process.exit(1);
}
if (!BACKEND_URL) {
  console.error('ERROR: BACKEND_URL (or VITE_BACKEND_URL / VITE_API_URL) is required in env');
  process.exit(1);
}
const USE_S3 = Boolean(S3_BUCKET);
if (!USE_S3) {
  console.warn('S3 is not configured. Media will be uploaded to backend /api/uploads (local storage).');
}
let s3 = null;
if (USE_S3) {
  const s3Config = { region: S3_REGION };
  if (AWS_ACCESS_KEY_ID && AWS_SECRET_ACCESS_KEY) {
    s3Config.credentials = {
      accessKeyId: AWS_ACCESS_KEY_ID,
      secretAccessKey: AWS_SECRET_ACCESS_KEY
    };
  }
  s3 = new S3Client(s3Config);
}


function buildImporterCandidates(url) {
  const raw = String(url || '').trim().replace(/\/+$/, '');
  if (!raw) return [];
  if (/\/importer\/channel_post$/i.test(raw)) return [raw];
  const base = deriveBackendBase(raw);
  const candidates = [
    `${base}/api/v1/importer/channel_post`,
    `${base}/api/importer/channel_post`,
    `${base}/importer/channel_post`,
  ];
  if (/\/api\//i.test(raw)) candidates.unshift(raw);
  return Array.from(new Set(candidates.filter(Boolean)));
}

const IMPORTER_CANDIDATES = buildImporterCandidates(BACKEND_URL);
console.log('Importer endpoints:', IMPORTER_CANDIDATES.join(', '));

async function postToBackendImporter(payload) {
  if (!IMPORTER_CANDIDATES.length) throw new Error('No backend importer endpoint configured');
  const headers = {};
  if (IMPORTER_API_KEY) headers['X-Importer-Key'] = IMPORTER_API_KEY;
  let lastErr = null;
  for (const endpoint of IMPORTER_CANDIDATES) {
    try {
      const res = await axios.post(endpoint, payload, { timeout: 20000, headers });
      return { endpoint, res };
    } catch (err) {
      lastErr = err;
      const status = err?.response?.status;
      if (status === 404 || status === 405) continue;
      throw err;
    }
  }
  throw lastErr || new Error('No importer endpoint accepted request');
}

const bot = new Telegraf(BOT_TOKEN);

// helper: download file from Telegram using file_path
async function downloadFileFromTelegram(filePath) {
  const fileUrl = `https://api.telegram.org/file/bot${BOT_TOKEN}/${filePath}`;
  const res = await axios.get(fileUrl, { responseType: 'arraybuffer', timeout: 20000 });
  return res.data; // Buffer
}

async function uploadBufferToS3(buffer, key, contentType = 'application/octet-stream') {
  const cmd = new PutObjectCommand({
    Bucket: S3_BUCKET,
    Key: key,
    Body: buffer,
    ContentType: contentType,
    ACL: 'public-read'
  });
  if (!s3) throw new Error("S3 client is not initialized");
  await s3.send(cmd);
  return `https://${S3_BUCKET}.s3.${S3_REGION}.amazonaws.com/${encodeURIComponent(key)}`;
}

async function uploadBufferToBackend(buffer, filename, contentType = 'application/octet-stream') {
  const uploadUrl = `${BACKEND_BASE_URL}/api/uploads`;
  const form = new FormData();
  form.append('file', buffer, { filename, contentType });
  const res = await axios.post(uploadUrl, form, {
    headers: form.getHeaders(),
    timeout: 20000,
    maxContentLength: Infinity,
    maxBodyLength: Infinity,
  });
  const url = res.data && (res.data.url || res.data.object_url || res.data.file_url);
  if (!url) throw new Error('Backend upload returned no url');
  if (typeof url === 'string' && url.startsWith('http')) return url;
  const rel = (typeof url === 'string') ? url : '';
  if (!rel) throw new Error('Backend upload returned invalid url');
  return `${BACKEND_BASE_URL}${rel.startsWith('/') ? '' : '/'}${rel}`;
}

async function uploadMedia(buffer, ext, contentType) {
  const filename = `tg.${ext || 'bin'}`;
  if (USE_S3) {
    const key = makeS3Key('telegram', ext || 'bin');
    return await uploadBufferToS3(buffer, key, contentType);
  }
  return await uploadBufferToBackend(buffer, filename, contentType);
}

function makeS3Key(prefix = 'imported', ext = 'jpg') {
  const hash = crypto.randomBytes(6).toString('hex');
  const ts = Date.now();
  return `${prefix}/${ts}-${hash}.${ext}`;
}

async function handleChannelPost(ctx) {
  try {
    const post = ctx.update.channel_post;
    if (!post) return;

    const text = post.text || post.caption || '';
    const message_id = post.message_id;
    const chat = post.chat || {};
    const chat_id = chat.id;
    const images = [];

    if (post.photo && Array.isArray(post.photo) && post.photo.length > 0) {
      const sizeObj = post.photo[post.photo.length - 1];
      const file_id = sizeObj.file_id;
      const file = await ctx.telegram.getFile(file_id);
      if (file && file.file_path) {
        const buf = await downloadFileFromTelegram(file.file_path);
        const ext = 'jpg';
        const url = await uploadMedia(buf, ext, 'image/jpeg');
        images.push(url);
      }
    }

    if (post.document) {
      const file_id = post.document.file_id;
      const file = await ctx.telegram.getFile(file_id);
      if (file && file.file_path) {
        const buf = await downloadFileFromTelegram(file.file_path);
        const mime = post.document.mime_type || 'application/octet-stream';
        let ext = 'bin';
        if (mime.includes('png')) ext = 'png';
        else if (mime.includes('jpeg') || mime.includes('jpg')) ext = 'jpg';
        else if (mime.includes('gif')) ext = 'gif';
        else if (mime.includes('pdf')) ext = 'pdf';
        const url = await uploadMedia(buf, ext, mime);
        images.push(url);
      }
    }

    const payload = {
      channel_id: chat_id,
      message_id,
      date: post.date || Math.floor(Date.now() / 1000),
      text,
      image_urls: images
    };

    try {
      const { endpoint } = await postToBackendImporter(payload);
      console.log(`Imported post ${message_id} from chat ${chat_id} -> ${endpoint}`);
    } catch (err) {
      console.error('Failed to POST to backend:', err && err.message ? err.message : err);
      if (ADMIN_CHAT_ID) {
        const errText = `❗️ Failed to import post ${message_id} from ${chat_id}:\n${err && err.message ? err.message : String(err)}`;
        try { await ctx.telegram.sendMessage(ADMIN_CHAT_ID, errText); } catch(e){ console.error('Failed to notify admin:', e && e.message ? e.message : e); }
      }
    }
  } catch (err) {
    console.error('Error in handleChannelPost:', err && err.message ? err.message : err);
  }
}

bot.on('channel_post', handleChannelPost);

(async () => {
  try {
    await bot.launch();
    console.log('Telegraf bot launched (listening for channel_post)');
  } catch (err) {
    // Telegraf часто возвращает 404 от Telegram API, если токен неверный
    if (err && (err.code || err.response || err.description)) {
      const status = err.response && err.response.status;
      const desc = err.description || (err.response && err.response.data && err.response.data.description);
      if (status) console.error('Failed to launch bot (HTTP):', status, desc || '');
      else console.error('Failed to launch bot:', err.code, desc || err.message || String(err));
      if (String(status) === '404') {
        console.error('Hint: Telegram returned 404. Usually this means TELEGRAM_BOT_TOKEN is wrong.');
      }
    } else {
      console.error('Failed to launch bot:', err && err.message ? err.message : err);
    }
    process.exit(1);
  }
})();

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));
