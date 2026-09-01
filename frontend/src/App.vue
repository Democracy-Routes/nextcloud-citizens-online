<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One bundle, two audiences. An organizer sees their sessions; a participant
// sees only the deliberation they are in. Which one you get is decided by what
// the server says about you, not by a menu.
import { computed, onMounted, ref } from 'vue'
import { api, ApiError } from './api'
import CzButton from './components/ui/CzButton.vue'
import CzToasts from './components/ui/CzToasts.vue'
import ParticipantView from './components/participant/ParticipantView.vue'
import SessionDetail from './components/SessionDetail.vue'
import SessionWizard from './components/SessionWizard.vue'
import SettingsView from './components/SettingsView.vue'
import { toast } from './components/ui/toast'

type View = { name: 'empty' } | { name: 'create' } | { name: 'detail'; id: string } | { name: 'settings' }

const sessions = ref<any[]>([])
const view = ref<View>({ name: 'empty' })
const loaded = ref(false)
const isAdmin = ref(false)
const mode = ref<'loading' | 'organizer' | 'participant'>('loading')
const sidebarOpen = ref(false)

const STATUS_TONE: Record<string, string> = {
	DRAFT: 'gray',
	READY: 'blue',
	ACTIVE: 'red',
	PROCESSING: 'amber',
	REVIEW: 'blue',
	COMPLETE: 'green',
}

const activeId = computed(() => (view.value.name === 'detail' ? view.value.id : ''))

async function loadSessions(): Promise<void> {
	try {
		sessions.value = await api.listSessions()
	} catch (error) {
		if (!(error instanceof ApiError && error.status === 403)) {
			console.warn('could not list sessions', error)
		}
		sessions.value = []
	}
	loaded.value = true
}

async function decideMode(): Promise<void> {
	// An organizer is anyone who owns a session or can create one; a person who
	// is only a participant should not be shown an empty organizer console.
	const [mine, participation] = await Promise.all([
		api.listSessions().catch(() => []),
		api.mySession().catch(() => ({ state: 'none' })),
	])
	sessions.value = mine
	loaded.value = true
	const isParticipant = participation && participation.state !== 'none'
	mode.value = mine.length === 0 && isParticipant ? 'participant' : 'organizer'
}

async function checkAdmin(): Promise<void> {
	try {
		await api.adminPing()
		isAdmin.value = true
	} catch (error) {
		// only a definite 403 hides Settings — any other failure leaves it
		// visible so the real error is on screen instead of a missing menu
		isAdmin.value = !(error instanceof ApiError && error.status === 403)
	}
}

function open(id: string): void {
	view.value = { name: 'detail', id }
	sidebarOpen.value = false
}

async function onCreated(session: any): Promise<void> {
	await loadSessions()
	open(session.id)
	toast('Session created')
}

async function onDeleted(): Promise<void> {
	view.value = { name: 'empty' }
	await loadSessions()
}

onMounted(async () => {
	await decideMode()
	if (mode.value === 'organizer') await checkAdmin()
})
</script>

<template>
	<div class="cz-shell" :class="{ 'cz-shell--participant': mode === 'participant' }">
		<template v-if="mode === 'participant'">
			<main class="cz-content cz-content--single">
				<ParticipantView />
			</main>
		</template>

		<template v-else>
			<aside class="cz-sidebar" :class="{ 'cz-sidebar--open': sidebarOpen }">
				<div class="cz-sidebar__head">
					<CzButton variant="primary" wide @click="view = { name: 'create' }">
						New session
					</CzButton>
				</div>
				<nav class="cz-navlist">
					<button
						v-for="session in sessions"
						:key="session.id"
						class="cz-navitem"
						:class="{ 'cz-navitem--active': session.id === activeId }"
						type="button"
						@click="open(session.id)">
						<span class="cz-dot" :class="`cz-dot--${STATUS_TONE[session.status] || 'gray'}`"></span>
						<span class="cz-navitem__name">{{ session.name }}</span>
						<span class="cz-navitem__meta">{{ session.participant_count }}</span>
					</button>
					<p v-if="loaded && !sessions.length" class="cz-muted cz-sidebar__empty">
						No sessions yet.
					</p>
				</nav>
				<div class="cz-sidebar__foot">
					<button
						v-if="isAdmin"
						class="cz-navitem"
						:class="{ 'cz-navitem--active': view.name === 'settings' }"
						type="button"
						@click="view = { name: 'settings' }; sidebarOpen = false">
						<span class="cz-navitem__name">Settings</span>
					</button>
				</div>
			</aside>

			<div v-if="sidebarOpen" class="cz-scrim" @click="sidebarOpen = false"></div>

			<main class="cz-content">
				<div class="cz-mobilebar">
					<CzButton small @click="sidebarOpen = !sidebarOpen">Sessions</CzButton>
				</div>

				<div v-if="view.name === 'empty'" class="cz-empty">
					<h2>Citizens Online</h2>
					<p class="cz-muted">
						Run an online deliberation in Nextcloud Talk: define the rounds, split people
						into breakout rooms, and let the app keep time, capture what is said and draft
						the findings for you to review.
					</p>
					<CzButton variant="primary" @click="view = { name: 'create' }">
						Create your first session
					</CzButton>
				</div>

				<SessionWizard v-else-if="view.name === 'create'" @created="onCreated" @cancel="view = { name: 'empty' }" />
				<SettingsView v-else-if="view.name === 'settings'" />
				<SessionDetail
					v-else-if="view.name === 'detail'"
					:key="view.id"
					:session-id="view.id"
					@deleted="onDeleted"
					@changed="loadSessions" />
			</main>
		</template>

		<CzToasts />
	</div>
</template>
