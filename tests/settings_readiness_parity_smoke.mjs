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
const screenshotPath = process.env.MEMORY_STARGRAPH_SCREENSHOT_PATH || "";

function outcomeStatusLabel(status) {
  const clean = String(status || "unknown").replace(/_/g, " ");
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

const browser = await chromium.launch({ headless: true, executablePath: chromePath });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true });
const settingsResponses = new Map();

page.on("response", async (response) => {
  const url = response.url();
  if (!url.includes("/api/memory-value-digest") && !url.includes("/api/customer-readiness")) return;
  if (!url.includes("settings_request=")) return;
  try {
    const parsed = new URL(url);
    const requestId = parsed.searchParams.get("settings_request") || "";
    if (!requestId) return;
    const kind = parsed.pathname.includes("memory-value-digest") ? "digest" : "readiness";
    const current = settingsResponses.get(requestId) || {};
    current[kind] = await response.json();
    settingsResponses.set(requestId, current);
  } catch {
    // Ignore unrelated or malformed responses; the final assertion requires both payloads.
  }
});

try {
  await page.goto(appUrl, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.__MEMORY_STARGRAPH__?.getState().graph?.nodes?.length > 0, null, { timeout: 120000 });
  await page.click("#navSettingsButton");
  await page.waitForFunction(() => {
    const panel = document.querySelector("#settingsFlyout");
    const cards = document.querySelector("#settingsEvidenceCards");
    return Boolean(
      panel
        && panel.hidden === false
        && cards?.dataset.requestId
        && panel.querySelector(".verified-outcomes-card")
        && panel.querySelector(".customer-readiness-card")
    );
  }, null, { timeout: 60000 });
  const settledRequestId = await page.locator("#settingsEvidenceCards").getAttribute("data-request-id");
  await page.waitForFunction((requestId) => {
    const cards = document.querySelector("#settingsEvidenceCards");
    return Boolean(
      requestId
        && cards?.dataset.requestId === requestId
        && cards.querySelector(".verified-outcomes-card")
        && cards.querySelector(".customer-readiness-card")
    );
  }, settledRequestId, { timeout: 1000 });

  const uiState = await page.evaluate(() => {
    const cards = document.querySelector("#settingsEvidenceCards");
    const digestCard = cards?.querySelector(".verified-outcomes-card");
    const readinessCard = cards?.querySelector(".customer-readiness-card");
    return {
      requestId: cards?.dataset.requestId || "",
      refreshedAt: cards?.dataset.refreshedAt || "",
      digestSubtitle: digestCard?.querySelector(".verified-outcomes-header p")?.textContent || "",
      digestStatus: digestCard?.querySelector(".verified-outcomes-status")?.textContent || "",
      readinessSubtitle: readinessCard?.querySelector(".customer-readiness-header p")?.textContent || "",
      readinessStatus: readinessCard?.querySelector(".customer-readiness-status")?.textContent || "",
      targetLine: Array.from(readinessCard?.querySelectorAll(".customer-readiness-privacy") || [])
        .map((node) => node.textContent || "")
        .find((text) => text.startsWith("Configured targets:")) || "",
      text: cards?.textContent || "",
      leaksSecret: new RegExp("api[_-]?key|sk-[A-Za-z0-9]{20,}|authorization|raw prompt|/Users/", "i").test(cards?.textContent || ""),
      refreshButtonVisible: Boolean(cards?.querySelector('button[aria-label="Refresh weekly outcomes and customer readiness"]')?.offsetParent),
    };
  });
  const apiState = settingsResponses.get(settledRequestId);
  if (!apiState?.digest || !apiState?.readiness) {
    throw new Error(`Missing captured Settings API payloads for request ${settledRequestId}`);
  }

  const outcomes = apiState.digest?.verified_memory_outcomes || {};
  const outcomeCounts = outcomes.summary_counts || {};
  const readinessCounts = apiState.readiness?.summary_counts || {};
  const targetEvidence = apiState.readiness?.target_evidence || {};
  const configured = targetEvidence.configured_remote || {};
  const local = targetEvidence.local || {};
  const expected = {
    digestSubtitle: `${outcomeCounts.gates_passed ?? 0}/${outcomeCounts.gates_total ?? 0} gates passed · ${outcomeStatusLabel(outcomes.status)}`,
    digestStatus: outcomeStatusLabel(outcomes.status),
    readinessSubtitle: `${readinessCounts.ready ?? 0}/${readinessCounts.checks_total ?? 0} checks ready · ${outcomeStatusLabel(apiState.readiness?.status)}`,
    readinessStatus: outcomeStatusLabel(apiState.readiness?.status),
    targetLine: `Configured targets: ${configured.verified_target_count ?? 0}/${configured.configured_target_count ?? 0} attested · ${outcomeStatusLabel(configured.status || targetEvidence.status)} · local ${outcomeStatusLabel(local.status)}`,
  };
  const result = { uiState, expected };
  console.log(JSON.stringify(result, null, 2));
  if (
    !uiState.requestId
    || !uiState.refreshedAt
    || !uiState.refreshButtonVisible
    || uiState.digestSubtitle !== expected.digestSubtitle
    || uiState.digestStatus !== expected.digestStatus
    || uiState.readinessSubtitle !== expected.readinessSubtitle
    || uiState.readinessStatus !== expected.readinessStatus
    || uiState.targetLine !== expected.targetLine
    || uiState.leaksSecret
  ) {
    throw new Error(`Settings readiness cards did not match current API payloads: ${JSON.stringify(result)}`);
  }
  if (screenshotPath) {
    await page.screenshot({ path: screenshotPath, fullPage: true });
  }
} finally {
  await browser.close();
}
