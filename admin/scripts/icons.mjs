// Render the brand mark (the four bars of icon.svg) to the PNG icons the PWA
// manifest and iOS need. Uses the installed Google Chrome through Playwright.
//
//   node scripts/icons.mjs            # writes into ../src/ira/web/static
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";

const out = resolve(process.argv[2] || "../src/ira/web/static");

// The maskable icon fills the whole square and keeps the bars inside the safe zone.
const mark = (maskable) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="${maskable ? 0 : 8}" fill="#1f6f5c"/>
  <g transform="translate(16 16) scale(${maskable ? 0.8 : 1}) translate(-16 -16)">
    <rect x="7" y="13" width="3" height="6" rx="1.5" fill="#fff"/>
    <rect x="12" y="9" width="3" height="14" rx="1.5" fill="#fff"/>
    <rect x="17" y="6" width="3" height="20" rx="1.5" fill="#fff"/>
    <rect x="22" y="11" width="3" height="10" rx="1.5" fill="#fff"/>
  </g>
</svg>`;

const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage();
const icons = [
  ["icon-512.png", 512, false],
  ["icon-192.png", 192, false],
  ["icon-180.png", 180, false],
  ["icon-512-maskable.png", 512, true],
];
for (const [name, size, maskable] of icons) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(
    `<!doctype html><html><head><style>html,body{margin:0;background:transparent}` +
      `svg{display:block;width:${size}px;height:${size}px}</style></head><body>${mark(maskable)}</body></html>`,
  );
  const png = await page.screenshot({ omitBackground: true, type: "png" });
  writeFileSync(resolve(out, name), png);
  console.log(`${name}: ${png.length} bytes`);
}
await browser.close();
