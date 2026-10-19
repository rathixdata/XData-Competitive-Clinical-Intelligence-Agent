// Inlines the demo build (dist-demo) into one self-contained HTML file: dist-demo/xdata-demo.html
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const dir = new URL('../dist-demo/', import.meta.url).pathname;
let html = readFileSync(join(dir, 'index.html'), 'utf8');
const assets = join(dir, 'assets');
for (const f of readdirSync(assets)) {
  const body = readFileSync(join(assets, f), 'utf8');
  if (f.endsWith('.css')) {
    html = html.replace(new RegExp(`<link rel="stylesheet"[^>]*href="[^"]*${f}"[^>]*>`), () => `<style>${body}</style>`);
  } else if (f.endsWith('.js')) {
    html = html.replace(new RegExp(`<script type="module"[^>]*src="[^"]*${f}"[^>]*></script>`), () => `<script type="module">${body.replace(/<\/script/g, '<\\/script')}</script>`);
  }
}
html = html.replace(/<link rel="modulepreload"[^>]*>/g, '');
const icon = readFileSync(join(dir, 'favicon.svg'), 'utf8');
html = html.replace(/href="[^"]*favicon\.svg"/, () => `href="data:image/svg+xml,${encodeURIComponent(icon)}"`);
if (/src="\.?\/?assets\//.test(html)) throw new Error('unresolved asset reference');
writeFileSync(join(dir, 'xdata-demo.html'), html);
console.log(`wrote ${join(dir, 'xdata-demo.html')} (${(html.length / 1024).toFixed(0)} KB)`);

// Body-only variant for hosts that wrap the page in their own document skeleton (claude.ai Artifacts).
const head = /<head>([\s\S]*)<\/head>/.exec(html)[1].replace(/<meta (charset|name="viewport")[^>]*>\s*/g, '');
const body = /<body>([\s\S]*)<\/body>/.exec(html)[1];
writeFileSync(join(dir, 'xdata-demo.artifact.html'), `${head.trim()}\n${body.trim()}\n`);
