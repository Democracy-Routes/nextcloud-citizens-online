// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Page } from '@playwright/test'

export const STATE_FILE = 'tests/browser/.auth/organizer.json'

/** AppAPI serves the ExApp's own page here. */
export const APP_PATH = '/index.php/apps/app_api/embedded/citizens_online/citizens_online'

export function credentials(): { user: string; password: string } {
	const user = process.env.CO_TEST_USER
	const password = process.env.CO_TEST_PASSWORD
	if (!user || !password) {
		throw new Error(
			'Set CO_TEST_USER and CO_TEST_PASSWORD (see frontend/playwright.config.ts). ' +
				'They must be a Nextcloud account on NEXTCLOUD_URL.',
		)
	}
	return { user, password }
}

/** Open the app and get past Nextcloud's own first-run modal, which otherwise
 *  swallows the first click of every spec. */
export async function openApp(page: Page): Promise<void> {
	await page.goto(APP_PATH, { waitUntil: 'networkidle' })
	await page.waitForTimeout(1000)
	await page.evaluate(() =>
		document.querySelectorAll('.modal-mask, #firstrunwizard').forEach((e) => e.remove()),
	)
}

/** The ExApp's API base, derived the same way the bundle derives it. */
export async function apiBase(page: Page): Promise<string> {
	return page.evaluate(() => {
		const el = document.querySelector<HTMLScriptElement>('script[src*="citizens-online-main"]')
		return el!.src.replace(/\/js\/.*$/, '')
	})
}

/** Call the app's own API with the logged-in session, for setup and teardown
 *  that would be tedious to drive through the UI. */
export async function api<T = any>(
	page: Page,
	method: string,
	path: string,
	body?: unknown,
): Promise<{ status: number; body: T }> {
	const base = await apiBase(page)
	return page.evaluate(
		async ([base, method, path, body]: any) => {
			const response = await fetch(base + path, {
				method,
				headers: body ? { 'Content-Type': 'application/json' } : {},
				body: body ? JSON.stringify(body) : undefined,
				credentials: 'same-origin',
			})
			let parsed: any = null
			try {
				parsed = await response.json()
			} catch {
				/* 204 and friends */
			}
			return { status: response.status, body: parsed }
		},
		[base, method, path, body],
	)
}
