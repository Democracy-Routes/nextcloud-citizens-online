<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { ref } from 'vue'
import { api } from '../api'
import CzButton from './ui/CzButton.vue'
import CzStatusPill from './ui/CzStatusPill.vue'
import { toast } from './ui/toast'

const props = defineProps<{ session: any }>()
const emit = defineEmits<{ changed: []; goLive: [] }>()
const busy = ref('')

async function start(round: any): Promise<void> {
	busy.value = round.id
	try {
		const result = await api.startRound(round.id)
		toast(`Round started in ${result.rooms?.length ?? 0} Talk rooms`)
		emit('changed')
		emit('goLive')
	} catch (error: any) {
		toast(error?.message || 'Could not start the round', 'error')
	} finally {
		busy.value = ''
	}
}

async function end(round: any): Promise<void> {
	busy.value = round.id
	try {
		await api.endRound(round.id)
		toast('Round ended — analysis queued')
		emit('changed')
	} catch (error: any) {
		toast(error?.message || 'Could not end the round', 'error')
	} finally {
		busy.value = ''
	}
}

async function addRound(): Promise<void> {
	await api.addRound(props.session.id, {
		title: `Round ${props.session.rounds.length + 1}`,
		question: '',
		duration_minutes: 20,
	})
	emit('changed')
}

async function save(round: any): Promise<void> {
	await api.updateRound(round.id, {
		title: round.title,
		question: round.question,
		duration_minutes: round.duration_minutes,
	})
	toast('Saved')
	emit('changed')
}

async function remove(round: any): Promise<void> {
	if (!window.confirm(`Delete ${round.title}?`)) return
	await api.deleteRound(round.id)
	emit('changed')
}
</script>

<template>
	<section class="cz-tabpanel">
		<div v-for="round in session.rounds" :key="round.id" class="cz-card">
			<div class="cz-card__head">
				<h3>{{ round.title }}</h3>
				<CzStatusPill :status="round.status" />
			</div>
			<div class="cz-field-row">
				<label class="cz-field cz-field--grow">
					<span>Question</span>
					<input v-model="round.question" type="text" maxlength="4000" @blur="save(round)" />
				</label>
				<label class="cz-field cz-field--narrow">
					<span>Minutes</span>
					<input v-model.number="round.duration_minutes" type="number" min="1" max="480" @blur="save(round)" />
				</label>
			</div>
			<div class="cz-actions">
				<CzButton
					v-if="round.status === 'NOT_STARTED'"
					variant="primary"
					:disabled="busy === round.id"
					@click="start(round)">
					{{ busy === round.id ? 'Starting…' : 'Start round' }}
				</CzButton>
				<CzButton v-else-if="round.status === 'ACTIVE'" variant="danger" :disabled="busy === round.id" @click="end(round)">
					End round
				</CzButton>
				<span v-else class="cz-muted cz-small">
					{{ round.summary ? round.summary.slice(0, 160) : 'Finished' }}
				</span>
				<CzButton v-if="round.status === 'NOT_STARTED'" small variant="tertiary" @click="remove(round)">
					Delete
				</CzButton>
			</div>
		</div>
		<CzButton @click="addRound">Add a round</CzButton>
	</section>
</template>
