// History modal — paginated history_log viewer with category filter + search.
import * as api from "./api.js";
import { toast } from "./toast.js";

const escape = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

async function loadCategories() {
  const sel = document.getElementById("history-category");
  try {
    const r = await api.get("/history/categories");
    const cats = r.categories || r || [];
    sel.innerHTML = `<option value="">all categories</option>` +
      cats.map((c) => `<option value="${escape(c)}">${escape(c)}</option>`).join("");
  } catch {}
}

async function refresh() {
  const list = document.getElementById("history-list");
  const q = document.getElementById("history-q").value.trim();
  const cat = document.getElementById("history-category").value;
  list.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const params = { limit: 200 };
    if (cat) params.category = cat;
    if (q) params.q = q;
    const r = await api.get("/history", params);
    const events = r.events || r || [];
    if (!events.length) {
      list.innerHTML = `<p class="muted">No events.</p>`;
      return;
    }
    list.innerHTML = events.map((e) => `
      <div class="history-row">
        <span class="ts">${escape((e.created_at || "").slice(11, 19))}</span>
        <span class="cat">${escape(e.event_category || "")}</span>
        <span><b>${escape(e.event_type)}</b> · ${escape(e.action || "")} ${e.project_slug ? `· <span class="muted">${escape(e.project_slug)}</span>` : ""}</span>
        <span class="out-${escape(e.outcome || "success")}">${escape(e.outcome || "")}</span>
      </div>
    `).join("");
  } catch (e) {
    list.innerHTML = `<p>Failed: ${escape(e.message)}</p>`;
  }
}

export function init() {
  document.getElementById("open-history").addEventListener("click", async () => {
    document.getElementById("history-modal").setAttribute("aria-hidden", "false");
    await loadCategories();
    refresh();
  });
  document.getElementById("history-refresh").addEventListener("click", refresh);
  document.getElementById("history-q").addEventListener("keydown", (e) => {
    if (e.key === "Enter") refresh();
  });
  document.getElementById("history-category").addEventListener("change", refresh);
}
