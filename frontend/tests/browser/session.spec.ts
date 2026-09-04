// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The organizer's path from nothing to a distributed round, through the real UI
// against a real Nextcloud. Everything it creates is removed again, whether or
// not the test passes.
import { expect, test } from '@playwright/test'
import { api, openApp } from './helpers'

const NAME = `ZZ e2e ${Date.now()}`
let sessionId = ''

test.afterAll(async ({ browser }) => {
	if (!sessionId) return
	const page = await browser.newPage()
	await openApp(page)
	await api(page, 'DELETE', `/api/v1/sessions/${sessionId}`)
	await page.close()
})

test('an organizer can build a session and distribute its rooms', async ({ page }) => {
	await openApp(page)

	await page.click('.cz-sidebar__top .cz-btn')
	await page.fill('.cz-page input[type="text"]', NAME)
	await page.click('.cz-page .cz-btn--primary')

	await expect(page.locator('.cz-pagehead h2')).toHaveText(NAME, { timeout: 20_000 })
	const list = await api(page, 'GET', '/api/v1/sessions')
	sessionId = list.body.find((s: any) => s.name === NAME).id

	// every tab renders
	for (const label of ['Rounds', 'Participants', 'Rooms', 'Analysis', 'Report', 'Settings']) {
		await page.click(`button.cz-tab:has-text("${label}")`)
		await expect(page.locator('[role="tabpanel"]')).toBeVisible()
	}

	// add people through the picker, which is the only supported way now
	await page.click('button.cz-tab:has-text("Participants")')
	await page.click('.cz-picker input')
	await page.type('.cz-picker input', 'co2', { delay: 30 })
	await page.waitForSelector('.cz-picker__hit')
	await page.keyboard.press('Enter')
	await expect(page.locator('.cz-table tbody tr')).toHaveCount(1, { timeout: 15_000 })

	// and distribute them
	await api(page, 'POST', `/api/v1/sessions/${sessionId}/participants`, {
		participants: [{ nc_user_id: 'co3' }, { nc_user_id: 'co4' }],
	})
	await page.click('button.cz-tab:has-text("Rooms")')
	await page.click('[role="tabpanel"] .cz-btn')
	await expect(page.locator('[role="tabpanel"] .cz-card').first()).toBeVisible({ timeout: 15_000 })
})

test('the settings tab can rename the session', async ({ page }) => {
	// Its own session, not the one above. Tests coupled through a module variable
	// skip silently when run alone, and a skip reads like a pass.
	await openApp(page)
	const name = `ZZ e2e rename ${Date.now()}`
	const created = await api(page, 'POST', '/api/v1/sessions', { name })
	expect(created.status).toBe(201)

	try {
		await openApp(page)
		await page.click(`.cz-navitem:has-text("${name}")`)
		await page.click('button.cz-tab:has-text("Settings")')

		const renamed = `${name} renamed`
		await page.fill('[role="tabpanel"] input[type="text"]', renamed)
		await page.click('[role="tabpanel"] .cz-btn--primary')
		await expect(page.locator('.cz-pagehead h2')).toHaveText(renamed, { timeout: 15_000 })
	} finally {
		await api(page, 'DELETE', `/api/v1/sessions/${created.body.id}`)
	}
})
