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
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, ignoreHTTPSErrors: true });

try {
  await page.goto(appUrl, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.__MEMORY_STARGRAPH__?.getState().graph?.nodes?.length > 0, null, { timeout: 120000 });
  await page.waitForFunction(() => Boolean(window.__MEMORY_STARGRAPH__?.getState().focusSlug), null, { timeout: 30000 });
  await page.click("#navSearchButton");
  await page.waitForFunction(() => {
    const input = document.querySelector("#searchInput");
    const flyout = document.querySelector("#searchFlyout");
    return Boolean(input && flyout && !flyout.hidden && !input.disabled && input.offsetParent !== null);
  }, null, { timeout: 1000 });
  await page.fill("#searchInput", "optional timeout telemetry is not a todo");
  const state = await page.evaluate(() => {
    const input = document.querySelector("#searchInput");
    const flyout = document.querySelector("#searchFlyout");
    const nav = document.querySelector("#navSearchButton");
    return {
      uiVersion: document.querySelector("#uiVersion")?.textContent || "",
      flyoutHidden: flyout?.hidden,
      inputDisabled: input?.disabled,
      inputVisible: Boolean(input && input.offsetParent !== null),
      inputFocused: document.activeElement === input,
      inputValue: input?.value || "",
      navExpanded: nav?.getAttribute("aria-expanded"),
      navOpen: nav?.classList.contains("is-open"),
      followupsOrder: [...document.querySelectorAll(".nav-rail > .nav-rail-button")].map((item) => item.id),
      followupsCount: document.querySelectorAll("#autopilotFindingsButton").length,
    };
  });
  const resolverIndex = state.followupsOrder.indexOf("navResolverButton");
  const ok = state.uiVersion
    && !state.flyoutHidden
    && !state.inputDisabled
    && state.inputVisible
    && state.inputFocused
    && state.inputValue === "optional timeout telemetry is not a todo"
    && state.navExpanded === "true"
    && state.navOpen
    && resolverIndex >= 0
    && state.followupsOrder[resolverIndex + 1] === "autopilotFindingsButton"
    && state.followupsOrder[resolverIndex + 2] === "navSettingsButton"
    && state.followupsCount === 1;
  console.log(JSON.stringify(state, null, 2));
  if (!ok) throw new Error(`Search rail did not open an enabled focused surface: ${JSON.stringify(state)}`);
} finally {
  await browser.close();
}
