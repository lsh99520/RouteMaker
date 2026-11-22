const { chromium } = require('playwright');
(async () => {
  const FPS = 30, DUR = 70.5, N = Math.round(FPS * DUR);
  const b = await chromium.launch(); const p = await b.newPage({ viewport:{width:1920,height:1080} });
  await p.goto('file://' + process.cwd() + '/video.html'); await p.waitForFunction(() => window.__ready); await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(500);
  for (let i = 0; i < N; i++) {
    await p.evaluate(ms => window.seek(ms), i * 1000 / FPS);
    await p.screenshot({ path: `frames/f${String(i).padStart(5,'0')}.jpg`, type:'jpeg', quality:94 });
    if (i % 300 === 0) console.log('frame', i, '/', N);
  }
  await b.close(); console.log('done');
})();
