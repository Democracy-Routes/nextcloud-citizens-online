// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Every route in this app sits behind a Nextcloud session, so the suite logs in
// once here and every spec reuses the saved state.
import { expect, test as setup } from '@playwright/test'
import { STATE_FILE, credentials } from './helpers'

setup('log the organizer in', async ({ page }) => {
	const { user, password } = credentials()
	await page.goto('/login')
	await page.fill('input[name="user"]', user)
	await page.fill('input[name="password"]', password)
	await page.click('button[type="submit"]')
	// Nextcloud lands on the dashboard; a failed login stays on /login.
	await expect(page).not.toHaveURL(/\/login/, { timeout: 30_000 })
	await page.context().storageState({ path: STATE_FILE })
})
