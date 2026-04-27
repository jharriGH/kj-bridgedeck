// Thin fetch wrapper around the BridgeDeck API. All routes (except health/root)
// require Authorization: Bearer <admin key>.

const KEY_STORAGE = "bridgedeck.adminKey";

export const config = {
  apiUrl:
    (window.BRIDGEDECK_CONFIG && window.BRIDGEDECK_CONFIG.API_URL) ||
    "https://kj-bridgedeck-api.onrender.com",
  version:
    (window.BRIDGEDECK_CONFIG && window.BRIDGEDECK_CONFIG.VERSION) || "1.0.0",
};

export function getAdminKey() {
  try {
    return localStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

export function setAdminKey(value) {
  try {
    localStorage.setItem(KEY_STORAGE, value || "");
  } catch {}
}

function authHeaders(extra = {}) {
  const key = getAdminKey();
  const h = { ...extra };
  if (key) h.Authorization = `Bearer ${key}`;
  return h;
}

async function _handle(resp) {
  const ct = resp.headers.get("content-type") || "";
  const text = await resp.text();
  let body = text;
  if (ct.startsWith("application/json")) {
    try {
      body = JSON.parse(text);
    } catch {}
  }
  if (!resp.ok) {
    const err = new Error(`${resp.status} ${resp.statusText}`);
    err.status = resp.status;
    err.body = body;
    throw err;
  }
  return body;
}

export async function get(path, params) {
  const url = new URL(`${config.apiUrl}${path}`);
  if (params) Object.entries(params).forEach(([k, v]) => v !== undefined && v !== null && url.searchParams.set(k, v));
  const resp = await fetch(url, { headers: authHeaders() });
  return _handle(resp);
}

export async function post(path, body) {
  const resp = await fetch(`${config.apiUrl}${path}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: body ? JSON.stringify(body) : undefined,
  });
  return _handle(resp);
}

export async function patch(path, body) {
  const resp = await fetch(`${config.apiUrl}${path}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: body ? JSON.stringify(body) : undefined,
  });
  return _handle(resp);
}

export async function del(path) {
  const resp = await fetch(`${config.apiUrl}${path}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  return _handle(resp);
}

// SSE-like POST with streaming body. The bridge /chat endpoint emits
// `event: x\ndata: y\n\n` chunks. We can't use EventSource because it's
// GET-only and unauthenticated; instead we read the response stream.
export async function streamPost(path, body, onEvent) {
  const resp = await fetch(`${config.apiUrl}${path}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`stream open failed ${resp.status}`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    // Each event ends with a blank line.
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const lines = raw.split("\n");
      let eventName = "message";
      let dataLines = [];
      for (const line of lines) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      const dataStr = dataLines.join("\n");
      let data = dataStr;
      try { data = JSON.parse(dataStr); } catch {}
      onEvent({ event: eventName, data });
    }
  }
}

// POST a binary body (audio bytes). Returns the parsed JSON.
export async function postAudio(path, audioBlob) {
  const b64 = await blobToBase64(audioBlob);
  return post(path, { audio_base64: b64, mime: audioBlob.type || "audio/webm" });
}

function blobToBase64(blob) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onloadend = () => {
      const s = r.result;
      const idx = s.indexOf(",");
      res(idx >= 0 ? s.slice(idx + 1) : s);
    };
    r.onerror = () => rej(r.error);
    r.readAsDataURL(blob);
  });
}

// Health is unauthenticated.
export async function health() {
  const resp = await fetch(`${config.apiUrl}/health`);
  return _handle(resp);
}
