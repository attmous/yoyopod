// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

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
								{ label: 'Unboxing & First Setup', slug: 'families/unboxing' },
								{ label: 'The Parent App & Pairing', slug: 'families/parent-app-setup' },
								{ label: 'One Button: How Kids Use It', slug: 'families/using-the-button' },
							],
						},
						{
							label: 'Everyday Use',
							items: [
								{ label: 'Listening: Music & Stories', slug: 'families/listening' },
								{ label: 'Talking: Calls & Voice Notes', slug: 'families/talking' },
								{ label: 'Location & Check-Ins', slug: 'families/location' },
								{ label: 'Charging & Care', slug: 'families/care' },
							],
						},
						{
							label: 'Safety & Privacy',
							items: [
								{ label: 'Parental Controls', slug: 'families/parental-controls' },
								{ label: 'Our Privacy Promise', slug: 'families/privacy' },
							],
						},
						{ label: 'FAQ & Troubleshooting', slug: 'families/faq' },
					],
				},
				{
					label: 'User Stories',
					items: [
						{ label: 'Stories Index', slug: 'stories' },
						{ label: 'Mia, 8: The Walk to School', slug: 'stories/mia-walk-to-school' },
						{ label: 'Jonas, 10: Saturday Playlists', slug: 'stories/jonas-saturday-playlists' },
						{ label: 'Grandma Calls at Six', slug: 'stories/grandma-calls' },
						{ label: 'A Voice Note from the Bus', slug: 'stories/voice-note-from-the-bus' },
						{ label: 'Lights Out: Bedtime Stories', slug: 'stories/bedtime-stories' },
						{ label: "The First Week (a Parent's View)", slug: 'stories/first-week-parent' },
					],
				},
				{
					label: 'Applications',
					items: [
						{ label: 'Apps Index', slug: 'apps' },
						{ label: 'Listen: Music & Stories', slug: 'apps/listen' },
						{ label: 'Talk: Calls & Voice Notes', slug: 'apps/talk' },
						{ label: 'Locate: Location & Check-Ins', slug: 'apps/locate' },
						{ label: 'The Parent App', slug: 'apps/parent-app' },
						{ label: 'Setup: On-Device Onboarding', slug: 'apps/setup' },
						{ label: 'What Comes Next', slug: 'apps/future' },
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
								{ label: 'The Glass: Display & Input', slug: 'builders/hardware/display' },
								{ label: 'Audio Path', slug: 'builders/hardware/audio' },
								{ label: 'Power & Battery', slug: 'builders/hardware/power' },
								{ label: 'Connectivity: 4G & GPS', slug: 'builders/hardware/connectivity' },
								{ label: 'From Prototype to Product', slug: 'builders/hardware/roadmap' },
							],
						},
						{
							label: 'Software Platform',
							items: [
								{ label: 'Architecture at a Glance', slug: 'builders/software/architecture' },
								{ label: 'Device Runtime & Workers', slug: 'builders/software/runtime' },
								{ label: 'UI System', slug: 'builders/software/ui' },
								{ label: 'Cloud & Provisioning', slug: 'builders/software/cloud' },
								{ label: 'App Platform', slug: 'builders/software/apps' },
								{ label: 'Security Model', slug: 'builders/software/security' },
							],
						},
						{
							label: 'Developer Guide',
							items: [
								{ label: 'Dev Environment', slug: 'builders/dev/environment' },
								{ label: 'Build & Flash a Device', slug: 'builders/dev/build-and-flash' },
								{ label: 'Testing & Validation', slug: 'builders/dev/testing' },
								{ label: 'APIs & SDKs', slug: 'builders/dev/apis' },
							],
						},
					],
				},
				{
					label: 'Company',
					items: [
						{ label: 'Company Index', slug: 'company' },
						{ label: 'Mission & Story', slug: 'company/mission' },
						{ label: 'Product Principles', slug: 'company/principles' },
						{ label: 'What yoyopod Is Not', slug: 'company/what-we-are-not' },
						{ label: 'Brand Kit', slug: 'company/brand-kit' },
						{ label: 'Roadmap', slug: 'company/roadmap' },
					],
				},
			],
		}),
	],
});
