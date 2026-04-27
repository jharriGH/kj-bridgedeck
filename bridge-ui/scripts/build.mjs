// Pre-deploy step: write a small `js/config.js` snippet that the index.html
// will load before app.js. Lets you swap API_URL via env without touching
// the static files.
//
// Usage:
//   API_URL=https://kj-bridgedeck-api.onrender.com node scripts/build.mjs
//
// On Cloudflare Pages, set env var API_URL in the dashboard and use
// `npm run build` as the build command.
import { writeFileSync, readFileSync } from "node:fs";

const apiUrl = process.env.API_URL || "https://kj-bridgedeck-api.onrender.com";
const version = process.env.UI_VERSION || "1.0.0";

const snippet = `// Generated at build time — do not edit.
window.BRIDGEDECK_CONFIG = {
  API_URL: ${JSON.stringify(apiUrl)},
  VERSION: ${JSON.stringify(version)}
};
`;
writeFileSync("./dist/js/config.js", snippet);

// Patch index.html to include the config script before app.js.
const html = readFileSync("./dist/index.html", "utf8");
const tag = '<script src="/js/config.js"></script>';
let next = html;
if (!html.includes(tag)) {
  next = html.replace(
    /<script type="module" src="\/js\/app\.js"><\/script>/,
    `${tag}\n  <script type="module" src="/js/app.js"></script>`
  );
  writeFileSync("./dist/index.html", next);
}
console.log(`[build] API_URL=${apiUrl}  VERSION=${version}`);
