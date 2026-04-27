// Admin modal — paginated panels (Connection, Settings, Projects, Auto-approve,
// Action queue, Handoffs, Stats). Keeps things compact: each panel is a small
// inline render fn with its own load() + render() + bind().

import * as api from "./api.js";
import { toast } from "./toast.js";

const escape = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;");

const PANELS = {
  connection: { label: "Connection", render: renderConnection },
  settings:   { label: "Settings",   render: renderSettings   },
  projects:   { label: "Projects",   render: renderProjects   },
  "auto-approve": { label: "Auto-approve", render: renderAutoApprove },
  actions:    { label: "Action queue", render: renderActions  },
  handoffs:   { label: "Handoffs",   render: renderHandoffs   },
  stats:      { label: "Stats",      render: renderStats      },
  cost:       { label: "Cost",       render: renderCost       },
};

// --- Connection ----------------------------------------------------------

async function renderConnection(body) {
  body.innerHTML = `<h3>Connection</h3>
    <p>API URL: <code>${escape(api.config.apiUrl)}</code></p>
    <p>Admin key: <code>${api.getAdminKey() ? "set ✓" : "MISSING"}</code></p>
    <div style="margin: 14px 0;">
      <button class="btn ghost" id="conn-reset">Change admin key</button>
      <button class="btn ghost" id="conn-reload">Reload settings cache</button>
    </div>
    <h3>Health</h3>
    <pre id="conn-health" style="background:var(--bg-elev-2); padding:12px; border-radius:6px; max-height:240px; overflow:auto;">loading…</pre>`;

  document.getElementById("conn-reset").onclick = () => {
    api.setAdminKey("");
    document.getElementById("admin-modal").setAttribute("aria-hidden", "true");
    document.getElementById("key-gate").setAttribute("aria-hidden", "false");
  };
  document.getElementById("conn-reload").onclick = async () => {
    try {
      await api.post("/settings/reset");
      toast.success("Reload triggered");
    } catch (e) {
      toast.error(`Reload failed: ${e.message}`);
    }
  };
  try {
    const h = await api.health();
    document.getElementById("conn-health").textContent = JSON.stringify(h, null, 2);
  } catch (e) {
    document.getElementById("conn-health").textContent = `health failed: ${e.message}`;
  }
}

// --- Settings ------------------------------------------------------------

async function renderSettings(body) {
  body.innerHTML = `<h3>Settings</h3><div id="settings-tree" class="muted">loading…</div>`;
  try {
    const all = await api.get("/settings");
    const ns = all && (all.settings || all);
    const html = Object.entries(ns).map(([namespace, kv]) => {
      const rows = Object.entries(kv || {}).map(([key, val]) => `
        <tr>
          <td>${escape(key)}</td>
          <td><code>${escape(JSON.stringify(val))}</code></td>
          <td><button class="btn ghost" data-edit data-ns="${escape(namespace)}" data-k="${escape(key)}" data-v='${escape(JSON.stringify(val))}'>Edit</button></td>
        </tr>
      `).join("");
      return `<details open><summary><b>${escape(namespace)}</b></summary>
        <table class="admin-table"><thead><tr><th>Key</th><th>Value</th><th></th></tr></thead><tbody>${rows}</tbody></table>
      </details>`;
    }).join("");
    document.getElementById("settings-tree").innerHTML = html;

    body.querySelectorAll("[data-edit]").forEach((b) => {
      b.onclick = async () => {
        const ns = b.dataset.ns, k = b.dataset.k;
        const cur = b.dataset.v;
        const next = prompt(`Edit ${ns}.${k} (JSON):`, cur);
        if (next == null) return;
        let parsed;
        try { parsed = JSON.parse(next); }
        catch { toast.error("Not valid JSON"); return; }
        try {
          await api.patch(`/settings/${encodeURIComponent(ns)}/${encodeURIComponent(k)}`, { namespace: ns, key: k, value: parsed });
          toast.success("Updated");
          renderSettings(body);
        } catch (e) {
          toast.error(`Update failed: ${e.message}`);
        }
      };
    });
  } catch (e) {
    document.getElementById("settings-tree").innerHTML = `<p>Failed: ${escape(e.message)}</p>`;
  }
}

// --- Projects ------------------------------------------------------------

async function renderProjects(body) {
  body.innerHTML = `<h3>Projects</h3>
    <button class="btn ghost" id="proj-sync">↻ Sync from Brain</button>
    <div id="proj-list" class="muted">loading…</div>`;
  document.getElementById("proj-sync").onclick = async () => {
    try { await api.post("/projects/sync"); toast.success("Sync requested"); renderProjects(body); }
    catch (e) { toast.error(`Sync failed: ${e.message}`); }
  };
  try {
    const r = await api.get("/projects");
    const list = r.projects || r || [];
    document.getElementById("proj-list").innerHTML = `
      <table class="admin-table">
        <thead><tr><th>Slug</th><th>Display</th><th>Repo</th><th>Active</th></tr></thead>
        <tbody>${list.map((p) => `
          <tr>
            <td>${escape(p.emoji || "")} ${escape(p.slug)}</td>
            <td>${escape(p.display_name || "")}</td>
            <td>${p.repo_url ? `<a href="${escape(p.repo_url)}" target="_blank">repo</a>` : ""}</td>
            <td>${p.is_active === false ? "—" : "✓"}</td>
          </tr>`).join("")}</tbody>
      </table>`;
  } catch (e) {
    document.getElementById("proj-list").innerHTML = `<p>Failed: ${escape(e.message)}</p>`;
  }
}

// --- Auto-approve --------------------------------------------------------

async function renderAutoApprove(body) {
  body.innerHTML = `<h3>Auto-approve rules</h3>
    <div id="ar-list" class="muted">loading…</div>`;
  try {
    const r = await api.get("/auto-approve");
    const list = r.rules || r || [];
    document.getElementById("ar-list").innerHTML = `
      <table class="admin-table">
        <thead><tr><th>Project</th><th>Mode</th><th>Pattern</th><th>Type</th><th>Per hr</th><th>Fired</th></tr></thead>
        <tbody>${list.map((rl) => `
          <tr>
            <td>${escape(rl.project_slug || "*")}</td>
            <td>${escape(rl.action || "allow")}</td>
            <td><code>${escape(rl.pattern)}</code></td>
            <td>${escape(rl.pattern_type)}</td>
            <td>${rl.max_per_hour ?? "∞"}</td>
            <td>${rl.fire_count ?? 0}</td>
          </tr>`).join("")}</tbody>
      </table>`;
  } catch (e) {
    document.getElementById("ar-list").innerHTML = `<p>Failed: ${escape(e.message)}</p>`;
  }
}

// --- Action queue --------------------------------------------------------

async function renderActions(body) {
  body.innerHTML = `<h3>Action queue</h3><div id="aq-list" class="muted">loading…</div>`;
  try {
    const r = await api.get("/actions");
    const list = r.actions || r || [];
    document.getElementById("aq-list").innerHTML = `
      <table class="admin-table">
        <thead><tr><th>Type</th><th>Project</th><th>Trigger</th><th>Status</th><th></th></tr></thead>
        <tbody>${list.map((a) => `
          <tr>
            <td>${escape(a.action_type)}</td>
            <td>${escape(a.target_project || "")}</td>
            <td>${escape(a.trigger_type)}</td>
            <td>${escape(a.status)}</td>
            <td>${a.status === "queued" ? `<button class="btn ghost" data-cancel="${escape(a.id)}">Cancel</button>` : ""}</td>
          </tr>`).join("")}</tbody>
      </table>`;
    body.querySelectorAll("[data-cancel]").forEach((b) => {
      b.onclick = async () => {
        try { await api.del(`/actions/${b.dataset.cancel}`); toast.success("Cancelled"); renderActions(body); }
        catch (e) { toast.error(e.message); }
      };
    });
  } catch (e) {
    document.getElementById("aq-list").innerHTML = `<p>Failed: ${escape(e.message)}</p>`;
  }
}

// --- Handoffs ------------------------------------------------------------

async function renderHandoffs(body) {
  body.innerHTML = `<h3>Recent handoffs</h3><div id="ho-list" class="muted">loading…</div>`;
  try {
    const r = await api.get("/handoffs");
    const list = r.handoffs || r || [];
    document.getElementById("ho-list").innerHTML = `
      <table class="admin-table">
        <thead><tr><th>Project</th><th>Confidence</th><th>Brain sync</th><th>When</th></tr></thead>
        <tbody>${list.map((h) => `
          <tr>
            <td>${escape(h.project_slug)}</td>
            <td>${(h.confidence ?? 0).toFixed(2)}</td>
            <td>${escape(h.brain_sync || "?")}</td>
            <td class="muted">${escape((h.created_at || "").slice(0, 19).replace("T", " "))}</td>
          </tr>`).join("")}</tbody>
      </table>`;
  } catch (e) {
    document.getElementById("ho-list").innerHTML = `<p>Failed: ${escape(e.message)}</p>`;
  }
}

// --- Stats ---------------------------------------------------------------

async function renderStats(body) {
  body.innerHTML = `<h3>Empire stats</h3><pre id="stats-out" style="background:var(--bg-elev-2); padding:12px; border-radius:6px; max-height:60vh; overflow:auto;">loading…</pre>`;
  try {
    const r = await api.get("/stats/empire");
    document.getElementById("stats-out").textContent = JSON.stringify(r, null, 2);
  } catch (e) {
    document.getElementById("stats-out").textContent = `Failed: ${e.message}`;
  }
}

// --- Cost ----------------------------------------------------------------

async function renderCost(body) {
  body.innerHTML = `
    <h3>Cost intelligence</h3>
    <div class="cost-grid">
      <div class="cost-card"><h4>Today</h4><div class="cost-stat" id="c-today">…</div></div>
      <div class="cost-card"><h4>Last 7 days</h4><div class="cost-stat" id="c-week">…</div></div>
      <div class="cost-card"><h4>Last 30 days</h4><div class="cost-stat" id="c-month">…</div></div>
      <div class="cost-card"><h4>Active burn</h4><div class="cost-stat" id="c-burn">…</div></div>
    </div>

    <h3 style="margin-top:18px;">Daily heatmap (30d)</h3>
    <div class="cost-heatmap" id="c-heat"></div>

    <h3 style="margin-top:18px;">By source (7d)</h3>
    <div id="c-source"></div>

    <h3 style="margin-top:18px;">By project (7d)</h3>
    <table class="admin-table"><thead><tr><th>Project</th><th>Total</th><th>Bridge</th><th>Summarizer</th><th>Intent</th><th>Other</th></tr></thead><tbody id="c-proj-body"></tbody></table>

    <h3 style="margin-top:18px;">Top sessions (30d)</h3>
    <table class="admin-table"><thead><tr><th>Session</th><th>Total</th></tr></thead><tbody id="c-sess-body"></tbody></table>

    <h3 style="margin-top:18px;">Caps</h3>
    <table class="admin-table"><thead><tr><th>Scope</th><th>Cap (USD)</th><th>Behavior</th><th>Enabled</th><th></th></tr></thead><tbody id="c-caps-body"></tbody></table>
  `;

  try {
    const [summary, timeline, bySource, byProj, caps] = await Promise.all([
      api.get("/cost/summary"),
      api.get("/cost/timeline", { days: 30 }),
      api.get("/cost/by-source", { days: 7 }),
      api.get("/cost/by-project", { days: 7 }),
      api.get("/cost/caps"),
    ]);
    const live = await api.get("/cost/live").catch(() => ({}));

    document.getElementById("c-today").textContent = "$" + (summary.today || 0).toFixed(2);
    document.getElementById("c-week").textContent  = "$" + (summary.week  || 0).toFixed(2);
    document.getElementById("c-month").textContent = "$" + (summary.month || 0).toFixed(2);
    document.getElementById("c-burn").textContent  = "$" + ((live.active_sessions_burn_rate) || 0).toFixed(2);

    // Heatmap — bin each day's total into 5 buckets relative to max.
    const days = (timeline.timeline || []);
    const max = Math.max(0.0001, ...days.map((d) => d.total || 0));
    document.getElementById("c-heat").innerHTML = days.map((d) => {
      const ratio = (d.total || 0) / max;
      const bin = ratio === 0 ? 0 : ratio < 0.25 ? 1 : ratio < 0.5 ? 2 : ratio < 0.75 ? 3 : 4;
      return `<div class="cell" data-bin="${bin}" title="${d.date}: $${(d.total||0).toFixed(4)}"></div>`;
    }).join("");

    // By source — horizontal bars.
    const src = bySource.sources || {};
    const srcMax = Math.max(0.0001, ...Object.values(src).map((v) => Number(v) || 0));
    document.getElementById("c-source").innerHTML = Object.entries(src)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => {
        const w = Math.round((Number(v) / srcMax) * 100);
        return `<div class="cost-bar"><span style="width:90px">${escape(k)}</span>` +
               `<div class="fill" style="width:${w}%"></div>` +
               `<span>$${Number(v).toFixed(4)}</span></div>`;
      }).join("");

    document.getElementById("c-proj-body").innerHTML = (byProj.projects || []).map((p) => `
      <tr>
        <td>${escape(p.project_slug)}</td>
        <td>$${(p.total || 0).toFixed(4)}</td>
        <td>$${(p.bridge || 0).toFixed(4)}</td>
        <td>$${(p.summarizer || 0).toFixed(4)}</td>
        <td>$${(p.intent || 0).toFixed(4)}</td>
        <td>$${(p.other || 0).toFixed(4)}</td>
      </tr>`).join("");

    document.getElementById("c-sess-body").innerHTML = (summary.top_sessions || []).map((s) => `
      <tr><td><code>${escape(s.session_id)}</code></td><td>$${(s.total_usd || 0).toFixed(4)}</td></tr>
    `).join("");

    document.getElementById("c-caps-body").innerHTML = (caps.caps || []).map((c) => `
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
          toast.success("Cap saved");
        } catch (e) {
          toast.error(`Save failed: ${e.message}`);
        }
      };
    });
  } catch (e) {
    body.innerHTML += `<p class="muted">Failed: ${escape(e.message)}</p>`;
  }
}

// --- Init ----------------------------------------------------------------

export function init() {
  const modal = document.getElementById("admin-modal");
  const body = document.getElementById("admin-panel-body");

  document.getElementById("open-admin").addEventListener("click", () => {
    modal.setAttribute("aria-hidden", "false");
    PANELS.connection.render(body);
  });

  document.querySelectorAll(".admin-nav-item").forEach((el) => {
    el.addEventListener("click", () => {
      document.querySelectorAll(".admin-nav-item").forEach((x) => x.classList.remove("active"));
      el.classList.add("active");
      const key = el.dataset.adminPanel;
      const panel = PANELS[key];
      if (panel) panel.render(body);
    });
  });
}
