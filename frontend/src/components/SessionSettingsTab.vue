<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Until this existed, nothing about a session could be changed after it was
// created. The whole form closes while a round is running: these settings pick
// the speech model, drive the facilitator and decide how many rooms the next
// distribution builds, so changing them mid-round would leave the session's
// record disagreeing with what actually happened.
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import CzButton from './ui/CzButton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ session: any }>()
const emit = defineEmits<{ changed: [] }>()

const form = ref<Record<string, any>>({})
const saving = ref(false)
const error = ref('')

const liveRound = computed(() =>
	(props.session.rounds || []).find((r: any) => r.status === 'ACTIVE') || null,
)
const locked = computed(() => liveRound.value !== null)

const FIELDS = [
	'name', 'description', 'language', 'rooms_per_round', 'policy_preset',
	'speaking_policy', 'analysis_instructions', 'audio_retention_days',
	'facilitator_enabled', 'capture_enabled',
]

function load(): void {
	form.value = Object.fromEntries(FIELDS.map((f) => [f, props.session[f]]))
	error.value = ''
}
watch(() => props.session, load, { immediate: true, deep: false })

const dirty = computed(() => FIELDS.some((f) => form.value[f] !== props.session[f]))

async function save(): Promise<void> {
	if (!form.value.name?.trim()) {
		error.value = 'A session needs a name.'
		return
	}
	saving.value = true
	error.value = ''
	try {
		await api.updateSession(props.session.id, form.value)
		toast('Session updated')
		emit('changed')
	} catch (e: any) {
		error.value = e?.message || 'Could not save'
		toast(error.value, 'error')
	} finally {
		saving.value = false
	}
}
</script>

<template>
	<div>
		<div v-if="locked" class="cz-card cz-warn">
			<strong>Round {{ liveRound.position }} is running.</strong>
			<p class="cz-muted cz-small">
				These settings choose the speech model, drive the facilitator and decide how rooms are
				built, so they cannot change while a round is live. End the round to edit them.
			</p>
		</div>

		<div class="cz-field">
			<label>Name</label>
			<input v-model="form.name" type="text" maxlength="200" :disabled="locked" />
		</div>

		<div class="cz-field">
			<label>Description</label>
			<textarea v-model="form.description" rows="2" maxlength="5000" :disabled="locked"></textarea>
		</div>

		<div class="cz-fieldgrid">
			<div class="cz-field">
				<label>Language</label>
				<select v-model="form.language" :disabled="locked">
					<option value="en">English</option>
					<option value="it">Italian</option>
					<option value="de">German</option>
					<option value="fr">French</option>
					<option value="es">Spanish</option>
					<option value="nl">Dutch</option>
					<option value="pt">Portuguese</option>
				</select>
			</div>
			<div class="cz-field" style="max-width: 180px">
				<label>Rooms per round</label>
				<input v-model.number="form.rooms_per_round" type="number" min="1" max="20" :disabled="locked" />
			</div>
			<div class="cz-field">
				<label>Facilitation</label>
				<select v-model="form.policy_preset" :disabled="locked">
					<option value="gentle">Gentle</option>
					<option value="strict">Strict</option>
				</select>
			</div>
		</div>

		<div class="cz-field">
			<label>Speaking-time policy</label>
			<select v-model="form.speaking_policy" :disabled="locked">
				<option value="soft_balanced">Nudge when one voice dominates</option>
				<option value="none">Do not comment on speaking time</option>
			</select>
		</div>

		<div class="cz-field">
			<label>Analysis instructions <em class="cz-muted">(optional)</em></label>
			<textarea
				v-model="form.analysis_instructions"
				rows="3"
				maxlength="4000"
				placeholder="Anything the analysis should pay particular attention to."
				:disabled="locked"></textarea>
		</div>

		<div class="cz-field" style="max-width: 260px">
			<label>Keep audio for (days)</label>
			<input v-model.number="form.audio_retention_days" type="number" min="0" max="3650" :disabled="locked" />
			<span class="cz-muted cz-small">0 uses the server-wide default, it does not mean “keep forever”.</span>
		</div>

		<div class="cz-checks">
			<label><input v-model="form.facilitator_enabled" type="checkbox" :disabled="locked" /> Facilitator bot posts in the rooms</label>
			<label><input v-model="form.capture_enabled" type="checkbox" :disabled="locked" /> Record participants’ microphones for the transcript</label>
		</div>

		<p v-if="error" class="cz-error">{{ error }}</p>

		<div class="cz-row">
			<CzButton variant="primary" :disabled="locked || saving || !dirty" @click="save">
				{{ saving ? 'Saving…' : 'Save changes' }}
			</CzButton>
			<CzButton v-if="dirty && !locked" variant="tertiary" @click="load">Discard</CzButton>
			<span v-if="!dirty && !locked" class="cz-muted cz-small">No unsaved changes.</span>
		</div>
	</div>
</template>
