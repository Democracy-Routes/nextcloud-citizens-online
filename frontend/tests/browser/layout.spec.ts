// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The app once shipped with its sidebar stacked above the content, the page
// clipped with no scrollbar, and every form label at browser default size —
// because the components used class names the stylesheet did not define. None
// of that fails a unit test. These assertions are geometric on purpose.
import { expect, test } from '@playwright/test'
import { openApp } from './helpers'

test.describe('the app shell', () => {
	test('sidebar and content sit side by side and fill the surface', async ({ page }) => {
		await openApp(page)
		await page.waitForSelector('.cz-sidebar')

		const root = (await page.locator('#citizens-online-app').boundingBox())!
		const sidebar = (await page.locator('.cz-sidebar').boundingBox())!
		const content = (await page.locator('main.cz-content').boundingBox())!

		// side by side, not stacked
		expect(Math.round(sidebar.x + sidebar.width)).toBe(Math.round(content.x))
		expect(Math.round(sidebar.y)).toBe(Math.round(content.y))
		// and together they fill the shell
		expect(Math.round(content.x + content.width)).toBe(Math.round(root.x + root.width))
		expect(sidebar.width).toBeGreaterThan(200)
	})

	test('the content pane scrolls, not the page', async ({ page }) => {
		await openApp(page)
		await page.waitForSelector('main.cz-content')
		const overflow = await page.locator('main.cz-content').evaluate(
			(el) => getComputedStyle(el).overflowY,
		)
		expect(overflow).toBe('auto')
		const pageScrolls = await page.evaluate(
			() => document.documentElement.scrollHeight > window.innerHeight + 1,
		)
		expect(pageScrolls).toBe(false)
	})

	test('there is no unstyled wrapper between the shell and its panes', async ({ page }) => {
		await openApp(page)
		await page.waitForSelector('.cz-sidebar')
		const childClasses = await page.locator('#citizens-online-app > *').evaluateAll(
			(nodes) => nodes.map((n) => n.className),
		)
		expect(childClasses.some((c) => String(c).includes('cz-sidebar'))).toBe(true)
		expect(childClasses.some((c) => String(c).includes('cz-shell'))).toBe(false)
	})
})
