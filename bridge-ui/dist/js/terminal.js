// Terminal tab: per-session control, transcript poll, send/approve/focus/stop.
import * as api from "./api.js";
import { toast } from "./toast.js";

let activeId = null;
let pollTimer = null;
const POLL_MS = 2000;

function escape(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderTranscript(events) {
  if (!events || !events.length) return `<p class="muted">No transcript events yet.</p>`;
  return events
    .slice(-200)
    .map((ev) => {
      const role = ev.role || ev.type || "system";
      const text = ev.text || ev.content || "";
      return `<div class="transcript-line ${role}"><b>${role}:</b> ${escape(text)}</div>`;
    })
    .join("");
}

async function refresh() {
  if (!activeId) return;
  try {
    const session = await api.get(`/sessions/${activeId}`);
    const meta = session && (session.source ? session : {});
    document.getElementById("term-status").textContent = meta.status || "—";
    document.getElementById("term-status").dataset.status = meta.status || "idle";
    document.getElementById("term-tokens-in").textContent = meta.tokens_in || 0;
    document.getElementById("term-tokens-out").textContent = meta.tokens_out || 0;
    document.getElementById("term-cost").textContent = (meta.cost_usd || 0).toFixed(4);
    document.getElementById("term-model").textContent = (meta.model || "?").replace(/^claude-/, "");
    document.getElementById("term-project").textContent = meta.project_slug || "—";

    const needsCard = document.getElementById("needs-input-card");
    if (meta.status === "needs_input" && meta.needs_input_msg) {
      needsCard.classList.remove("hidden");
      document.getElementById("needs-input-text").textContent = meta.needs_input_msg;
    } else {
      needsCard.classList.add("hidden");
    }

    // Pull recent transcript events from /sessions/{id}/history
    try {
      const hist = await api.get(`/sessions/${activeId}/history`);
      const events = (hist && (hist.events || hist)) || [];
      document.getElementById("term-transcript").innerHTML = renderTranscript(events);
      const t = document.getElementById("term-transcript");
      t.scrollTop = t.scrollHeight;
    } catch (e) {
      // History endpoint may 503 in cloud mode — that's fine.
    }
  } catch (e) {
    toast.error(`Session refresh failed: ${e.message}`);
  }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(refresh, POLL_MS);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

function open(sessionId) {
  activeId = sessionId;
  document.getElementById("terminal-empty").classList.add("hidden");
  document.getElementById("terminal-body").classList.remove("hidden");
  document.querySelector('.tab[data-tab="terminal"]').click();
  refresh();
  startPolling();
}

async function send() {
  const text = document.getElementById("term-input").value.trim();
  if (!text || !activeId) return;
  try {
    await api.post(`/sessions/${activeId}/message`, { text, session_id: activeId });
    document.getElementById("term-input").value = "";
    toast.success("Sent");
    refresh();
  } catch (e) {
    toast.error(`Send failed: ${e.message}`);
  }
}

async function approve(choice) {
  if (!activeId) return;
  try {
    await api.post(`/sessions/${activeId}/approve`, { choice });
    toast.success(`Sent: ${choice}`);
    refresh();
  } catch (e) {
    toast.error(`Approve failed: ${e.message}`);
  }
}

async function focus() {
  if (!activeId) return;
  try {
    await api.post(`/sessions/${activeId}/focus`);
    toast.success("Window focused");
  } catch (e) {
    toast.error(`Focus failed: ${e.message}`);
  }
}

async function stop() {
  if (!activeId) return;
  if (!confirm("Stop this session?")) return;
  try {
    await api.post(`/sessions/${activeId}/stop`);
    toast.success("Stop signal sent");
    refresh();
  } catch (e) {
    toast.error(`Stop failed: ${e.message}`);
  }
}

async function note() {
  if (!activeId) return;
  const text = prompt("Note:");
  if (!text) return;
  try {
    await api.post("/notes", { session_id: activeId, note_text: text });
    toast.success("Note saved");
  } catch (e) {
    toast.error(`Note failed: ${e.message}`);
  }
}

export function init() {
  document.addEventListener("bridgedeck:open-terminal", (e) => open(e.detail.sessionId));
  document.getElementById("term-send").addEventListener("click", send);
  document.getElementById("term-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  document.getElementById("term-focus").addEventListener("click", focus);
  document.getElementById("term-stop").addEventListener("click", stop);
  document.getElementById("term-note").addEventListener("click", note);
  document.querySelectorAll("#needs-input-card [data-approve]").forEach((b) => {
    b.addEventListener("click", () => approve(b.dataset.approve));
  });

  document.addEventListener("bridgedeck:tab", (e) => {
    if (e.detail.tab !== "terminal") stopPolling();
    else if (activeId) startPolling();
  });
}
