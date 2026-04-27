// Main entry point — wires tabs, modals, key gate, health pill.
import * as api from "./api.js";
import { toast } from "./toast.js";
import * as monitor from "./monitor.js";
import * as terminal from "./terminal.js";
import * as bridge from "./bridge.js";
import * as admin from "./admin.js";
import * as history from "./history.js";

document.getElementById("version-tag").textContent = "v" + api.config.version;

// --- Admin-key gate ------------------------------------------------------
function showKeyGate() {
  document.getElementById("key-gate-api").textContent = api.config.apiUrl;
  document.getElementById("admin-key-input").value = api.getAdminKey() || "";
  document.getElementById("key-gate").setAttribute("aria-hidden", "false");
}
function hideKeyGate() {
  document.getElementById("key-gate").setAttribute("aria-hidden", "true");
}
if (!api.getAdminKey()) {
  showKeyGate();
} else {
  hideKeyGate();
}
document.getElementById("admin-key-save").addEventListener("click", () => {
  const v = document.getElementById("admin-key-input").value.trim();
  if (!v) {
    toast.error("Key required.");
    return;
  }
  api.setAdminKey(v);
  hideKeyGate();
  toast.success("Saved");
  pollHealth();
});

// --- Tab switching -------------------------------------------------------
document.querySelectorAll(".tab[data-tab]").forEach((tab) => {
  tab.addEventListener("click", () => {
    const name = tab.dataset.tab;
    document.querySelectorAll(".tab[data-tab]").forEach((t) => t.setAttribute("aria-selected", t === tab ? "true" : "false"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.dataset.active = "false");
    document.getElementById(`panel-${name}`).dataset.active = "true";
    document.dispatchEvent(new CustomEvent("bridgedeck:tab", { detail: { tab: name } }));
  });
});

// --- Modals close on backdrop / [data-close] -----------------------------
document.querySelectorAll(".modal").forEach((m) => {
  m.addEventListener("click", (e) => {
    if (e.target === m) m.setAttribute("aria-hidden", "true");
  });
});
document.querySelectorAll("[data-close]").forEach((b) => {
  b.addEventListener("click", () => {
    document.getElementById(b.dataset.close).setAttribute("aria-hidden", "true");
  });
});

// --- Health pill ---------------------------------------------------------
async function pollHealth() {
  const dot = document.querySelector(".health-dot");
  const label = document.getElementById("health-label");
  try {
    const h = await api.health();
    const ok = h.healthy && h.brain === "ok" && h.supabase === "ok";
    const bad = h.supabase === "down" || h.brain === "down";
    dot.dataset.status = ok ? "ok" : bad ? "down" : "degraded";
    label.textContent = `api ${h.version || ""} · sb:${h.supabase} br:${h.brain} w:${h.watcher}`;
  } catch (e) {
    dot.dataset.status = "down";
    label.textContent = `api unreachable`;
  }
}
document.getElementById("health-pill").addEventListener("click", () => {
  document.getElementById("open-admin").click();
});
pollHealth();
setInterval(pollHealth, 30_000);

// --- Cost pill (poll /cost/live every 5s) --------------------------------
const COST_WARN = 0.8; // 80% of empire_daily cap
const COST_OVER = 1.0;
async function pollCostLive() {
  try {
    const live = await api.get("/cost/live");
    document.getElementById("today-spend").textContent = (live.today || 0).toFixed(2);

    const caps = await api.get("/cost/caps").catch(() => ({ caps: [] }));
    const empireDaily = (caps.caps || []).find((c) => c.scope === "empire_daily");
    const cap = empireDaily ? Number(empireDaily.cap_usd) : 0;
    const pill = document.getElementById("cost-pill");
    if (cap > 0) {
      const ratio = (live.today || 0) / cap;
      pill.dataset.state = ratio >= COST_OVER ? "over" : ratio >= COST_WARN ? "warn" : "ok";
      pill.title = `$${(live.today || 0).toFixed(2)} of $${cap.toFixed(2)} empire_daily cap`;
    }
  } catch (e) {
    // silent — cost is non-critical
  }
}
document.getElementById("cost-pill").addEventListener("click", () => {
  document.getElementById("open-admin").click();
  setTimeout(() => {
    const tab = document.querySelector('.admin-nav-item[data-admin-panel="cost"]');
    if (tab) tab.click();
  }, 50);
});
pollCostLive();
setInterval(pollCostLive, 5000);

// --- Mount feature modules -----------------------------------------------
monitor.init();
terminal.init();
bridge.init();
admin.init();
history.init();
