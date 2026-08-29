/**
 * Regenerates docs/screenshots/ from a locally running NEXORA.
 *
 *   1. terminal A:  cd apps/api && PYTHONPATH=../.. venv/Scripts/python -m uvicorn nexora.main:app --port 8000
 *   2. terminal B:  cd apps/web && npm run dev
 *   3. terminal C:  node docs/capture-screenshots.mjs
 *
 * Drives headless Chrome over CDP. Shots are taken against MOCK mode with a real
 * Gemini key, so a mission actually completes — no account data, no spend beyond
 * a few Gemini calls.
 */
import { spawn } from "child_process";
import fs from "fs";

const CHROME =
  process.env.CHROME ||
  "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PORT = 9340;
const APP = process.env.APP_URL || "http://localhost:3000";
const OUT = "docs/screenshots";
const W = 1440, H = 1024;
const GOAL =
  "Plan 3 days in Kyoto: a travel guide document, a day-by-day slide deck, and an itemised budget spreadsheet in USD.";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
fs.mkdirSync(OUT, { recursive: true });

import os from "os";
import path from "path";
const PROFILE = fs.mkdtempSync(path.join(os.tmpdir(), "nx-shots-"));
const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${PORT}`, "--remote-allow-origins=*",
  "--disable-gpu", "--hide-scrollbars", `--window-size=${W},${H}`, "--no-first-run",
  "--no-default-browser-check", `--user-data-dir=${PROFILE}`, "about:blank",
], { stdio: "ignore" });

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const p = list.find((t) => t.type === "page");
      if (p?.webSocketDebuggerUrl) return p.webSocketDebuggerUrl;
    } catch {}
    await sleep(250);
  }
  throw new Error("Chrome CDP did not come up");
}

const ws = new WebSocket(await target());
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0;
const pending = new Map();
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
});
const cdp = (method, params = {}) =>
  new Promise((res) => { const n = ++id; pending.set(n, res); ws.send(JSON.stringify({ id: n, method, params })); });

await cdp("Page.enable");
await cdp("Runtime.enable");
await cdp("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 2, mobile: false });

const go = async (url) => { await cdp("Page.navigate", { url }); await sleep(2500); };
const ev=(expr)=>cdp("Runtime.evaluate",{expression:expr,awaitPromise:true,returnByValue:true}).then(r=>r?.result?.value);
const shot = async (name) => {
  const { data } = await cdp("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  fs.writeFileSync(`${OUT}/${name}.png`, Buffer.from(data, "base64"));
  console.log("saved", name);
};

// 1 — landing
await go(APP);
await shot("01-landing");

// 2 — launch a mission, capture it once the workforce is executing
await ev(`(()=>{const i=document.querySelector('input[placeholder*="accomplish"]');
  const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  set.call(i,${JSON.stringify(GOAL)}); i.dispatchEvent(new Event('input',{bubbles:true}));
  [...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Launch').click();})()`);
for (let i = 0; i < 40; i++) {
  await sleep(4000);
  if (await ev(`/WORKFORCE .* SPECIALISTS|Executing the plan/.test(document.body.innerText)`)) break;
}
await sleep(3000);
await shot("02-mission-running");

// 3 — wait for a terminal state, capture the completion view
for (let i = 0; i < 40; i++) {
  const done = await ev(`/Mission (Complete|Failed)/.test(document.body.innerText)`);
  if (done) break;
  await sleep(5000);
}
await sleep(1500);
await shot("03-mission-complete");

// 4 — capability explorer
await go(`${APP}/explorer`);
await shot("04-capability-explorer");

// 5 — architecture diagram
await go("file://" + process.cwd().replace(/\\/g, "/") + "/docs/architecture.svg");
await shot("05-architecture");

ws.close();
chrome.kill();
console.log("done → docs/screenshots/");
process.exit(0);
