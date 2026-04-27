// Monitor tab: live grid of sessions, polled every 3s.
import * as api from "./api.js";
import { toast } from "./toast.js";

const POLL_MS = 3000;

let pollTimer = null;
let projectsCache = [];

const fmtDuration = (ms) => {
  if (!ms || ms < 0) return "—";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
};

function projectMeta(slug) {
  const p = projectsCache.find((x) => x.slug === slug);
  return {
    emoji: (p && p.emoji) || "•",
    color: (p && p.color) || "#00e5ff",
    display: (p && p.display_name) || slug,
  };
}

async function loadProjects() {
  try {
    const r = await api.get("/projects");
    projectsCache = r.projects || r || [];
  } catch (e) {
    projectsCache = [];
  }
}

function renderTile(s) {
  const meta = projectMeta(s.project_slug);
  const startedMs = Date.now() - new Date(s.started_at).getTime();
  const lastMs = Date.now() - new Date(s.last_activity).getTime();
  const cost = (s.cost_usd || 0).toFixed(4);

  const promptHtml =
    s.status === "needs_input" && s.needs_input_msg
      ? `<div class="tile-prompt">${escape(s.needs_input_msg)}</div>`
      : "";

  return `
    <div class="tile" data-session="${s.session_id}">
      <div class="tile-head">
        <div class="tile-title">
          <span class="tile-emoji">${meta.emoji}</span>
          <span>${escape(meta.display)}</span>
        </div>
        <span class="status-chip" data-status="${s.status}">${s.status}</span>
      </div>
      <div class="tile-meta">
        <span><span class="muted">tok in</span> <b>${s.tokens_in || 0}</b></span>
        <span><span class="muted">tok out</span> <b>${s.tokens_out || 0}</b></span>
        <span><span class="muted">$</span> <b>${cost}</b></span>
        <span><span class="muted">model</span> <b>${escape((s.model || "?").replace(/^claude-/, ""))}</b></span>
        <span><span class="muted">elapsed</span> <b>${fmtDuration(startedMs)}</b></span>
        <span><span class="muted">idle</span> <b>${fmtDuration(lastMs)}</b></span>
      </div>
      ${promptHtml}
    </div>
  `;
}

function escape(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function refresh() {
  const grid = document.getElementById("session-grid");
  const meta = document.getElementById("monitor-meta");
  try {
    const sessions = await api.get("/sessions/live");
    const list = Array.isArray(sessions) ? sessions : sessions.sessions || [];
    if (!list.length) {
      grid.innerHTML = `<div class="placeholder"><p>No active Claude Code sessions detected. Run <code>claude</code> in any project.</p></div>`;
    } else {
      grid.innerHTML = list.map(renderTile).join("");
    }
    meta.textContent = `${list.length} session${list.length === 1 ? "" : "s"} · ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    grid.innerHTML = `<div class="placeholder"><p>Failed to load sessions: ${escape(e.message)}</p><p class="muted">${escape(JSON.stringify(e.body || ""))}</p></div>`;
    meta.textContent = "error";
  }
}

function startPolling() {
  stopPolling();
  refresh();
  pollTimer = setInterval(refresh, POLL_MS);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

export function init() {
  document.getElementById("refresh-monitor").addEventListener("click", refresh);

  document.getElementById("session-grid").addEventListener("click", (e) => {
    const tile = e.target.closest(".tile[data-session]");
    if (!tile) return;
    const sessionId = tile.dataset.session;
    document.dispatchEvent(new CustomEvent("bridgedeck:open-terminal", { detail: { sessionId } }));
  });

  document.getElementById("launch-session-btn").addEventListener("click", async () => {
    if (!projectsCache.length) await loadProjects();
    const select = document.getElementById("launch-project");
    select.innerHTML = projectsCache
      .map((p) => `<option value="${escape(p.slug)}">${escape(p.emoji || "•")} ${escape(p.display_name || p.slug)}</option>`)
      .join("");
    document.getElementById("launch-modal").setAttribute("aria-hidden", "false");
  });

  document.getElementById("launch-confirm").addEventListener("click", async () => {
    const project_slug = document.getElementById("launch-project").value;
    const initial_prompt = document.getElementById("launch-prompt").value || null;
    const working_directory = document.getElementById("launch-cwd").value || null;
    if (!project_slug) return;
    try {
      await api.post("/sessions/launch", { project_slug, initial_prompt, working_directory });
      document.getElementById("launch-modal").setAttribute("aria-hidden", "true");
      toast.success("Launch dispatched");
      setTimeout(refresh, 600);
    } catch (e) {
      toast.error(`Launch failed: ${e.body && e.body.detail ? JSON.stringify(e.body.detail) : e.message}`);
    }
  });

  document.addEventListener("bridgedeck:tab", (e) => {
    if (e.detail.tab === "monitor") startPolling();
    else stopPolling();
  });

  loadProjects().then(startPolling);
}

export const monitor = { refresh, loadProjects };
