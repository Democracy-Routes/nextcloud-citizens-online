<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import AnalysisTab from './AnalysisTab.vue'
import LiveTab from './LiveTab.vue'
import ParticipantsTab from './ParticipantsTab.vue'
import ReportTab from './ReportTab.vue'
import RoomsTab from './RoomsTab.vue'
import RoundsTab from './RoundsTab.vue'
import CzButton from './ui/CzButton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import { toast } from './ui/toast'

const props = defineProps<{ sessionId: string }>()
const emit = defineEmits<{ deleted: []; changed: [] }>()

const session = ref<any>(null)
const tab = ref('rounds')
const loading = ref(true)

const activeRound = computed(
	() => (session.value?.rounds || []).find((r: any) => r.status === 'ACTIVE') || null,
)
const reviewRound = computed(
	() =>
		(session.value?.rounds || []).find((r: any) => r.status === 'READY_FOR_REVIEW') ||
		(session.value?.rounds || []).slice().reverse().find((r: any) => r.status !== 'NOT_STARTED') ||
		null,
)

const TABS = [
	{ id: 'rounds', label: 'Rounds' },
	{ id: 'participants', label: 'Participants' },
	{ id: 'rooms', label: 'Rooms' },
	{ id: 'live', label: 'Live' },
	{ id: 'analysis', label: 'Analysis' },
	{ id: 'report', label: 'Report' },
]

async function load(): Promise<void> {
	loading.value = true
	try {
		session.value = await api.getSession(props.sessionId)
		if (activeRound.value) tab.value = 'live'
	} finally {
		loading.value = false
	}
}

async function refresh(): Promise<void> {
	session.value = await api.getSession(props.sessionId)
	emit('changed')
}

async function remove(): Promise<void> {
	if (!window.confirm(`Delete “${session.value.name}” and everything in it?`)) return
	await api.deleteSession(props.sessionId)
	toast('Session deleted')
	emit('deleted')
}

onMounted(load)
</script>

<template>
	<div v-if="loading" class="cz-muted">Loading…</div>
	<div v-else-if="session" class="cz-page">
		<div class="cz-pagehead">
			<div style="min-width: 0">
				<h2 style="overflow-wrap: anywhere">{{ session.name }}</h2>
				<p class="cz-muted" style="margin: 4px 0 0">
					{{ session.participant_count }} participants ·
					{{ session.round_count }} rounds ·
					{{ session.rooms_per_round }} rooms per round
				</p>
			</div>
			<div class="cz-row" style="flex-wrap: nowrap">
				<CzStatusPill :status="session.status" />
				<CzButton small variant="tertiary" @click="remove">Delete</CzButton>
			</div>
		</div>

		<nav class="cz-tabs" role="tablist">
			<button
				v-for="item in TABS"
				:key="item.id"
				:id="`session-tab-${item.id}`"
				class="cz-tab"
				:class="{ 'cz-tab--active': tab === item.id }"
				role="tab"
				:aria-selected="tab === item.id"
				:aria-controls="`session-panel-${item.id}`"
				:tabindex="tab === item.id ? 0 : -1"
				type="button"
				@click="tab = item.id">
				{{ item.label }}
				<span v-if="item.id === 'live' && activeRound" class="cz-dot cz-dot--red cz-dot--pulse"></span>
			</button>
		</nav>

		<div
			:id="`session-panel-${tab}`"
			role="tabpanel"
			:aria-labelledby="`session-tab-${tab}`"
			tabindex="0">
			<RoundsTab v-if="tab === 'rounds'" :session="session" @changed="refresh" @go-live="tab = 'live'" />
			<ParticipantsTab v-else-if="tab === 'participants'" :session="session" @changed="refresh" />
			<RoomsTab v-else-if="tab === 'rooms'" :session="session" @changed="refresh" />
			<LiveTab v-else-if="tab === 'live'" :session="session" :round="activeRound" @changed="refresh" />
			<AnalysisTab v-else-if="tab === 'analysis'" :session="session" :round="reviewRound" />
			<ReportTab v-else-if="tab === 'report'" :session="session" @changed="refresh" />
		</div>
	</div>
</template>
