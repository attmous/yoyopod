import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const requireFromWebsite = createRequire(new URL('../../website/package.json', import.meta.url));
const sharp = requireFromWebsite('sharp');
const pitchAssets = resolve(here, '../src/assets/pitch');

const asDataUrl = async (relativePath) => {
	const contents = await readFile(resolve(pitchAssets, relativePath));
	return `data:image/png;base64,${contents.toString('base64')}`;
};

const [mama, papa] = await Promise.all([
	asDataUrl('avatars/mama.png'),
	asDataUrl('avatars/papa.png'),
]);

const screen = `
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="480" height="560" viewBox="0 0 480 560">
	<defs>
		<filter id="shadow" x="-20%" y="-20%" width="140%" height="160%">
			<feDropShadow dx="0" dy="10" stdDeviation="10" flood-color="#31304A" flood-opacity="0.16"/>
		</filter>
		<clipPath id="mama-clip"><circle cx="240" cy="190" r="68"/></clipPath>
		<clipPath id="papa-clip"><circle cx="240" cy="395" r="34"/></clipPath>
	</defs>

	<rect width="480" height="560" fill="#FCE6D2"/>
	<rect y="44" width="480" height="412" fill="#EFEDFF"/>

	<!-- Compact device status bar -->
	<g fill="#1B1B1F" font-family="Avenir Next, Avenir, Helvetica Neue, Arial, sans-serif" font-size="19" font-weight="700">
		<text x="20" y="29">16:18</text>
		<text x="381" y="29">86%</text>
	</g>
	<g fill="none" stroke="#1B1B1F" stroke-width="3" stroke-linecap="round">
		<path d="M106 30v-5m8 5v-10m8 10v-15m8 15v-20"/>
		<path d="M144 17c7-7 17-7 24 0m-19 6c4-4 10-4 14 0"/>
		<rect x="430" y="11" width="35" height="21" rx="3"/>
		<path d="M466 17v9"/>
	</g>
	<rect x="434" y="15" width="25" height="13" rx="1.5" fill="#1B1B1F"/>

	<!-- Current Talk scene language -->
	<g font-family="Avenir Next, Avenir, Helvetica Neue, Arial, sans-serif" fill="#1B1B1F">
		<text x="20" y="70" font-size="16" font-weight="800" letter-spacing="2.4">TALK</text>
		<text x="20" y="94" font-size="15" font-weight="600" opacity="0.56">Approved family</text>
	</g>

	<rect x="64" y="113" width="352" height="214" rx="34" fill="#AAA7E9" filter="url(#shadow)"/>
	<circle cx="240" cy="190" r="73" fill="#FCE6D2" opacity="0.92"/>
	<image x="172" y="122" width="136" height="136" preserveAspectRatio="xMidYMid slice" xlink:href="${mama}" clip-path="url(#mama-clip)"/>
	<circle cx="240" cy="190" r="68" fill="none" stroke="#FFF9F2" stroke-width="6"/>
	<g font-family="Avenir Next, Avenir, Helvetica Neue, Arial, sans-serif" fill="#1B1B1F" text-anchor="middle">
		<text x="240" y="284" font-size="33" font-weight="800">Mama</text>
		<text x="240" y="309" font-size="15" font-weight="650" opacity="0.58">Call · voice message</text>
	</g>
	<g transform="translate(370 124)">
		<circle cx="0" cy="0" r="22" fill="#F37767"/>
		<text x="0" y="7" fill="#1B1B1F" font-family="Avenir Next, Avenir, Helvetica Neue, Arial, sans-serif" font-size="21" font-weight="900" text-anchor="middle">2</text>
	</g>

	<!-- Next contact peek -->
	<circle cx="240" cy="395" r="39" fill="#FCE6D2"/>
	<image x="206" y="361" width="68" height="68" preserveAspectRatio="xMidYMid slice" xlink:href="${papa}" clip-path="url(#papa-clip)"/>
	<circle cx="240" cy="395" r="34" fill="none" stroke="#FFF9F2" stroke-width="4"/>
	<text x="240" y="447" fill="#1B1B1F" opacity="0.72" font-family="Avenir Next, Avenir, Helvetica Neue, Arial, sans-serif" font-size="19" font-weight="750" text-anchor="middle">Papa</text>

	<!-- Current four-slot deck; exact application icon masks are composited below -->
	<rect y="456" width="480" height="104" fill="#FCE6D2"/>
	<rect x="132" y="474" width="96" height="68" rx="24" fill="#AAA7E9"/>
</svg>`;

const deckPositions = [
	{ file: 'deck-listen.png', left: 30, opacity: 0.64 },
	{ file: 'deck-talk.png', left: 150, opacity: 1 },
	{ file: 'deck-ask.png', left: 270, opacity: 0.64 },
	{ file: 'deck-setup.png', left: 390, opacity: 0.64 },
];

const deckIcons = await Promise.all(
	deckPositions.map(async ({ file, left, opacity }) => ({
		input: await sharp(resolve(pitchAssets, `device-ui/${file}`))
			.resize(60, 60, { kernel: sharp.kernel.nearest })
			.ensureAlpha(opacity)
			.png()
			.toBuffer(),
		left,
		top: 478,
	})),
);

await sharp(Buffer.from(screen))
	.composite(deckIcons)
	.png()
	.toFile(resolve(pitchAssets, 'device-ui/device-talk-family.png'));
