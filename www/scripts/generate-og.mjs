// Generates public/og.png (1200x630) in the locked coming-soon design:
// navy canvas, the cream bounce-p wordmark (official logo pack PNG — no
// font rasterization needed), the Cloud·Sky render, and the mandatory
// design-study disclaimer baked into the image (docs/product/README.md:
// renders show the V2 design study, not shipped hardware).
import sharp from 'sharp';
import { fileURLToPath } from 'node:url';

const asset = (p) => fileURLToPath(new URL(p, import.meta.url));

const render = await sharp(asset('../src/assets/device/render-cloud-sky.png'))
	.resize({ height: 470 })
	.toBuffer();
const logo = await sharp(asset('../src/assets/brand/yoyopod-cream-1024.png'))
	.resize({ width: 420 })
	.toBuffer();

// Disclaimer set in a generic sans-serif so it renders identically on any
// build machine; the brand type is carried by the logo PNG.
const caption = Buffer.from(`<svg width="1200" height="630" xmlns="http://www.w3.org/2000/svg">
  <text x="70" y="588" font-family="Arial, Helvetica, sans-serif" font-size="24" font-weight="600" fill="rgba(240,238,233,0.55)">V2 design study — not shipped hardware</text>
</svg>`);

await sharp({
	create: { width: 1200, height: 630, channels: 4, background: '#2b2836' },
})
	.composite([
		{ input: render, left: 760, top: 80 },
		{ input: logo, left: 70, top: 240 },
		{ input: caption, left: 0, top: 0 },
	])
	.png()
	.toFile(asset('../public/og.png'));

console.log('wrote public/og.png');
