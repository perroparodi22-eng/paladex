// Developer helper: node scripts/dev/screenshot.cjs <url> <out.png> [width] [height]
const { chromium } = require('playwright');
(async () => {
  const [,, url, out, w, h] = process.argv;
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: +(w||1440), height: +(h||900) } });
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) });
  await p.goto(url, { waitUntil: 'networkidle' });
  await p.waitForTimeout(800);
  await p.screenshot({ path: out, fullPage: true });
  if (errors.length) console.log('ERRORS:', errors.join('\n'));
  await b.close();
})();
