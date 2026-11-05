// Developer helper: node scripts/dev/screenshot.cjs <url> <out.png> [width] [height] [mobile] [it|en]
// "mobile" emulates a phone (touch, mobile viewport) at the given size, e.g. 390 844 mobile.
// "it" / "en" opens the interface in that language (as chosen in the browser), e.g. 1440 900 desktop en.
const { chromium } = require('playwright');
(async () => {
  const [,, url, out, w, h, mode, lang] = process.argv;
  const b = await chromium.launch();
  const mobile = mode === 'mobile';
  const p = await b.newPage({ viewport: { width: +(w||1440), height: +(h||900) }, ...(mobile ? { isMobile: true, hasTouch: true } : {}) });
  if (lang === 'it' || lang === 'en') await p.addInitScript((l) => localStorage.setItem('paladex.lang', l), lang);
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()) });
  await p.goto(url, { waitUntil: 'networkidle' });
  await p.waitForTimeout(800);
  // Horizontal overflow of the page itself (wide content must scroll inside its own box).
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (overflow > 0) console.log(`HORIZONTAL OVERFLOW: ${overflow}px`);
  await p.screenshot({ path: out, fullPage: true });
  if (errors.length) console.log('ERRORS:', errors.join('\n'));
  await b.close();
})();
