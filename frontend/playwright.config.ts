import { defineConfig, devices } from '@playwright/test'

// Browser tests run against a real, running Nextcloud with this ExApp
// registered — there is no way to fake the AppAPI proxy, the session auth or
// Talk. That also means they cannot run in CI, which has no Nextcloud: this is
// a local pre-release gate, driven by `make e2e`.
//
// Set NEXTCLOUD_URL and CO_TEST_USER / CO_TEST_PASSWORD, or put them in
// frontend/.env.e2e (gitignored). scripts/dev-env.local.sh holds the same URL.
const BASE_URL = process.env.NEXTCLOUD_URL || 'http://localhost'

export default defineConfig({
	testDir: './tests/browser',
	timeout: 180_000,
	retries: 0,
	workers: 1,
	reporter: [['list']],
	use: {
		baseURL: BASE_URL,
		ignoreHTTPSErrors: true,
		screenshot: 'only-on-failure',
		trace: 'retain-on-failure',
		...devices['Desktop Firefox'],
		launchOptions: {
			firefoxUserPrefs: {
				// Firefox: Chromium's --use-fake-device-for-media-capture stopped
				// providing a fake microphone on this host; these prefs still do,
				// which is what makes the capture path testable at all.
				'media.navigator.streams.fake': true,
				'media.navigator.permission.disabled': true,
			},
		},
	},
	projects: [
		// Log in once and hand the session to every spec, rather than
		// re-authenticating in each of them.
		{ name: 'setup', testMatch: /auth\.setup\.ts/ },
		{
			name: 'firefox',
			use: { browserName: 'firefox', storageState: 'tests/browser/.auth/organizer.json' },
			dependencies: ['setup'],
		},
	],
})
