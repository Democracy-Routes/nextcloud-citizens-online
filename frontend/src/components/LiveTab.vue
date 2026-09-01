<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The moderator's view of a running round (spec §22): who is speaking, how
// much, what the facilitator has said, and the four actions worth having
// within reach — message a room, extend, remix, end.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import CzButton from './ui/CzButton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ session: any; round: any }>()
const emit = defineEmits<{ changed: [] }>()

const data = ref<any>(null)
const transcript = ref<any>(null)
const openTranscriptRoom = ref('')
const now = ref(Date.now())
let poll = 0
let clock = 0
let loadedAt = Date.now()

const remaining = computed(() => {
	const base = data.value?.remaining_seconds
	if (base === null || base === undefined) return null
	return Math.max(0, base - Math.floor((now.value - loadedAt) / 1000))
})

const remainingLabel = computed(() => {
	if (remaining.value === null) return '—'
	const m = Math.floor(remaining.value / 60)
	const s = remaining.value % 60
	return `${m}:${String(s).padStart(2, '0')}`
})

function share(member: any): number {
	return Math.round((member.share || 0) * 100)
}

function minutes(ms: number): string {
	const total = Math.round((ms || 0) / 1000)
	return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

async function refresh(): Promise<void> {
	if (!props.round) return
	try {
		data.value = await api.monitor(props.round.id)
		loadedAt = Date.now()
	} catch (error) {
		console.warn('monitor poll failed', error)
	}
}

async function messageRoom(room: any): Promise<void> {
	const text = window.prompt(`Message to room ${room.number}`)
	if (!text) return
	await api.messageRoom(room.id, text)
	toast('Message sent')
}

async function extend(): Promise<void> {
	await api.extendRound(props.round.id, 5)
	toast('Five more minutes')
	await refresh()
	emit('changed')
}

async function remix(): Promise<void> {
	const result = await api.remixRound(props.round.id)
	toast(`Applied the current plan to Talk (${result.moved} people)`)
}

async function end(): Promise<void> {
	if (!window.confirm('End this round for everyone?')) return
	await api.endRound(props.round.id)
	toast('Round ended')
	emit('changed')
}

async function showTranscript(room: any): Promise<void> {
	if (openTranscriptRoom.value === room.id) {
		openTranscriptRoom.value = ''
		return
	}
	transcript.value = await api.roomTranscript(room.id)
	openTranscriptRoom.value = room.id
}

onMounted(() => {
	void refresh()
	poll = window.setInterval(refresh, 4000)
	clock = window.setInterval(() => (now.value = Date.now()), 1000)
})
onBeforeUnmount(() => {
	window.clearInterval(poll)
	window.clearInterval(clock)
})
</script>

<template>
	<section class="cz-tabpanel">
		<div v-if="!round" class="cz-empty">
			<h3>No round is running</h3>
			<p class="cz-muted">Start one from the Rounds tab and this page will fill with life.</p>
		</div>

		<template v-else-if="data">
			<div class="cz-livebar">
				<div>
					<div class="cz-eyebrow">{{ round.title }}</div>
					<div class="cz-timer" :class="{ 'cz-timer--urgent': (remaining ?? 999) < 120 }">
						{{ remainingLabel }}
					</div>
				</div>
				<div class="cz-livebar__actions">
					<CzButton small @click="extend">+5 min</CzButton>
					<CzButton small @click="remix">Apply plan (remix)</CzButton>
					<CzButton small variant="danger" @click="end">End round</CzButton>
				</div>
			</div>

			<div class="cz-statusline">
				<span :class="data.facilitator.enabled ? 'cz-ok' : 'cz-muted'">
					Facilitator {{ data.facilitator.enabled ? 'on' : 'off' }}
				</span>
				<span v-if="data.facilitator.enabled && !data.facilitator.configured" class="cz-warn">
					· no language model configured, so it cannot speak
				</span>
				<span v-else-if="data.facilitator.degraded" class="cz-warn">
					· degraded: {{ data.facilitator.missed }} message(s) missed their moment
				</span>
				<span class="cz-muted">· {{ data.capture.active }} microphone(s) recording</span>
			</div>

			<div class="cz-rooms">
				<div v-for="room in data.rooms" :key="room.id" class="cz-card">
					<div class="cz-card__head">
						<h3>Room {{ room.number }}</h3>
						<span class="cz-muted cz-small">{{ minutes(room.speaking_ms) }} spoken</span>
					</div>
					<ul class="cz-speaking">
						<li v-for="member in room.members" :key="member.participant_id">
							<span class="cz-speaking__name">
								<span v-if="member.speaking_now" class="cz-dot cz-dot--red cz-dot--pulse"></span>
								<span v-else-if="member.capturing" class="cz-dot cz-dot--green"></span>
								<span v-else class="cz-dot cz-dot--gray"></span>
								{{ member.display_name || member.nc_user_id }}
							</span>
							<span class="cz-bar"><span class="cz-bar__fill" :style="{ width: share(member) + '%' }"></span></span>
							<span class="cz-speaking__pct">{{ share(member) }}%</span>
						</li>
					</ul>
					<div class="cz-actions">
						<CzButton small @click="messageRoom(room)">Message room</CzButton>
						<CzButton small variant="tertiary" @click="showTranscript(room)">
							{{ openTranscriptRoom === room.id ? 'Hide' : 'Transcript' }}
						</CzButton>
						<a v-if="room.talk_token" class="cz-link" :href="`/index.php/call/${room.talk_token}`" target="_blank" rel="noopener">Open in Talk</a>
					</div>
					<div v-if="openTranscriptRoom === room.id" class="cz-transcript">
						<p v-for="segment in transcript?.segments || []" :key="segment.id">
							<span class="cz-muted">{{ segment.speaker }}:</span> {{ segment.text }}
						</p>
						<p v-if="!(transcript?.segments || []).length" class="cz-muted cz-small">
							Nothing transcribed yet.
						</p>
					</div>
				</div>
			</div>

			<div v-if="data.alerts.length" class="cz-card">
				<h3>Facilitator and moderation log</h3>
				<ul class="cz-alerts">
					<li v-for="alert in data.alerts" :key="alert.id">
						<strong>{{ alert.type.replaceAll('_', ' ') }}</strong>
						<span v-if="alert.observed !== null" class="cz-muted">
							· {{ alert.rule }} {{ Math.round((alert.observed || 0) * 100) }}%
							(threshold {{ Math.round((alert.threshold || 0) * 100) }}%)
						</span>
						<div>{{ alert.message }}</div>
					</li>
				</ul>
			</div>
		</template>
	</section>
</template>
