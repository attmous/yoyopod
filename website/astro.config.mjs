// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

const stub = { text: 'Stub', variant: 'caution' };

// https://astro.build/config
export default defineConfig({
	integrations: [
		starlight({
			title: 'yoyopod',
			description:
				'A screen-light audio companion for kids — documentation for the runtime, hardware, and UI system.',
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/attmous/yoyocore' },
			],
			customCss: ['./src/styles/custom.css'],
			sidebar: [
				{
					label: 'Start Here',
					items: [
						{ label: 'Welcome', link: '/' },
						{ label: 'Repo Map & Source of Truth', slug: 'start/repo-map' },
					],
				},
				{
					label: 'UI System Guide',
					items: [
						{ label: 'Guide Index', slug: 'ui' },
						{ label: "Overview: A Pixel's Journey", slug: 'ui/overview' },
						{ label: 'The Mental Model', slug: 'ui/mental-model' },
						{
							label: 'Foundations',
							items: [
								{ label: 'The Glass and the Board', slug: 'ui/hardware' },
								{ label: 'Talking to the Panel', slug: 'ui/driver' },
							],
						},
						{
							label: 'The Stack',
							items: [
								{ label: 'The LVGL Layer', slug: 'ui/lvgl' },
								{ label: 'The Render Loop', slug: 'ui/rendering' },
								{ label: 'The Custom Framework', slug: 'ui/framework' },
								{ label: 'Motion & Theming', slug: 'ui/motion-and-theming' },
							],
						},
						{
							label: 'Interaction',
							items: [
								{ label: 'One Button, Three Gestures', slug: 'ui/input' },
								{ label: 'Screens & Navigation', slug: 'ui/screens' },
							],
						},
						{
							label: 'Reference',
							items: [
								{ label: 'Design Reference Gallery', slug: 'ui/mockups' },
								{ label: 'Playbook & Recipes', slug: 'ui/playbook' },
								{ label: 'Known Gaps & Build Order', slug: 'ui/gaps' },
							],
						},
						{
							label: 'Advanced',
							items: [
								{ label: 'Software Architecture', slug: 'ui/advanced/architecture' },
								{ label: 'Runtime Data Flow', slug: 'ui/advanced/data-flow' },
								{ label: 'Source Map', slug: 'ui/advanced/source-map' },
							],
						},
					],
				},
				{
					label: 'Product',
					items: [
						{ label: 'Product Definition', slug: 'product/definition', badge: stub },
						{ label: 'Positioning', slug: 'product/positioning', badge: stub },
						{ label: 'Roadmap', slug: 'product/roadmap', badge: stub },
					],
				},
				{
					label: 'Architecture',
					items: [
						{ label: 'System Architecture', slug: 'architecture/system-architecture', badge: stub },
						{ label: 'Runtime Event Flow', slug: 'architecture/runtime-event-flow', badge: stub },
						{ label: 'Canonical Structure', slug: 'architecture/canonical-structure', badge: stub },
						{ label: 'Work Areas', slug: 'architecture/work-areas', badge: stub },
					],
				},
				{
					label: 'Hardware',
					items: [
						{ label: 'Audio Stack', slug: 'hardware/audio-stack', badge: stub },
						{ label: 'Power Module', slug: 'hardware/power-module', badge: stub },
					],
				},
				{
					label: 'Features',
					items: [
						{ label: 'Cloud Provisioning & Backend', slug: 'features/cloud-provisioning', badge: stub },
						{ label: 'Cloud Voice Worker', slug: 'features/cloud-voice-worker', badge: stub },
						{ label: 'Local-First Music', slug: 'features/local-first-music', badge: stub },
						{ label: 'Remote Playback', slug: 'features/remote-playback', badge: stub },
						{ label: 'MPV Dependencies', slug: 'features/mpv-dependencies', badge: stub },
					],
				},
				{
					label: 'Operations',
					items: [
						{ label: 'Development Guide', slug: 'operations/development-guide', badge: stub },
						{ label: 'Pi Dev Workflow', slug: 'operations/pi-dev-workflow', badge: stub },
						{ label: 'Dev/Prod Lanes', slug: 'operations/dev-prod-lanes', badge: stub },
						{ label: 'Quality Gates', slug: 'operations/quality-gates', badge: stub },
						{ label: 'Setup Contract', slug: 'operations/setup-contract', badge: stub },
						{ label: 'Contributor Workflow', slug: 'operations/contributor-workflow', badge: stub },
					],
				},
			],
		}),
	],
});
