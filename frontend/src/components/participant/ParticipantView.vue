<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One screen that follows the deliberation (spec §23). The participant never
// navigates: consent, waiting, the discussion, the result — the server says
// which of those is happening and this component shows it.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../../api'
import { CaptureEngine, unsyncedRecordings } from '../../capture/engine'
import ConsentScreen from './ConsentScreen.vue'
import CzButton from '../ui/CzButton.vue'
import { toast } from '../ui/toast'

const view = ref<any>(null)
const loading = ref(true)
const engine = ref<CaptureEngine | null>(null)
const captions = ref<Array<{ t: number; text: string; speaker?: string }>>([])
const micDenied = ref(false)
const now = ref(Date.now())
let pollTimer = 0
let captionTimer = 0
let clockTimer = 0

const state = computed(() => view.value?.state ?? 'loading')
const round = computed(() => view.value?.round ?? null)
const room = computed(() => view.value?.room ?? null)

const remaining = computed(() => {
	const seconds = round.value?.remaining_seconds
	if (seconds === null || seconds === undefined) return ''
	const total = Math.max(0, seconds - Math.floor((now.value - loadedAt) / 1000))
	const m = Math.floor(total / 60)
	const s = total % 60
	return `${m}:${String(s).padStart(2, '0')}`
})
let loadedAt = Date.now()

const talkUrl = computed(() => {
	const token = room.value?.talk_token
	return token ? `/index.php/call/${token}` : ''
})

async function refresh(): Promise<void> {
	try {
		const next = await api.mySession()
		view.value = next
		loadedAt = Date.now()
	} catch (error) {
		// a transient failure must not blank the participant's screen
		console.warn('participant poll failed', error)
	} finally {
		loading.value = false
	}
}

async function accept(): Promise<void> {
	await api.consent(true)
	await refresh()
	toast('Thank you — you can join when your group opens.')
}

async function decline(): Promise<void> {
	await api.consent(false)
	await refresh()
}

async function startCapture(): Promise<void> {
	if (!round.value || engine.value || !view.value?.session?.capture_enabled) return
	const captureEngine = new CaptureEngine()
	try {
		await captureEngine.start(round.value.id)
		engine.value = captureEngine
		micDenied.value = false
	} catch (error) {
		micDenied.value = true
		console.warn('capture could not start', error)
	}
}

async function stopCapture(): Promise<void> {
	const captureEngine = engine.value
	if (!captureEngine) return
	try {
		await captureEngine.finish()
	} catch (error) {
		console.warn('capture finish failed', error)
	}
}

async function pollCaptions(): Promise<void> {
	const id = engine.value?.state.recordingId
	if (!id) return
	try {
		const result = await api.captureLive(id)
		captions.value = result.lines.slice(-25)
	} catch {
		/* captions are best-effort and never block the round */
	}
}

// The round starting and ending is what drives capture, not a button.
watch(
	() => [state.value, round.value?.id],
	async ([newState, roundId], old) => {
		if (newState === 'in_round' && roundId && !engine.value) {
			await startCapture()
		}
		if (engine.value && (newState !== 'in_round' || (old && old[1] && roundId !== old[1]))) {
			await stopCapture()
			engine.value = null
			captions.value = []
		}
	},
)

onMounted(async () => {
	await refresh()
	pollTimer = window.setInterval(refresh, 4000)
	captionTimer = window.setInterval(pollCaptions, 6000)
	clockTimer = window.setInterval(() => (now.value = Date.now()), 1000)
	const stranded = await unsyncedRecordings()
	if (stranded.length) {
		toast(`${stranded.length} earlier recording(s) are still stored on this device.`, 'error')
	}
	window.addEventListener('beforeunload', warnIfRecording)
})

function warnIfRecording(event: BeforeUnloadEvent): void {
	if (engine.value?.state.phase === 'recording') {
		event.preventDefault()
		event.returnValue = ''
	}
}

onBeforeUnmount(() => {
	window.clearInterval(pollTimer)
	window.clearInterval(captionTimer)
	window.clearInterval(clockTimer)
	window.removeEventListener('beforeunload', warnIfRecording)
	void stopCapture()
})
</script>

<template>
	<div class="cz-participant">
		<div v-if="loading" class="cz-muted">Loading…</div>

		<div v-else-if="state === 'none'" class="cz-empty">
			<h2>Nothing to attend</h2>
			<p class="cz-muted">
				You are not currently a participant in any deliberation. When an organizer adds you,
				this page will tell you what to do.
			</p>
		</div>

		<ConsentScreen
			v-else-if="state === 'consent'"
			:handling="view.data_handling"
			:session="view.session"
			@accept="accept"
			@decline="decline"
		/>

		<div v-else-if="state === 'in_round'">
			<header class="cz-round__head">
				<div>
					<div class="cz-eyebrow">{{ view.session.name }} · Room {{ room.number }}</div>
					<h2>{{ round.title }}</h2>
				</div>
				<div class="cz-timer" :class="{ 'cz-timer--urgent': (round.remaining_seconds ?? 999) < 120 }">
					{{ remaining }}
				</div>
			</header>

			<p v-if="round.question" class="cz-question">{{ round.question }}</p>

			<div class="cz-row">
				<a class="cz-btn cz-btn--primary" :href="talkUrl" target="_blank" rel="noopener">
					Join the discussion
				</a>
				<span class="cz-muted cz-small">
					Opens Nextcloud Talk in a new tab. Keep <strong>this</strong> tab open — it is
					recording your microphone.
				</span>
			</div>

			<div class="cz-capture" :class="`cz-capture--${engine?.state.phase ?? 'idle'}`">
				<template v-if="!view.session.capture_enabled">
					<span class="cz-dot cz-dot--gray"></span> Recording is switched off for this session.
				</template>
				<template v-else-if="micDenied">
					<span class="cz-dot cz-dot--red"></span>
					No microphone access. The discussion still works, but nothing you say will reach
					the transcript.
					<CzButton small @click="startCapture">Try again</CzButton>
				</template>
				<template v-else-if="engine?.state.phase === 'recording'">
					<span class="cz-dot cz-dot--red cz-dot--pulse"></span>
					Recording · {{ engine.state.ackedChunks }}/{{ engine.state.localChunks }} uploaded
					<span v-if="!engine.state.uploadOnline" class="cz-muted">
						· offline, kept on this device
					</span>
				</template>
				<template v-else-if="engine?.state.phase">
					<span class="cz-dot cz-dot--amber"></span> {{ engine.state.phase }}
				</template>
				<template v-else>
					<span class="cz-dot cz-dot--gray"></span> Starting the microphone…
				</template>
			</div>

			<section v-if="captions.length" class="cz-captions">
				<h3>What has been heard</h3>
				<p v-for="(line, index) in captions" :key="index">
					<span class="cz-muted">{{ line.speaker || 'You' }}:</span> {{ line.text }}
				</p>
			</section>

			<section class="cz-card">
				<h3>In your room</h3>
				<ul>
					<li v-for="member in room.members" :key="member.nc_user_id">
						{{ member.display_name || member.nc_user_id }}
					</li>
				</ul>
			</section>
		</div>

		<div v-else-if="state === 'unassigned'" class="cz-empty">
			<h2>A round is running</h2>
			<p class="cz-muted">
				You have not been placed in a room for this round. The organizer can still add you.
			</p>
		</div>

		<div v-else-if="state === 'published'" class="cz-empty">
			<h2>{{ view.session.name }}</h2>
			<p class="cz-muted">The results of this deliberation have been published.</p>
		</div>

		<div v-else class="cz-empty">
			<h2>{{ view.session?.name || 'Waiting' }}</h2>
			<p class="cz-muted">
				Nothing is running right now. This page will change by itself when the next round
				opens — you can leave it open.
			</p>
		</div>
	</div>
</template>
