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
    const button = document.querySelector("#customerReadinessButton");
    return Boolean(button && button.offsetParent !== null);
  }, null, { timeout: 3000 });
  await page.click("#customerReadinessButton");
  await page.waitForFunction(() => Boolean(document.querySelector(".customer-readiness-card")), null, { timeout: 60000 });
  const state = await page.evaluate(() => {
    const card = document.querySelector(".customer-readiness-card");
    const text = card?.textContent || "";
    const raw = document.querySelector("#modalMarkdown")?.textContent || "";
    return {
      uiVersion: document.querySelector("#uiVersion")?.textContent || "",
      modalTitle: document.querySelector("#modalTitle")?.textContent || "",
      cardVisible: Boolean(card && card.offsetParent !== null),
      cardText: text,
      itemCount: document.querySelectorAll(".customer-readiness-item").length,
      hasHealth: /Service health/.test(text),
      hasActivation: /Activation/.test(text),
      hasModel: /Ask Yoda model/.test(text),
      hasStorage: /Durable storage/.test(text),
      hasWeekly: /Weekly outcomes/.test(text),
      hasResolver: /Resolver pending state/.test(text),
      hasTargets: /Configured targets/.test(text),
      hasNextStep: /Safe next step:/.test(text),
      hasPrivacy: /private|Aggregate/.test(text),
      rawHasReadiness: /"schema_version": 1/.test(raw) && /"read_only": true/.test(raw),
      leaksSecret: new RegExp("api[_-]?key|sk-[A-Za-z0-9]{20,}|authorization|raw prompt|/Users/", "i").test(raw),
      hasRepairButton: /auto-repair|Repair now|Approve resolver/.test(text),
    };
  });
  console.log(JSON.stringify(state, null, 2));
  if (
    state.uiVersion !== "V1.0.183"
    || state.modalTitle !== "Customer readiness"
    || !state.cardVisible
    || state.itemCount < 7
    || !state.hasHealth
    || !state.hasActivation
    || !state.hasModel
    || !state.hasStorage
    || !state.hasWeekly
    || !state.hasResolver
    || !state.hasTargets
    || !state.hasNextStep
    || !state.hasPrivacy
    || !state.rawHasReadiness
    || state.leaksSecret
    || state.hasRepairButton
  ) {
    throw new Error(`Customer readiness card did not meet acceptance: ${JSON.stringify(state)}`);
  }
} finally {
  await browser.close();
}
