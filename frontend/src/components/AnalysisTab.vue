<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Findings are drafts until a person approves them, and every one shows the
// passages it rests on (spec §17).
import { onMounted, ref, watch } from 'vue'
import { api } from '../api'
import CzButton from './ui/CzButton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ session: any; round: any }>()
const data = ref<any>(null)
const loading = ref(false)

async function load(): Promise<void> {
	if (!props.round) return
	loading.value = true
	try {
		data.value = await api.findings(props.round.id)
	} finally {
		loading.value = false
	}
}

async function review(finding: any, status: string): Promise<void> {
	await api.updateFinding(finding.id, {
		status,
		title: finding.title,
		summary: finding.summary,
	})
	toast(status === 'APPROVED' ? 'Approved' : 'Rejected')
	await load()
}

async function rerun(): Promise<void> {
	try {
		const result = await api.analyze(props.round.id)
		toast(`Analysis queued for ${result.queued} room(s)`)
	} catch (error: any) {
		toast(error?.message || 'Could not queue the analysis', 'error')
	}
}

watch(() => props.round?.id, load)
onMounted(load)
</script>

<template>
	<section class="cz-tabpanel">
		<div v-if="!round" class="cz-empty">
			<h3>Nothing analysed yet</h3>
			<p class="cz-muted">Findings appear here once a round has ended.</p>
		</div>
		<template v-else>
			<div class="cz-actions">
				<CzButton @click="rerun">Re-run analysis for {{ round.title }}</CzButton>
				<CzButton small variant="tertiary" @click="load">Refresh</CzButton>
			</div>
			<div v-if="loading" class="cz-muted">Loading…</div>
			<template v-else-if="data">
				<div v-if="data.cross_room.length" class="cz-card">
					<h3>Across all rooms</h3>
					<article v-for="finding in data.cross_room" :key="finding.id" class="cz-finding">
						<header>
							<span class="cz-tag">{{ finding.type.replaceAll('_', ' ') }}</span>
							<strong>{{ finding.title }}</strong>
							<span v-if="finding.mentioned_room_count" class="cz-muted cz-small">
								· raised in {{ finding.mentioned_room_count }} room(s)
							</span>
						</header>
						<p>{{ finding.summary }}</p>
						<details v-if="finding.evidence.length">
							<summary>{{ finding.evidence.length }} supporting passage(s)</summary>
							<blockquote v-for="(item, i) in finding.evidence" :key="i">
								<span class="cz-muted">{{ item.speaker }} ({{ item.timestamp }}):</span>
								{{ item.text }}
							</blockquote>
						</details>
						<div class="cz-actions">
							<span class="cz-muted cz-small">{{ finding.status.replaceAll('_', ' ').toLowerCase() }}</span>
							<CzButton small variant="primary" @click="review(finding, 'APPROVED')">Approve</CzButton>
							<CzButton small variant="tertiary" @click="review(finding, 'REJECTED')">Reject</CzButton>
						</div>
					</article>
				</div>

				<div v-for="room in data.rooms" :key="room.id" class="cz-card">
					<h3>Room {{ room.number }}</h3>
					<p v-if="room.summary" class="cz-muted">{{ room.summary }}</p>
					<article v-for="finding in room.findings" :key="finding.id" class="cz-finding">
						<header>
							<span class="cz-tag">{{ finding.type.replaceAll('_', ' ') }}</span>
							<strong>{{ finding.title }}</strong>
						</header>
						<p>{{ finding.summary }}</p>
						<details v-if="finding.evidence.length">
							<summary>{{ finding.evidence.length }} supporting passage(s)</summary>
							<blockquote v-for="(item, i) in finding.evidence" :key="i">
								<span class="cz-muted">{{ item.speaker }} ({{ item.timestamp }}):</span>
								{{ item.text }}
							</blockquote>
						</details>
						<div class="cz-actions">
							<span class="cz-muted cz-small">{{ finding.status.replaceAll('_', ' ').toLowerCase() }}</span>
							<CzButton small variant="primary" @click="review(finding, 'APPROVED')">Approve</CzButton>
							<CzButton small variant="tertiary" @click="review(finding, 'REJECTED')">Reject</CzButton>
						</div>
					</article>
					<p v-if="!room.findings.length" class="cz-muted cz-small">No findings for this room.</p>
				</div>
			</template>
		</template>
	</section>
</template>
