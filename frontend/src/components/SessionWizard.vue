<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { ref } from 'vue'
import { api } from '../api'
import CzButton from './ui/CzButton.vue'
import { toast } from './ui/toast'

const emit = defineEmits<{ created: [session: any]; cancel: [] }>()

const name = ref('')
const description = ref('')
const language = ref('en')
const roomsPerRound = ref(2)
const policyPreset = ref('gentle')
const facilitator = ref(true)
const capture = ref(true)
const saving = ref(false)
const error = ref('')

const rounds = ref([
	{ title: 'Round 1', question: '', duration_minutes: 20 },
])

function addRound(): void {
	rounds.value.push({
		title: `Round ${rounds.value.length + 1}`,
		question: '',
		duration_minutes: 20,
	})
}

function removeRound(index: number): void {
	rounds.value.splice(index, 1)
}

async function save(): Promise<void> {
	error.value = ''
	if (!name.value.trim()) {
		error.value = 'Give the session a name.'
		return
	}
	saving.value = true
	try {
		const session = await api.createSession({
			name: name.value.trim(),
			description: description.value.trim(),
			language: language.value,
			rooms_per_round: roomsPerRound.value,
			policy_preset: policyPreset.value,
			facilitator_enabled: facilitator.value,
			capture_enabled: capture.value,
			rounds: rounds.value.filter((r) => r.title.trim() || r.question.trim()),
		})
		emit('created', session)
	} catch (caught: any) {
		error.value = caught?.message || 'Could not create the session.'
		toast(error.value, 'error')
	} finally {
		saving.value = false
	}
}
</script>

<template>
	<div class="cz-page" style="max-width: 720px">
		<h2>New session</h2>
		<p class="cz-muted">
			A session is one online deliberation: a group of people, a sequence of rounds, and the
			breakout rooms they discuss in.
		</p>

		<div class="cz-field">
			<label>Name</label>
			<input v-model="name" type="text" maxlength="200" placeholder="Urban mobility, first assembly" />
		</div>

		<div class="cz-field">
			<label>Description <em class="cz-muted">(optional)</em></label>
			<textarea v-model="description" rows="2" maxlength="5000"></textarea>
		</div>

		<div class="cz-fieldgrid">
			<div class="cz-field">
				<label>Language</label>
				<select v-model="language">
					<option value="en">English</option>
					<option value="it">Italian</option>
					<option value="de">German</option>
					<option value="fr">French</option>
					<option value="es">Spanish</option>
				</select>
			</div>
			<div class="cz-field">
				<label>Rooms per round</label>
				<input v-model.number="roomsPerRound" type="number" min="1" max="20" />
			</div>
			<div class="cz-field">
				<label>Facilitation</label>
				<select v-model="policyPreset">
					<option value="gentle">Gentle</option>
					<option value="strict">Strict</option>
				</select>
			</div>
		</div>

		<div class="cz-checks">
			<label><input v-model="facilitator" type="checkbox" /> Facilitator bot keeps time and speaking balance</label>
			<label><input v-model="capture" type="checkbox" /> Record participants' microphones for the transcript</label>
		</div>

		<h3>Rounds</h3>
		<div v-for="(round, index) in rounds" :key="index" class="cz-round-edit">
			<div class="cz-fieldgrid">
				<div class="cz-field">
					<label>Title</label>
					<input v-model="round.title" type="text" maxlength="200" />
				</div>
				<div class="cz-field" style="max-width: 160px">
					<label>Minutes</label>
					<input v-model.number="round.duration_minutes" type="number" min="1" max="480" />
				</div>
				<CzButton small variant="tertiary" :disabled="rounds.length === 1" @click="removeRound(index)">
					Remove
				</CzButton>
			</div>
			<div class="cz-field">
				<label>Question for this round</label>
				<input v-model="round.question" type="text" maxlength="4000"
					placeholder="What is the most important mobility problem?" />
			</div>
		</div>
		<CzButton small @click="addRound">Add a round</CzButton>

		<p v-if="error" class="cz-error">{{ error }}</p>

		<div class="cz-row">
			<CzButton variant="primary" :disabled="saving" @click="save">
				{{ saving ? 'Creating…' : 'Create session' }}
			</CzButton>
			<CzButton @click="$emit('cancel')">Cancel</CzButton>
		</div>
	</div>
</template>
