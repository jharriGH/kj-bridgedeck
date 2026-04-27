// Bridge tab: voice-first chat. Hold space to talk, SSE stream from /bridge/chat.
import * as api from "./api.js";
import { toast } from "./toast.js";

const TURN_LIMIT = 80;

let conversationId = null;
let recorder = null;
let recordChunks = [];
let recording = false;
let streaming = false;

function escape(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function appendTurn(role, body, opts = {}) {
  const history = document.getElementById("bridge-history");
  const greet = history.querySelector(".bridge-greeting");
  if (greet) greet.remove();
  const div = document.createElement("div");
  div.className = `bridge-turn ${role}`;
  div.innerHTML = `<div class="who">${role}</div><div class="body${opts.streaming ? " stream-cursor" : ""}"></div>`;
  div.querySelector(".body").textContent = body;
  history.appendChild(div);
  while (history.querySelectorAll(".bridge-turn").length > TURN_LIMIT) {
    history.querySelector(".bridge-turn").remove();
  }
  history.scrollTop = history.scrollHeight;
  return div;
}

function setMeta(text) {
  document.getElementById("bridge-meta").textContent = text || "";
}

async function loadHistory() {
  try {
    const r = await api.get("/bridge/conversations", { limit: 1 });
    const convs = r.conversations || [];
    if (!convs.length) return;
    const conv = convs[0];
    conversationId = conv.id;
    const detail = await api.get(`/bridge/conversations/${conv.id}`);
    const turns = detail.turns || [];
    const history = document.getElementById("bridge-history");
    const greet = history.querySelector(".bridge-greeting");
    if (greet && turns.length) greet.remove();
    turns.slice(-20).forEach((t) => {
      if (t.user_message) appendTurn("user", t.user_message);
      if (t.assistant_message) appendTurn("assistant", t.assistant_message);
    });
  } catch (e) {
    // Empty/no convs — fine.
  }
}

async function sendMessage(message, voice_input = false, audio_base64 = null) {
  if (streaming) {
    toast.error("Already streaming a response.");
    return;
  }
  streaming = true;
  appendTurn("user", message);
  const turn = appendTurn("assistant", "", { streaming: true });
  const bodyEl = turn.querySelector(".body");
  let assistantText = "";
  let intentLabel = "";
  let modelLabel = "";

  try {
    await api.streamPost(
      "/bridge/chat",
      {
        message,
        conversation_id: conversationId || undefined,
        voice_input,
        audio_base64: audio_base64 || undefined,
        stream: true,
      },
      ({ event, data }) => {
        switch (event) {
          case "transcript":
            // First user-message text was placeholder; replace with transcript.
            turn.previousElementSibling.querySelector(".body").textContent = data.text || message;
            break;
          case "intent":
            intentLabel = data.intent || "";
            setMeta(`intent: ${intentLabel}`);
            break;
          case "model_selected":
            modelLabel = (data.model || "").replace(/^claude-/, "");
            setMeta(`intent: ${intentLabel} · model: ${modelLabel}`);
            break;
          case "message_delta":
            if (data && data.text) {
              assistantText += data.text;
              bodyEl.textContent = assistantText;
              document.getElementById("bridge-history").scrollTop = 1e9;
            }
            break;
          case "actions_queued":
            const list = Array.isArray(data) ? data : [];
            if (list.length) {
              const div = document.createElement("div");
              div.className = "actions";
              div.textContent = `Queued ${list.length} action(s):\n` +
                list.map((a) => `  • ${a.action_type}${a.target_project ? " (" + a.target_project + ")" : ""}`).join("\n");
              turn.appendChild(div);
            }
            break;
          case "done":
            const cost = (data.cost || 0).toFixed(4);
            setMeta(
              `intent: ${intentLabel} · model: ${modelLabel} · ` +
              `${data.tokens_in || 0} → ${data.tokens_out || 0} tok · $${cost}`
            );
            break;
          case "error":
            toast.error(`Stream error: ${data.message || data}`);
            break;
        }
      }
    );
  } catch (e) {
    bodyEl.textContent = `(stream failed: ${e.message})`;
    toast.error(`Bridge chat failed: ${e.message}`);
  } finally {
    bodyEl.classList.remove("stream-cursor");
    turn.querySelector(".body").classList.remove("stream-cursor");
    streaming = false;
    await maybeSpeak(assistantText);
  }
}

async function maybeSpeak(text) {
  if (!text || !text.trim()) return;
  // Try server-side Piper. If it fails (503 / no piper), fall back to Web Speech.
  try {
    const resp = await fetch(`${api.config.apiUrl}/bridge/voice/synthesize`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${api.getAdminKey()}`,
      },
      body: JSON.stringify({ text: text.slice(0, 1000) }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.play().catch(() => {});
    audio.onended = () => URL.revokeObjectURL(url);
  } catch {
    if (window.speechSynthesis) {
      const u = new SpeechSynthesisUtterance(text.slice(0, 500));
      u.rate = 1.05;
      window.speechSynthesis.speak(u);
    }
  }
}

// --- Voice capture --------------------------------------------------------

async function startRecording() {
  if (recording) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordChunks = [];
    recorder = new MediaRecorder(stream, { mimeType: pickMime() });
    recorder.ondataavailable = (e) => e.data && e.data.size && recordChunks.push(e.data);
    recorder.onstop = handleRecorderStop;
    recorder.start();
    recording = true;
    setVoiceButton(true);
  } catch (e) {
    toast.error(`Mic error: ${e.message}`);
  }
}

function pickMime() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
  for (const m of candidates) {
    if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "audio/webm";
}

async function stopRecording() {
  if (!recording || !recorder) return;
  recorder.stop();
  recording = false;
  setVoiceButton(false);
  recorder.stream.getTracks().forEach((t) => t.stop());
}

async function handleRecorderStop() {
  const blob = new Blob(recordChunks, { type: recorder.mimeType });
  recordChunks = [];
  if (blob.size < 1500) {
    toast.error("Too short — hold longer.");
    return;
  }
  // Send the audio along with an empty message — server transcribes.
  const b64 = await blobToBase64(blob);
  await sendMessage("", true, b64);
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

function setVoiceButton(active) {
  const btn = document.getElementById("voice-btn");
  btn.setAttribute("aria-pressed", active ? "true" : "false");
  document.getElementById("voice-label").textContent = active ? "Recording…" : "Talk";
}

// --- Init -----------------------------------------------------------------

export function init() {
  document.getElementById("bridge-send").addEventListener("click", () => {
    const v = document.getElementById("bridge-input").value.trim();
    if (!v) return;
    document.getElementById("bridge-input").value = "";
    sendMessage(v);
  });
  document.getElementById("bridge-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      document.getElementById("bridge-send").click();
    }
  });
  document.querySelectorAll(".chip[data-suggest]").forEach((c) => {
    c.addEventListener("click", () => {
      const v = c.dataset.suggest;
      sendMessage(v);
    });
  });

  // Voice button: click toggles, mousedown/touchstart begins, release ends.
  const vbtn = document.getElementById("voice-btn");
  vbtn.addEventListener("mousedown", startRecording);
  vbtn.addEventListener("touchstart", (e) => { e.preventDefault(); startRecording(); });
  ["mouseup", "mouseleave", "touchend", "touchcancel"].forEach((ev) =>
    vbtn.addEventListener(ev, stopRecording)
  );

  // Hold space to talk (when Bridge tab is active and not typing in a field).
  let spaceDown = false;
  window.addEventListener("keydown", (e) => {
    if (e.code !== "Space" || spaceDown) return;
    if (!isBridgeActive()) return;
    if (isTyping(e.target)) return;
    spaceDown = true;
    e.preventDefault();
    startRecording();
  });
  window.addEventListener("keyup", (e) => {
    if (e.code !== "Space" || !spaceDown) return;
    spaceDown = false;
    e.preventDefault();
    stopRecording();
  });

  loadHistory();
}

function isBridgeActive() {
  return document.querySelector('[data-tab="bridge"]')?.getAttribute("aria-selected") === "true";
}

function isTyping(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
}
