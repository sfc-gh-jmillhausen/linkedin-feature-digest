import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';

// Render the real SMTP fragment in memory. Never create a separate HTML report.
// Usage: node preview_qa.mjs <smtp-message.json> <qa-output-dir> [features=5] [posts=1|3]
// Needs a local Chrome started with --remote-debugging-port (CHROME_CDP, default 127.0.0.1:9222).
const input = process.argv[2];
assert.ok(input, 'Pass an absolute smtp-message.json path');
const batch = JSON.parse(await readFile(input, 'utf8'));
assert.equal(batch.scope, 'individual');
assert.equal(batch.messages.length, 1);
const message = batch.messages[0];
assert.ok(message.to && !message.cc && !message.bcc, 'Expected one direct recipient');
const expectedFeatures = Number(process.argv[4] || 5);
assert.ok(Number.isInteger(expectedFeatures) && expectedFeatures >= 1 && expectedFeatures <= 5);
const expectedPosts = Number(process.argv[5] || 1);
assert.ok([1, 3].includes(expectedPosts));
const output = process.argv[3];
assert.ok(output, 'Pass an output directory for QA screenshots');
const cdp = process.env.CHROME_CDP || '127.0.0.1:9222';
const url = 'about:blank';
await mkdir(output, { recursive: true });
const target = await (await fetch(`http://${cdp}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' })).json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
let sequence = 0;
const pending = new Map();
socket.onmessage = ({ data }) => {
  const result = JSON.parse(data);
  if (!result.id) return;
  const handler = pending.get(result.id);
  pending.delete(result.id);
  result.error ? handler.reject(result.error) : handler.resolve(result.result);
};
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
try {
  await send('Page.enable');
  await send('Network.enable');
  await send('Network.setBlockedURLs', { urls: ['http://*', 'https://*'] });
  await send('Page.bringToFront');
  await send('Emulation.setFocusEmulationEnabled', { enabled: true });
  await send('Page.navigate', { url });
  let { frameTree } = await send('Page.getFrameTree');
  assert.equal(frameTree.frame.url, url);
  assert.equal(frameTree.childFrames?.length ?? 0, 0);
  await send('Page.setDocumentContent', {
    frameId: frameTree.frame.id,
    html: '<!doctype html><html lang="en"><head><meta charset="utf-8">'
      + '<meta name="viewport" content="width=device-width,initial-scale=1">'
      + '<meta name="snowflake-source" content="cortex-agent-authored">'
      + '<title>SMTP email layout check</title></head>'
      + `<body style="margin:0;background:#FFFFFF;">${message.html}</body></html>`,
  });
  const reports = [];
  for (const [name, width, height, scheme] of [['desktop', 1200, 900, 'light'], ['mobile', 360, 844, 'light'], ['tablet', 768, 1024, 'light'], ['dark-preference', 390, 844, 'dark']]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
    await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme }] });
    const { frameTree } = await send('Page.getFrameTree');
    assert.equal(frameTree.frame.url, url);
    assert.equal(frameTree.childFrames?.length ?? 0, 0);
    await send('Runtime.evaluate', { expression: '[...document.querySelectorAll("a")].filter(link => link.href !== "https://www.linkedin.com/sharing/compose").slice(0, ' + expectedPosts + ').at(-1).focus();' });
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    const result = await send('Runtime.evaluate', {
      expression: `(async () => {
        await document.fonts.ready;
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const links = [...document.querySelectorAll('a')];
        const composer = links.find(link => link.href === 'https://www.linkedin.com/sharing/compose');
        const paragraphs = [...document.querySelectorAll('.feature p')];
        return {
          width: innerWidth, scroll: document.documentElement.scrollWidth,
          posts: [...document.querySelectorAll('.post-copy')].map(element => element.innerText),
          optionsBeforeFeatures: [...document.querySelectorAll('.post-copy')].every(element => Boolean(element.compareDocumentPosition(document.querySelector('.feature')) & Node.DOCUMENT_POSITION_FOLLOWING)),
          composerCount: links.filter(link => link.href === 'https://www.linkedin.com/sharing/compose').length,
          features: document.querySelectorAll('.feature').length,
          resourceSections: document.querySelectorAll('.sales-resources').length,
          scenarios: document.querySelectorAll('.pain-value').length,
          banner: document.querySelector('.digest-banner')?.innerText,
          bannerColor: getComputedStyle(document.querySelector('.digest-banner')).backgroundColor,
          featureHeaders: document.querySelectorAll('.feature-header').length,
          talkTracks: document.querySelectorAll('.talk-track').length,
          salesGroups: document.querySelectorAll('.sales-group').length,
          removedLabelPresent: document.body.innerText.includes('not a measured result'),
          external: document.querySelectorAll('script,link[rel="stylesheet"],iframe,img,form').length,
          linkURLs: links.map(link => link.href), focused: document.activeElement === composer,
          composerLabel: composer.textContent,
          releaseURLsVisible: links.filter(link => link.href.startsWith('https://docs.snowflake.com/en/release-notes/'))
            .every(link => link.textContent === link.getAttribute('href')),
          focusOutline: getComputedStyle(composer).outlineStyle,
          targetHeight: composer.getBoundingClientRect().height,
          paragraphs: paragraphs.map(element => {
            const style = getComputedStyle(element);
            return {fontSize: style.fontSize, color: style.color, lineHeight: style.lineHeight};
          }),
        };
      })()`,
      returnByValue: true, awaitPromise: true,
    });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    const check = result.result.value;
    assert.ok(check.scroll <= check.width, `${name}: horizontal overflow`);
    assert.equal(check.posts.length, expectedPosts);
    assert.ok(check.posts.every(post => post.trim().length > 0));
    assert.equal(new Set(check.posts.map(post => post.trim().split(/\s+/).slice(0, 3).join(' '))).size, check.posts.length);
    assert.equal(check.optionsBeforeFeatures, true);
    assert.equal(check.composerCount, 1);
    assert.equal(check.external, 0);
    assert.equal(check.features, expectedFeatures);
    assert.equal(check.scenarios, expectedFeatures);
    assert.equal(check.resourceSections, expectedFeatures);
    assert.ok(check.banner.includes('Weekly Feature Digest'));
    assert.equal(check.bannerColor, 'rgb(18, 53, 72)');
    assert.equal(check.featureHeaders, expectedFeatures);
    assert.equal(check.talkTracks, expectedFeatures);
    assert.equal(check.salesGroups, expectedFeatures * 2);
    assert.equal(check.removedLabelPresent, false);
    assert.equal(check.composerLabel, 'Post to Linkedin');
    assert.equal(check.releaseURLsVisible, true);
    assert.ok(check.focused);
    assert.notEqual(check.focusOutline, 'none');
    assert.ok(check.targetHeight >= 44);
    await send('Runtime.evaluate', { expression: 'document.activeElement.blur(); window.scrollTo(0,0);' });
    const metrics = await send('Page.getLayoutMetrics');
    const capture = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width, height: metrics.cssContentSize.height, scale: 1 } });
    await writeFile(`${output}/${name}.png`, Buffer.from(capture.data, 'base64'));
    const top = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width, height: Math.min(height, metrics.cssContentSize.height), scale: 1 } });
    await writeFile(`${output}/${name}-top.png`, Buffer.from(top.data, 'base64'));
    const firstFeature = await send('Runtime.evaluate', { expression: 'document.querySelector(".feature").getBoundingClientRect().top + scrollY', returnByValue: true });
    const detail = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: firstFeature.result.value, width, height: Math.min(1250, metrics.cssContentSize.height - firstFeature.result.value), scale: 1 } });
    await writeFile(`${output}/${name}-feature.png`, Buffer.from(detail.data, 'base64'));
    reports.push({name, ...check});
    console.log(`${name}: no overflow; ${expectedFeatures} sales/resource sections; composer focus and touch size pass; no external resources`);
  }
  await writeFile(`${output}/layout-check.json`, JSON.stringify({input, scope: 'Unsigned SMTP body; not an email-client or signature rendering test', reports}, null, 2));
} finally {
  await send('Page.close');
  socket.close();
}