// Serve both sites locally, open each in Chromium, fail on any console error
// or page error, assert the headline and the sibling check, and write a
// screenshot per site to docs/screenshots/. CI runs it; `make render` runs it
// locally. Tests pass on things that are visibly wrong; this is where you
// look.
//
// Needs `playwright` resolvable from this directory (npm install --no-save
// playwright) and a Chromium it can find (npx playwright install chromium).

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const sides = { left: 8001, right: 8002 };
const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
};

function parseHeaders(text) {
  // Same parser the test suite has, so the headers the hosts would send are
  // the ones the local server sends. The CSP is enforced here too.
  const out = {};
  let current = null;
  for (const raw of text.split("\n")) {
    if (!raw.trim() || raw.trim().startsWith("#")) continue;
    if (!/^\s/.test(raw)) {
      current = raw.trim();
      out[current] = {};
    } else {
      const i = raw.indexOf(":");
      out[current][raw.slice(0, i).trim()] = raw.slice(i + 1).trim();
    }
  }
  return out;
}

function serve(side, port) {
  const dir = path.join(root, "sites", side, "public");
  const headers = parseHeaders(fs.readFileSync(path.join(dir, "_headers"), "utf8"));
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
    if (p.endsWith("/")) p += "index.html";
    const file = path.normalize(path.join(dir, p));
    let status = 200;
    let body;
    if (file.startsWith(dir) && fs.existsSync(file) && fs.statSync(file).isFile()) {
      body = fs.readFileSync(file);
    } else {
      status = 404;
      body = fs.readFileSync(path.join(dir, "404.html"));
      p = "/404.html";
    }
    const h = { "Content-Type": types[path.extname(p)] || "application/octet-stream", ...headers["/*"] };
    if (headers[p]) Object.assign(h, headers[p]);
    // Locally the sibling is on another port, so widen connect-src to it.
    const otherPort = side === "left" ? sides.right : sides.left;
    h["Content-Security-Policy"] = h["Content-Security-Policy"].replace(
      "connect-src 'self'",
      `connect-src 'self' http://localhost:${otherPort}`
    );
    res.writeHead(status, h);
    res.end(body);
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

const servers = await Promise.all(Object.entries(sides).map(([s, p]) => serve(s, p)));
const browser = await chromium.launch();
const shotsDir = path.join(root, "docs", "screenshots");
fs.mkdirSync(shotsDir, { recursive: true });
let failed = false;

for (const [side, port] of Object.entries(sides)) {
  const other = side === "left" ? "right" : "left";
  for (const scheme of ["dark", "light"]) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, colorScheme: scheme });
    const problems = [];
    let expecting404 = false; // the browser logs the 404 page's own status as a console error
    page.on("console", (m) => {
      if (m.type() !== "error") return;
      if (expecting404 && /status of 404/.test(m.text())) return;
      problems.push(`console: ${m.text()}`);
    });
    page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
    page.on("requestfailed", (r) => problems.push(`request failed: ${r.url()}`));
    await page.goto(`http://localhost:${port}/`, { waitUntil: "networkidle" });

    const h1 = (await page.textContent("h1")).replace(/\s+/g, " ").trim();
    if (h1 !== `The ${side[0].toUpperCase()}${side.slice(1)} One`) problems.push(`h1 reads ${JSON.stringify(h1)}`);

    await page.waitForFunction(() => document.getElementById("sibling-dot").dataset.state !== "pending");
    const sib = await page.textContent("#sibling-text");
    if (!sib.startsWith("online")) problems.push(`sibling check reads ${JSON.stringify(sib)} (both servers are up)`);

    // The orb is always animating, so Playwright never sees it "stable".
    await page.click("#orb", { force: true });
    const boops = await page.textContent("#boops");
    if (!/Booped once/.test(boops)) problems.push(`boop counter reads ${JSON.stringify(boops)}`);

    await page.click("#flip");
    const verdict = (await page.textContent("#verdict")).trim();
    if (!/^(LEFT|RIGHT)/.test(verdict)) problems.push(`flip verdict reads ${JSON.stringify(verdict)}`);
    if (verdict.startsWith(other.toUpperCase()) && !verdict.includes(`my${other}nut.org`)) {
      problems.push("a losing flip should link to the other side");
    }

    await page.click("#pledge");
    const pledge = await page.textContent("#pledge-text");
    if (!pledge.startsWith("Noted.")) problems.push(`pledge reads ${JSON.stringify(pledge)}`);

    // The 404 page must render too, with the same assets.
    expecting404 = true;
    const r = await page.goto(`http://localhost:${port}/definitely-not-here`, { waitUntil: "networkidle" });
    expecting404 = false;
    if (r.status() !== 404) problems.push(`404 page answered ${r.status()}`);
    if (!/Not here/.test(await page.textContent("h1"))) problems.push("404 page has the wrong headline");
    await page.goto(`http://localhost:${port}/`, { waitUntil: "networkidle" });
    await page.click("#flip"); // the reload cleared the verdict; show one in the screenshot

    const shot = path.join(shotsDir, `${side}-${scheme}.png`);
    await page.screenshot({ path: shot, fullPage: true });
    if (scheme === "dark") {
      // A phone-width pass of the same page, so the single-column layout is looked at too.
      await page.setViewportSize({ width: 390, height: 844 });
      await page.screenshot({ path: path.join(shotsDir, `${side}-phone.png`), fullPage: true });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
      if (overflow) problems.push("page scrolls horizontally at 390px");
    }
    if (problems.length) {
      failed = true;
      console.error(`✗ ${side} (${scheme})\n  ${problems.join("\n  ")}`);
    } else {
      console.log(`✓ ${side} (${scheme}) → ${path.relative(root, shot)}`);
    }
    await page.close();
  }
}

await browser.close();
for (const s of servers) s.close();
process.exit(failed ? 1 : 0);
