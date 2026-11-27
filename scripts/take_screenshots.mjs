// Take the README screenshots of the running platform (Phase 10).
//
// With the API (port 8000) and the web app (port 5173) running on a demo database
// (python scripts/prepare_demo.py), from the frontend/ folder:
//
//   npm install --no-save playwright && npx playwright install chromium
//   node ../scripts/take_screenshots.mjs
//
// Writes docs/screenshots/*.png (1440 x 900, at twice the resolution for sharp text).
// Logs in with the demo logins; set WEB_URL for another address.

import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const WEB = process.env.WEB_URL ?? "http://localhost:5173";
const PASSWORD = "Demo-pass-123";
const OUT = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "docs",
  "screenshots",
);

async function signedIn(browser, email) {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  await page.goto(`${WEB}/login`);
  await page.fill("input[type=email]", email);
  await page.fill("input[type=password]", PASSWORD);
  await page.click("button[type=submit]");
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
  return page;
}

async function shot(page, path, name, prepare) {
  await page.goto(`${WEB}${path}`);
  await page.waitForLoadState("networkidle");
  if (prepare) await prepare(page);
  await page.waitForTimeout(800); // charts finish drawing
  await page.screenshot({ path: join(OUT, `${name}.png`) });
  console.log(`  ${name}.png  (${path})`);
}

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
try {
  const login = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  await shot(login, "/login", "login");

  const manager = await signedIn(browser, "manager@example.com");
  await shot(manager, "/", "dashboard-manager");
  await shot(manager, "/ml-insights", "ml-reorder");
  await shot(manager, "/ml-insights?view=models", "ml-models", (p) =>
    p.getByText(/^Predictions vs reality/).scrollIntoViewIfNeeded(),
  );
  await shot(manager, "/products/1", "product-forecast", (p) =>
    p
      .getByRole("region", { name: "Forecast and insights" })
      .scrollIntoViewIfNeeded(),
  );
  await shot(manager, "/reports", "reports");

  const staff = await signedIn(browser, "staff@example.com");
  await shot(staff, "/fulfillment", "fulfillment-staff");
  await shot(staff, "/warehouse", "warehouse-layout");

  const customer = await signedIn(browser, "customer@example.com");
  await shot(customer, "/", "dashboard-customer");
} finally {
  await browser.close();
}
