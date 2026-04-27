// Tiny toast helper.
const root = () => document.getElementById("toast");

function show(text, kind = "info", ms = 3500) {
  const el = document.createElement("div");
  el.className = `toast-item ${kind}`;
  el.textContent = text;
  root().appendChild(el);
  setTimeout(() => el.remove(), ms);
}

export const toast = {
  info: (t) => show(t, "info"),
  error: (t) => show(t, "error", 5000),
  success: (t) => show(t, "success"),
};
