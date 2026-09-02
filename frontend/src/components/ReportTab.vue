<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { onMounted, ref } from 'vue'
import { api, BASE } from '../api'
import CzButton from './ui/CzButton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ session: any }>()
const emit = defineEmits<{ changed: [] }>()
const report = ref<any>(null)
const includeDrafts = ref(false)
const loading = ref(false)

async function load(): Promise<void> {
	loading.value = true
	try {
		report.value = await api.report(props.session.id, includeDrafts.value)
	} finally {
		loading.value = false
	}
}

function download(kind: 'md' | 'pdf' | 'json'): void {
	window.open(
		`${BASE}/api/v1/sessions/${props.session.id}/report.${kind}?include_drafts=${includeDrafts.value}`,
		'_blank',
	)
}

async function publish(): Promise<void> {
	await api.publishReport(props.session.id)
	toast('Published to participants')
	emit('changed')
}

async function close(): Promise<void> {
	if (!window.confirm('Close the session? The report is frozen at this point.')) return
	await api.closeSession(props.session.id)
	toast('Session closed')
	emit('changed')
}

onMounted(load)
</script>

<template>
	<div>
		<div class="cz-row">
			<label style="display: flex; align-items: center; gap: 8px; cursor: pointer">
				<input v-model="includeDrafts" type="checkbox" @change="load" />
				Include unapproved AI drafts
			</label>
			<CzButton small @click="download('md')">Markdown</CzButton>
			<CzButton small @click="download('pdf')">PDF</CzButton>
			<CzButton small @click="download('json')">JSON</CzButton>
			<CzButton small variant="primary" @click="publish">Publish to participants</CzButton>
			<CzButton v-if="!session.closed_at" small variant="tertiary" @click="close">Close session</CzButton>
		</div>

		<div v-if="loading" class="cz-muted">Loading…</div>
		<div v-else-if="report">
			<h2>{{ report.session.name }}</h2>
			<p class="cz-muted">
				{{ report.session.participants }} participants ·
				{{ report.is_final ? 'final' : 'interim' }} report
			</p>
			<p>{{ report.method }}</p>

			<div v-for="round in report.rounds" :key="round.position" class="cz-card">
				<h3>Round {{ round.position }} — {{ round.title }}</h3>
				<p v-if="round.question"><strong>{{ round.question }}</strong></p>
				<p v-if="round.summary">{{ round.summary }}</p>

				<template v-if="round.cross_room.length">
					<h4>Across all rooms</h4>
					<article v-for="finding in round.cross_room" :key="finding.id" class="cz-finding">
						<strong>{{ finding.title }}</strong>
						<span v-if="finding.is_draft" class="cz-tag cz-tag--draft">draft</span>
						<p>{{ finding.summary }}</p>
						<blockquote v-for="(item, i) in finding.evidence.slice(0, 3)" :key="i">
							<span class="cz-muted">{{ item.speaker }} ({{ item.timestamp }}):</span> {{ item.text }}
						</blockquote>
					</article>
				</template>

				<template v-for="room in round.rooms" :key="room.room_number">
					<template v-if="room.findings.length || room.summary">
						<h4>Room {{ room.room_number }}</h4>
						<p v-if="room.summary" class="cz-muted">{{ room.summary }}</p>
						<article v-for="finding in room.findings" :key="finding.id" class="cz-finding">
							<strong>{{ finding.title }}</strong>
							<span v-if="finding.is_draft" class="cz-tag cz-tag--draft">draft</span>
							<p>{{ finding.summary }}</p>
						</article>
					</template>
				</template>
			</div>

			<p class="cz-muted cz-small">{{ report.methodology_note }}</p>
		</div>
	</div>
</template>
