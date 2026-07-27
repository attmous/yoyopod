// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// Pages badged `vision` describe the target experience in full;
// unmarked pages are condensed from as-built documentation.
const vision = { text: 'Vision', variant: 'tip' };

// https://astro.build/config
export default defineConfig({
	site: 'https://docs.yoyopod.com',
	integrations: [
		starlight({
			title: 'yoyopod vision',
			description:
				'What yoyopod is today and the product it is becoming — the first device before a smartphone, for families, builders, and the curious.',
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/attmous/yoyopod' },
			],
			customCss: ['./src/styles/custom.css', './src/styles/promo.css'],
			sidebar: [
				{
					label: 'Start Here',
					items: [
						{ label: 'yoyopod.com ↗', link: 'https://yoyopod.com' },
						{ label: 'Welcome', link: '/' },
						{ label: 'About This Site', slug: 'start/about-this-site' },
						{ label: 'yoyopod in 30 Seconds', slug: 'start/promo' },
					],
				},
				{
					label: 'For Families',
					items: [
						{ label: 'Family Guide Index', slug: 'families' },
						{
							label: 'Getting Started',
							items: [
								{ label: 'Unboxing & First Setup', slug: 'families/unboxing', badge: vision },
								{ label: 'The Parent App & Pairing', slug: 'families/parent-app-setup', badge: vision },
								{ label: 'One Button: How Kids Use It', slug: 'families/using-the-button', badge: vision },
							],
						},
						{
							label: 'Everyday Use',
							items: [
								{ label: 'Listening: Music & Stories', slug: 'families/listening', badge: vision },
								{ label: 'Talking: Calls & Voice Notes', slug: 'families/talking', badge: vision },
								{ label: 'Location & Check-Ins', slug: 'families/location', badge: vision },
								{ label: 'Charging & Care', slug: 'families/care', badge: vision },
							],
						},
						{
							label: 'Safety & Privacy',
							items: [
								{ label: 'Parental Controls', slug: 'families/parental-controls', badge: vision },
								{ label: 'Our Privacy Promise', slug: 'families/privacy', badge: vision },
							],
						},
						{ label: 'FAQ & Troubleshooting', slug: 'families/faq', badge: vision },
					],
				},
				{
					label: 'User Stories',
					items: [
						{ label: 'Stories Index', slug: 'stories' },
						{ label: 'Mia, 8: The Walk to School', slug: 'stories/mia-walk-to-school', badge: vision },
						{ label: 'Jonas, 10: Saturday Playlists', slug: 'stories/jonas-saturday-playlists', badge: vision },
						{ label: 'Grandma Calls at Six', slug: 'stories/grandma-calls', badge: vision },
						{ label: 'A Voice Note from the Bus', slug: 'stories/voice-note-from-the-bus', badge: vision },
						{ label: 'Lights Out: Bedtime Stories', slug: 'stories/bedtime-stories', badge: vision },
						{ label: "The First Week (a Parent's View)", slug: 'stories/first-week-parent', badge: vision },
					],
				},
				{
					label: 'Applications',
					items: [
						{ label: 'Apps Index', slug: 'apps' },
						{ label: 'Listen: Music & Stories', slug: 'apps/listen', badge: vision },
						{ label: 'Talk: Calls & Voice Notes', slug: 'apps/talk', badge: vision },
						{ label: 'Ask: The Voice Companion', slug: 'apps/ask', badge: vision },
						{ label: 'Locate: Location & Check-Ins', slug: 'apps/locate', badge: vision },
						{ label: 'The Parent App', slug: 'apps/parent-app', badge: vision },
						{ label: 'Setup: On-Device Onboarding', slug: 'apps/setup', badge: vision },
						{ label: 'What Comes Next', slug: 'apps/future', badge: vision },
					],
				},
				{
					label: 'For Builders',
					items: [
						{ label: 'Builders Index', slug: 'builders' },
						{
							label: 'Hardware Platform',
							items: [
								{ label: 'Device Overview & Specs', slug: 'builders/hardware/overview' },
								{ label: 'The Canvas: Display & Input', slug: 'builders/hardware/display' },
								{ label: 'Audio Path', slug: 'builders/hardware/audio' },
								{ label: 'Power & Battery', slug: 'builders/hardware/power' },
								{ label: 'Connectivity: 4G & GPS', slug: 'builders/hardware/connectivity', badge: vision },
								{ label: 'From Prototype to Product', slug: 'builders/hardware/roadmap', badge: vision },
							],
						},
						{
							label: 'Software Platform',
							items: [
								{ label: 'Architecture at a Glance', slug: 'builders/software/architecture' },
								{ label: 'The yoyocore Runtime', slug: 'builders/software/runtime' },
								{ label: 'UI Engine', slug: 'builders/software/ui' },
								{ label: 'Media Engine', slug: 'builders/software/media-engine' },
								{ label: 'VoIP Engine', slug: 'builders/software/voip-engine', badge: vision },
								{ label: 'Speech Engine', slug: 'builders/software/speech-engine', badge: vision },
								{ label: 'Cloud & Provisioning', slug: 'builders/software/cloud', badge: vision },
								{ label: 'App Platform', slug: 'builders/software/apps', badge: vision },
								{ label: 'Security Model', slug: 'builders/software/security', badge: vision },
							],
						},
						{
							label: 'Developer Guide',
							items: [
								{ label: 'Dev Environment', slug: 'builders/dev/environment' },
								{ label: 'Build & Flash a Device', slug: 'builders/dev/build-and-flash' },
								{ label: 'Testing & Validation', slug: 'builders/dev/testing' },
								{ label: 'APIs & SDKs', slug: 'builders/dev/apis', badge: vision },
							],
						},
					],
				},
				{
					label: 'Company',
					items: [
						{ label: 'Company Index', slug: 'company' },
						{ label: 'Mission & Story', slug: 'company/mission' },
						{ label: 'Product Principles', slug: 'company/principles', badge: vision },
						{ label: 'What yoyopod Is Not', slug: 'company/what-we-are-not', badge: vision },
						{ label: 'Brand Kit', slug: 'company/brand-kit' },
						{ label: 'Roadmap', slug: 'company/roadmap' },
					],
				},
			],
		}),
	],
});
