// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';


// https://astro.build/config
export default defineConfig({
	redirects: {
		'/architecture/system-architecture/': '/runtime/overview/',
		'/architecture/runtime-event-flow/': '/runtime/loop/',
	},
	integrations: [
		starlight({
			title: 'yoyopod',
			description:
				'A screen-light audio companion for kids — documentation for the runtime, hardware, and UI system.',
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/attmous/yoyopod' },
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
					label: 'Runtime & Workers Guide',
					items: [
						{ label: 'Guide Index', slug: 'runtime' },
						{ label: "Overview: One Intent's Round Trip", slug: 'runtime/overview' },
						{ label: 'The Mental Model', slug: 'runtime/mental-model' },
						{
							label: 'The Protocol',
							items: [
								{ label: 'Telegrams on the Wire', slug: 'runtime/protocol' },
								{ label: 'The UI Contract', slug: 'runtime/ui-contract' },
							],
						},
						{
							label: 'The Supervisor',
							items: [
								{ label: 'Seven Processes, One Desk', slug: 'runtime/process-model' },
								{ label: 'Startup & Shutdown', slug: 'runtime/lifecycle' },
								{ label: 'The 50 Hz Loop', slug: 'runtime/loop' },
								{ label: 'Intents & House Rules', slug: 'runtime/routing-and-policies' },
								{ label: 'Configuration Wiring', slug: 'runtime/configuration' },
							],
						},
						{
							label: 'The Workers',
							items: [
								{ label: 'Media: The Record Library', slug: 'runtime/workers/media' },
								{ label: 'VoIP: The Switchboard', slug: 'runtime/workers/voip' },
								{ label: 'Network: The Radio Room', slug: 'runtime/workers/network' },
								{ label: 'Cloud: The Telegraph Desk', slug: 'runtime/workers/cloud' },
								{ label: 'Power: The Boiler Room', slug: 'runtime/workers/power' },
								{ label: 'Speech: The Interpreter', slug: 'runtime/workers/speech' },
							],
						},
						{
							label: 'Reference',
							items: [
								{ label: 'Testing & Validation', slug: 'runtime/testing' },
								{ label: 'Known Gaps & Honest Caveats', slug: 'runtime/gaps' },
							],
						},
						{
							label: 'Advanced',
							items: [
								{ label: 'Failure Paths & Timeouts', slug: 'runtime/advanced/failure-paths' },
								{ label: 'Source Map', slug: 'runtime/advanced/source-map' },
							],
						},
					],
				},
				{
					label: 'Product',
					items: [
						{ label: 'Product Definition', slug: 'product/definition' },
						{ label: 'Positioning', slug: 'product/positioning' },
						{ label: 'Roadmap', slug: 'product/roadmap' },
					],
				},
				{
					label: 'Architecture',
					items: [
						{ label: 'Canonical Structure', slug: 'architecture/canonical-structure' },
						{ label: 'Work Areas', slug: 'architecture/work-areas' },
					],
				},
				{
					label: 'Hardware',
					items: [
						{ label: 'Audio Stack', slug: 'hardware/audio-stack' },
						{ label: 'Power Module', slug: 'hardware/power-module' },
					],
				},
				{
					label: 'Features',
					items: [
						{ label: 'Cloud Provisioning & Backend', slug: 'features/cloud-provisioning' },
						{ label: 'Cloud Voice Worker', slug: 'features/cloud-voice-worker' },
						{ label: 'Local-First Music', slug: 'features/local-first-music' },
						{ label: 'Remote Playback', slug: 'features/remote-playback' },
						{ label: 'MPV Dependencies', slug: 'features/mpv-dependencies' },
					],
				},
				{
					label: 'Operations',
					items: [
						{ label: 'Development Guide', slug: 'operations/development-guide' },
						{ label: 'Pi Dev Workflow', slug: 'operations/pi-dev-workflow' },
						{ label: 'Dev/Prod Lanes', slug: 'operations/dev-prod-lanes' },
						{ label: 'Quality Gates', slug: 'operations/quality-gates' },
						{ label: 'Setup Contract', slug: 'operations/setup-contract' },
						{ label: 'Contributor Workflow', slug: 'operations/contributor-workflow' },
					],
				},
			],
		}),
	],
});
