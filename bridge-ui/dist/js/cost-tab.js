// Cost tab — full empire cost dashboard.
// Pulls /cost/summary, /cost/timeline, /cost/by-source, /cost/by-intent,
// /cost/rate-limit, /cost/wasted-cost, /cost/refund-worthy, /cost/caps,
// /sessions/health and renders one HUD-styled grid.
import * as api from "./api.js";
import { toast } from "./toast.js";

const escape = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

let pollTimer = null;

async function load() {
  const body = document.getElementById("cost-tab-body");
  body.innerHTML = `<div class="placeholder"><p>Loading cost dashboard…</p></div>`;

  try {
    const [summary, timeline, bySource, byIntent, rate, wasted, refund, caps, health, live] = await Promise.all([
      api.get("/cost/summary"),
      api.get("/cost/timeline", { days: 30 }),
      api.get("/cost/by-source", { days: 7 }),
      api.get("/cost/by-intent"),
      api.get("/cost/rate-limit"),
      api.get("/cost/wasted-cost", { days: 30 }),
      api.get("/cost/refund-worthy", { days: 30 }),
      api.get("/cost/caps"),
      api.get("/sessions/health"),
      api.get("/cost/live"),
    ]);

    body.innerHTML = render({
      summary, timeline, bySource, byIntent, rate, wasted, refund, caps, health, live,
    });
    bindCapEditors(caps);

    document.getElementById("cost-tab-meta").textContent =
      `${(summary.month || 0).toFixed(2)} mo · ${(live.active_sessions_burn_rate || 0).toFixed(2)} burn · ` +
      `updated ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    body.innerHTML = `<div class="placeholder"><p>Failed to load cost dashboard: ${escape(e.message)}</p></div>`;
  }
}

function render({ summary, timeline, bySource, byIntent, rate, wasted, refund, caps, health, live }) {
  const dollar = (n) => `$${Number(n || 0).toFixed(4)}`;
  const dollar2 = (n) => `$${Number(n || 0).toFixed(2)}`;

  // 4-stat row
  const stats = `
    <div class="cost-grid four">
      <div class="cost-card"><h4>Today</h4><div class="cost-stat">${dollar2(summary.today)}</div>
        <div class="muted small">live: ${dollar2(live.today)}</div></div>
      <div class="cost-card"><h4>Week</h4><div class="cost-stat">${dollar2(summary.week)}</div></div>
      <div class="cost-card"><h4>Month</h4><div class="cost-stat">${dollar2(summary.month)}</div></div>
      <div class="cost-card"><h4>Wasted (30d)</h4><div class="cost-stat">${dollar2(wasted.total_usd)}</div>
        <div class="muted small">${wasted.turns || 0} tagged</div></div>
    </div>`;

  // Heatmap
  const days = timeline.timeline || [];
  const max = Math.max(0.0001, ...days.map((d) => d.total || 0));
  const heat = days.map((d) => {
    const r = (d.total || 0) / max;
    const bin = r === 0 ? 0 : r < 0.25 ? 1 : r < 0.5 ? 2 : r < 0.75 ? 3 : 4;
    return `<div class="cell" data-bin="${bin}" title="${d.date}: ${dollar(d.total)}"></div>`;
  }).join("");

  // By source bars
  const src = bySource.sources || {};
  const srcMax = Math.max(0.0001, ...Object.values(src).map(Number));
  const sourceBars = Object.entries(src).sort((a, b) => b[1] - a[1])
    .map(([k, v]) => {
      const w = Math.round((Number(v) / srcMax) * 100);
      return `<div class="cost-bar"><span style="width:90px">${escape(k)}</span>` +
             `<div class="fill" style="width:${w}%"></div>` +
             `<span>${dollar(v)}</span></div>`;
    }).join("") || `<p class="muted">No data yet.</p>`;

  // By intent table
  const intents = byIntent.intents || [];
  const byIntentTable = intents.length ? `
    <table class="admin-table">
      <thead><tr><th>Intent</th><th>Turns</th><th>Avg $</th><th>Total $</th><th>Avg in</th><th>Avg out</th><th>Avg ms</th></tr></thead>
      <tbody>${intents.map((i) => `
        <tr>
          <td><b>${escape(i.intent)}</b></td>
          <td>${i.turn_count || 0}</td>
          <td>${dollar(i.avg_cost)}</td>
          <td>${dollar(i.total_cost)}</td>
          <td>${Math.round(Number(i.avg_in || 0))}</td>
          <td>${Math.round(Number(i.avg_out || 0))}</td>
          <td>${Math.round(Number(i.avg_ms || 0))}</td>
        </tr>`).join("")}</tbody>
    </table>` : `<p class="muted">No bridge turns logged in 30d. Send a few Bridge messages first.</p>`;

  // Top projects
  const tp = (summary.top_projects || []);
  const topProjTable = tp.length ? `
    <table class="admin-table">
      <thead><tr><th>Project</th><th>Total $ (30d)</th></tr></thead>
      <tbody>${tp.map((p) => `<tr><td>${escape(p.project_slug)}</td><td>${dollar(p.total_usd)}</td></tr>`).join("")}</tbody>
    </table>` : `<p class="muted">No project-tagged spend.</p>`;

  // Sessions needing attention
  const attn = health.needs_attention || [];
  const attnTable = attn.length ? `
    <table class="admin-table">
      <thead><tr><th>Session</th><th>Project</th><th>Status</th><th>$</th><th>Calls</th><th>Artifacts</th></tr></thead>
      <tbody>${attn.map((s) => `
        <tr>
          <td><code>${escape(String(s.session_id).slice(0, 16))}</code></td>
          <td>${escape(s.project_slug || "")}</td>
          <td><b>${escape(s.health_status)}</b></td>
          <td>${dollar(s.total_cost)}</td>
          <td>${s.call_count || 0}</td>
          <td>${s.artifacts_shipped || 0}</td>
        </tr>`).join("")}</tbody>
    </table>` : `<p class="muted">All sessions healthy${(health.counts && health.counts.healthy) ? ` (${health.counts.healthy} green)` : ""}.</p>`;

  // Refund-worthy
  const ref = (refund.details || []).slice(0, 8);
  const refundTable = ref.length ? `
    <table class="admin-table">
      <thead><tr><th>Turn</th><th>Outcome</th><th>$</th><th>Tagged</th></tr></thead>
      <tbody>${ref.map((r) => `
        <tr>
          <td><code>${escape(String(r.turn_id || "").slice(0, 16))}</code></td>
          <td>${escape(r.outcome)}</td>
          <td>${dollar(r.cost_usd)}</td>
          <td class="muted">${escape((r.tagged_at || "").slice(0, 19).replace("T"," "))}</td>
        </tr>`).join("")}</tbody>
    </table>` : `<p class="muted">Nothing tagged refund-worthy in 30d.</p>`;

  // Rate limit pills
  const rateLimitRows = (rate.live || []).map((t) => {
    const cur = t.current_usage || 0, hard = t.hard_limit || 1, soft = t.soft_limit || 1;
    const pct = Math.min(100, (cur / hard) * 100);
    const state = cur >= hard ? "over" : cur >= soft ? "warn" : "ok";
    return `<div class="rate-row" data-state="${state}">
      <span style="width:160px"><b>${escape(t.name)}</b></span>
      <div class="bar"><div class="fill" style="width:${pct}%"></div></div>
      <span class="muted">${cur} / ${hard} per ${t.window_seconds}s</span>
    </div>`;
  }).join("");
  const rateBlocks = (rate.recent_blocks || []).slice(0, 5);
  const rateBlocksTable = rateBlocks.length ? `
    <table class="admin-table"><thead><tr><th>When</th><th>Provider</th><th>Req</th><th>Limit</th><th>Resolution</th></tr></thead>
    <tbody>${rateBlocks.map((b) => `
      <tr>
        <td class="muted">${escape((b.blocked_at || "").slice(11, 19))}</td>
        <td>${escape(b.api_provider)}</td>
        <td>${b.requested_tokens || 0}</td>
        <td>${b.limit_value || 0}</td>
        <td>${escape(b.resolution || "pending")}</td>
      </tr>`).join("")}</tbody></table>` : `<p class="muted">No rate-limit blocks in 24h. ✅</p>`;

  // Caps editor
  const capsTable = (caps.caps || []).map((c) => `
    <tr>
      <td><code>${escape(c.scope)}</code></td>
      <td>$<input type="number" step="0.01" value="${c.cap_usd}" data-cap-field="cap_usd" data-scope="${escape(c.scope)}" style="width:90px"></td>
      <td>
        <select data-cap-field="behavior" data-scope="${escape(c.scope)}">
          ${["warn","haiku_force","hard_stop"].map(b => `<option ${b===c.behavior?"selected":""}>${b}</option>`).join("")}
        </select>
      </td>
      <td><input type="checkbox" ${c.enabled?"checked":""} data-cap-field="enabled" data-scope="${escape(c.scope)}"></td>
      <td><button class="btn ghost" data-cap-save="${escape(c.scope)}">Save</button></td>
    </tr>`).join("");

  return `
    ${stats}

    <div class="cost-grid two">
      <div class="cost-card">
        <h4>Daily heatmap (30d)</h4>
        <div class="cost-heatmap">${heat}</div>
        <div class="muted small">Each cell = one day, shaded by spend.</div>
      </div>
      <div class="cost-card">
        <h4>By source (7d)</h4>
        ${sourceBars}
      </div>
    </div>

    <div class="cost-grid two">
      <div class="cost-card">
        <h4>By intent (30d)</h4>
        ${byIntentTable}
      </div>
      <div class="cost-card">
        <h4>Top projects (30d)</h4>
        ${topProjTable}
      </div>
    </div>

    <div class="cost-grid two">
      <div class="cost-card">
        <h4>Sessions needing attention</h4>
        ${attnTable}
      </div>
      <div class="cost-card">
        <h4>Refund-worthy turns (30d)</h4>
        ${refundTable}
      </div>
    </div>

    <div class="cost-grid two">
      <div class="cost-card">
        <h4>Rate limits (live)</h4>
        ${rateLimitRows}
        <h4 style="margin-top:14px;">Recent blocks (24h)</h4>
        ${rateBlocksTable}
      </div>
      <div class="cost-card">
        <h4>Caps</h4>
        <table class="admin-table">
          <thead><tr><th>Scope</th><th>Cap (USD)</th><th>Behavior</th><th>On</th><th></th></tr></thead>
          <tbody>${capsTable || `<tr><td colspan="5" class="muted">No caps yet — apply migration.</td></tr>`}</tbody>
        </table>
      </div>
    </div>
  `;
}

function bindCapEditors(_capsResp) {
  const body = document.getElementById("cost-tab-body");
  body.querySelectorAll("[data-cap-save]").forEach((btn) => {
    btn.onclick = async () => {
      const scope = btn.dataset.capSave;
      const fields = body.querySelectorAll(`[data-scope="${scope}"]`);
      const patch = {};
      fields.forEach((f) => {
        const k = f.dataset.capField;
        patch[k] = f.type === "checkbox" ? f.checked
                 : f.type === "number"   ? Number(f.value) : f.value;
      });
      try {
        await api.patch(`/cost/caps/${encodeURIComponent(scope)}`, patch);
        toast.success(`Cap ${scope} saved`);
      } catch (e) {
        toast.error(`Save failed: ${e.message}`);
      }
    };
  });
}

function startPolling() { stopPolling(); load(); pollTimer = setInterval(load, 60000); }
function stopPolling()  { if (pollTimer) clearInterval(pollTimer); pollTimer = null; }

export function init() {
  document.getElementById("cost-tab-refresh").addEventListener("click", load);
  document.addEventListener("bridgedeck:tab", (e) => {
    if (e.detail.tab === "cost") startPolling();
    else stopPolling();
  });
}
