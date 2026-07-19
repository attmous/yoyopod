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
								{ label: 'Unboxing & First Setup', slug: 'families/unboxing', badge: pr },
								{ label: 'The Parent App & Pairing', slug: 'families/parent-app-setup', badge: pr },
								{ label: 'One Button: How Kids Use It', slug: 'families/using-the-button', badge: pr },
							],
						},
						{
							label: 'Everyday Use',
							items: [
								{ label: 'Listening: Music & Stories', slug: 'families/listening', badge: pr },
								{ label: 'Talking: Calls & Voice Notes', slug: 'families/talking', badge: pr },
								{ label: 'Location & Check-Ins', slug: 'families/location', badge: pr },
								{ label: 'Charging & Care', slug: 'families/care', badge: pr },
							],
						},
						{
							label: 'Safety & Privacy',
							items: [
								{ label: 'Parental Controls', slug: 'families/parental-controls', badge: pr },
								{ label: 'Our Privacy Promise', slug: 'families/privacy', badge: pr },
							],
						},
						{ label: 'FAQ & Troubleshooting', slug: 'families/faq', badge: pr },
					],
				},
				{
					label: 'User Stories',
					items: [
						{ label: 'Stories Index', slug: 'stories' },
						{ label: 'Mia, 8: The Walk to School', slug: 'stories/mia-walk-to-school', badge: pr },
						{ label: 'Jonas, 10: Saturday Playlists', slug: 'stories/jonas-saturday-playlists', badge: pr },
						{ label: 'Grandma Calls at Six', slug: 'stories/grandma-calls', badge: pr },
						{ label: 'A Voice Note from the Bus', slug: 'stories/voice-note-from-the-bus', badge: pr },
						{ label: 'Lights Out: Bedtime Stories', slug: 'stories/bedtime-stories', badge: pr },
						{ label: "The First Week (a Parent's View)", slug: 'stories/first-week-parent', badge: pr },
					],
				},
				{
					label: 'Applications',
					items: [
						{ label: 'Apps Index', slug: 'apps' },
						{ label: 'Listen: Music & Stories', slug: 'apps/listen', badge: pr },
						{ label: 'Talk: Calls & Voice Notes', slug: 'apps/talk', badge: pr },
						{ label: 'Ask: The Voice Companion', slug: 'apps/ask', badge: pr },
						{ label: 'Locate: Location & Check-Ins', slug: 'apps/locate', badge: pr },
						{ label: 'The Parent App', slug: 'apps/parent-app', badge: pr },
						{ label: 'Setup: On-Device Onboarding', slug: 'apps/setup', badge: pr },
						{ label: 'What Comes Next', slug: 'apps/future', badge: pr },
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
								{ label: 'Connectivity: 4G & GPS', slug: 'builders/hardware/connectivity', badge: pr },
								{ label: 'From Prototype to Product', slug: 'builders/hardware/roadmap', badge: pr },
							],
						},
						{
							label: 'Software Platform',
							items: [
								{ label: 'Architecture at a Glance', slug: 'builders/software/architecture' },
								{ label: 'The yoyocore Runtime', slug: 'builders/software/runtime' },
								{ label: 'UI Engine', slug: 'builders/software/ui' },
								{ label: 'Media Engine', slug: 'builders/software/media-engine' },
								{ label: 'VoIP Engine', slug: 'builders/software/voip-engine', badge: pr },
								{ label: 'Speech Engine', slug: 'builders/software/speech-engine', badge: pr },
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
								{ label: 'APIs & SDKs', slug: 'builders/dev/apis', badge: pr },
							],
						},
					],
				},
				{
					label: 'Company',
					items: [
						{ label: 'Company Index', slug: 'company' },
						{ label: 'Mission & Story', slug: 'company/mission' },
						{ label: 'Product Principles', slug: 'company/principles', badge: pr },
						{ label: 'What yoyopod Is Not', slug: 'company/what-we-are-not', badge: pr },
						{ label: 'Brand Kit', slug: 'company/brand-kit' },
						{ label: 'Roadmap', slug: 'company/roadmap' },
					],
				},
			],
		}),
	],
});
