// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// Content-status badges: `ph` = no as-built content exists yet;
// `pt` = some sections carry real content, the rest is placeholder;
// `pr` = the ideal target design is written out in full, awaiting
// adopt/adapt/drop decisions — not implemented.
const ph = { text: 'Placeholder', variant: 'caution' };
const pt = { text: 'Partial', variant: 'note' };
const pr = { text: 'Proposed', variant: 'success' };

// https://astro.build/config
export default defineConfig({
	integrations: [
		starlight({
			title: 'yoyopod vision',
			description:
				'The target-state documentation for yoyopod — the first device before a smartphone. Structure first, content later.',
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/attmous/yoyopod' },
			],
			customCss: ['./src/styles/custom.css'],
			sidebar: [
				{
					label: 'Start Here',
					items: [
						{ label: 'Welcome', link: '/' },
						{ label: 'About This Site', slug: 'start/about-this-site' },
					],
				},
				{
					label: 'For Families',
					items: [
						{ label: 'Family Guide Index', slug: 'families' },
						{
							label: 'Getting Started',
							items: [
								{ label: 'Unboxing & First Setup', slug: 'families/unboxing', badge: ph },
								{ label: 'The Parent App & Pairing', slug: 'families/parent-app-setup', badge: ph },
								{ label: 'One Button: How Kids Use It', slug: 'families/using-the-button', badge: pt },
							],
						},
						{
							label: 'Everyday Use',
							items: [
								{ label: 'Listening: Music & Stories', slug: 'families/listening', badge: pt },
								{ label: 'Talking: Calls & Voice Notes', slug: 'families/talking', badge: pt },
								{ label: 'Location & Check-Ins', slug: 'families/location', badge: ph },
								{ label: 'Charging & Care', slug: 'families/care', badge: pt },
							],
						},
						{
							label: 'Safety & Privacy',
							items: [
								{ label: 'Parental Controls', slug: 'families/parental-controls', badge: ph },
								{ label: 'Our Privacy Promise', slug: 'families/privacy', badge: ph },
							],
						},
						{ label: 'FAQ & Troubleshooting', slug: 'families/faq', badge: ph },
					],
				},
				{
					label: 'User Stories',
					items: [
						{ label: 'Stories Index', slug: 'stories' },
						{ label: 'Mia, 8: The Walk to School', slug: 'stories/mia-walk-to-school', badge: ph },
						{ label: 'Jonas, 10: Saturday Playlists', slug: 'stories/jonas-saturday-playlists', badge: ph },
						{ label: 'Grandma Calls at Six', slug: 'stories/grandma-calls', badge: ph },
						{ label: 'A Voice Note from the Bus', slug: 'stories/voice-note-from-the-bus', badge: ph },
						{ label: 'Lights Out: Bedtime Stories', slug: 'stories/bedtime-stories', badge: ph },
						{ label: "The First Week (a Parent's View)", slug: 'stories/first-week-parent', badge: ph },
					],
				},
				{
					label: 'Applications',
					items: [
						{ label: 'Apps Index', slug: 'apps' },
						{ label: 'Listen: Music & Stories', slug: 'apps/listen', badge: pt },
						{ label: 'Talk: Calls & Voice Notes', slug: 'apps/talk', badge: pt },
						{ label: 'Ask: The Voice Companion', slug: 'apps/ask', badge: pr },
						{ label: 'Locate: Location & Check-Ins', slug: 'apps/locate', badge: ph },
						{ label: 'The Parent App', slug: 'apps/parent-app', badge: pt },
						{ label: 'Setup: On-Device Onboarding', slug: 'apps/setup', badge: pt },
						{ label: 'What Comes Next', slug: 'apps/future', badge: ph },
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
								{ label: 'Connectivity: 4G & GPS', slug: 'builders/hardware/connectivity', badge: pt },
								{ label: 'From Prototype to Product', slug: 'builders/hardware/roadmap', badge: pt },
							],
						},
						{
							label: 'Software Platform',
							items: [
								{ label: 'Architecture at a Glance', slug: 'builders/software/architecture' },
								{ label: 'The yoyocore Runtime', slug: 'builders/software/runtime' },
								{ label: 'UI Engine', slug: 'builders/software/ui' },
								{ label: 'Media Engine', slug: 'builders/software/media-engine' },
								{ label: 'Calling Engine', slug: 'builders/software/calling-engine', badge: pr },
								{ label: 'Voice & Ask Engine', slug: 'builders/software/voice-ask', badge: pr },
								{ label: 'Cloud & Provisioning', slug: 'builders/software/cloud', badge: pr },
								{ label: 'App Platform', slug: 'builders/software/apps', badge: pr },
								{ label: 'Security Model', slug: 'builders/software/security', badge: pr },
							],
						},
						{
							label: 'Developer Guide',
							items: [
								{ label: 'Dev Environment', slug: 'builders/dev/environment' },
								{ label: 'Build & Flash a Device', slug: 'builders/dev/build-and-flash' },
								{ label: 'Testing & Validation', slug: 'builders/dev/testing' },
								{ label: 'APIs & SDKs', slug: 'builders/dev/apis', badge: ph },
							],
						},
					],
				},
				{
					label: 'Company',
					items: [
						{ label: 'Company Index', slug: 'company' },
						{ label: 'Mission & Story', slug: 'company/mission' },
						{ label: 'Product Principles', slug: 'company/principles', badge: pt },
						{ label: 'What yoyopod Is Not', slug: 'company/what-we-are-not', badge: pt },
						{ label: 'Brand Kit', slug: 'company/brand-kit' },
						{ label: 'Roadmap', slug: 'company/roadmap' },
					],
				},
			],
		}),
	],
});
