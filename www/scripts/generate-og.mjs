// Generates public/og.png (1200x630) in the locked coming-soon design:
// navy canvas, the cream bounce-p wordmark (official logo pack PNG — no
// font rasterization needed), and the Cloud·Sky render.
import sharp from 'sharp';
import { fileURLToPath } from 'node:url';

const asset = (p) => fileURLToPath(new URL(p, import.meta.url));

const render = await sharp(asset('../src/assets/device/render-cloud-sky.png'))
	.resize({ height: 470 })
	.toBuffer();
const logo = await sharp(asset('../src/assets/brand/yoyopod-cream-1024.png'))
	.resize({ width: 420 })
	.toBuffer();

await sharp({
	create: { width: 1200, height: 630, channels: 4, background: '#2b2836' },
})
	.composite([
		{ input: render, left: 760, top: 80 },
		{ input: logo, left: 70, top: 240 },
	])
	.png()
	.toFile(asset('../public/og.png'));

console.log('wrote public/og.png');
