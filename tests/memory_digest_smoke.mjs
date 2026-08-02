import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const playwrightCandidates = [
  process.env.PLAYWRIGHT_MODULE,
  "playwright",
  ...(process.env.PATH || "")
    .split(path.delimiter)
    .filter((entry) => path.basename(entry) === ".bin")
    .map((entry) => path.join(path.dirname(entry), "playwright")),
].filter(Boolean);

let chromium;
let loadError;
for (const candidate of playwrightCandidates) {
  try {
    ({ chromium } = require(candidate));
    break;
  } catch (error) {
    loadError = error;
  }
}
if (!chromium) {
  throw new Error(`Unable to load Playwright. Last error: ${loadError?.message || "unknown"}`);
}

const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const appUrl = process.env.MEMORY_STARGRAPH_URL || "https://127.0.0.1:8788";
const browser = await chromium.launch({ headless: true, executablePath: chromePath });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true });

try {
  await page.goto(appUrl, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.__MEMORY_STARGRAPH__?.getState().graph?.nodes?.length > 0, null, { timeout: 120000 });
  await page.hover("#navSettingsButton");
  await page.waitForFunction(() => {
    const button = document.querySelector("#memoryDigestButton");
    return Boolean(button && button.offsetParent !== null);
  }, null, { timeout: 3000 });
  await page.click("#memoryDigestButton");
  await page.waitForFunction(() => Boolean(document.querySelector(".verified-outcomes-card")), null, { timeout: 60000 });
  const state = await page.evaluate(() => {
    const card = document.querySelector(".verified-outcomes-card");
    const text = card?.textContent || "";
    const raw = document.querySelector("#modalMarkdown")?.textContent || "";
    return {
      uiVersion: document.querySelector("#uiVersion")?.textContent || "",
      modalTitle: document.querySelector("#modalTitle")?.textContent || "",
      cardVisible: Boolean(card && card.offsetParent !== null),
      cardText: text,
      itemCount: document.querySelectorAll(".verified-outcome-item").length,
      hasRetrieval: /Retrieval quality benchmark/.test(text),
      hasAskYoda: /Model-backed Ask Yoda/.test(text),
      hasSearchParity: /Natural-language search parity/.test(text),
      hasCapture: text.includes("Capture Link capture/enrichment"),
      hasCurrentBlockerDistinction: /No current blockers|current blocker/.test(text) && /historical failure/.test(text),
      hasPrivacy: /private|Aggregate/.test(text),
      rawHasOutcomes: /verified_memory_outcomes/.test(raw),
      leaksSecret: new RegExp("api[_-]?key|sk-[A-Za-z0-9]{20,}|authorization|raw prompt|/Users/", "i").test(raw),
    };
  });
  console.log(JSON.stringify(state, null, 2));
  if (
    !state.uiVersion
    || state.modalTitle !== "Weekly outcomes digest"
    || !state.cardVisible
    || state.itemCount < 7
    || !state.hasRetrieval
    || !state.hasAskYoda
    || !state.hasSearchParity
    || !state.hasCapture
    || !state.hasCurrentBlockerDistinction
    || !state.hasPrivacy
    || !state.rawHasOutcomes
    || state.leaksSecret
  ) {
    throw new Error(`Weekly outcomes digest card did not meet acceptance: ${JSON.stringify(state)}`);
  }
} finally {
  await browser.close();
}
