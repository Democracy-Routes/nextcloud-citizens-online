<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Secrets are written to Nextcloud's AppConfig and never come back: the form
// shows a hint like "…a91f" so an administrator can tell whether a key is set
// without the value ever being sent to the browser again.
import { onMounted, ref } from 'vue'
import { api } from '../api'
import CzButton from './ui/CzButton.vue'
import { toast } from './ui/toast'

const settings = ref<any>(null)
const llmKey = ref('')
const sttKey = ref('')
const saving = ref(false)
const probe = ref<Record<string, string>>({})

async function load(): Promise<void> {
	settings.value = await api.getProviders()
}

async function save(): Promise<void> {
	saving.value = true
	try {
		const payload: Record<string, unknown> = {
			llm_base_url: settings.value.llm_base_url,
			llm_model: settings.value.llm_model,
			llm_enabled: settings.value.llm_enabled,
			stt_provider: settings.value.stt_provider,
			stt_live_enabled: settings.value.stt_live_enabled,
			stt_batch_enabled: settings.value.stt_batch_enabled,
			vosk_url: settings.value.vosk_url,
			vosk_language_models: settings.value.vosk_language_models,
			whisper_base_url: settings.value.whisper_base_url,
			facilitator_enabled: settings.value.facilitator_enabled,
			policy_preset: settings.value.policy_preset,
			moderation_enabled: settings.value.moderation_enabled,
			organization_name: settings.value.organization_name,
			audio_retention_days: settings.value.audio_retention_days,
			talk_service_user: settings.value.talk_service_user,
			analysis_extra_instructions: settings.value.analysis_extra_instructions,
		}
		if (llmKey.value) payload.llm_api_key = llmKey.value
		if (sttKey.value) payload.stt_api_key = sttKey.value
		settings.value = await api.updateProviders(payload)
		llmKey.value = ''
		sttKey.value = ''
		toast('Settings saved')
	} catch (error: any) {
		toast(error?.message || 'Could not save', 'error')
	} finally {
		saving.value = false
	}
}

async function test(target: string): Promise<void> {
	probe.value[target] = 'Testing…'
	try {
		const result = await api.testProvider(target)
		probe.value[target] = result.message
		toast(result.ok ? 'Reachable' : 'Not reachable', result.ok ? 'success' : 'error')
	} catch (error: any) {
		probe.value[target] = error?.message || 'failed'
	}
}

onMounted(load)
</script>

<template>
	<div v-if="!settings" class="cz-muted">Loading…</div>
	<div v-else class="cz-panel">
		<h2>Settings</h2>
		<p class="cz-muted">
			These apply to every session on this server. Nothing leaves your infrastructure unless you
			configure an external endpoint here — and participants are told which one.
		</p>

		<h3>Language model</h3>
		<p class="cz-muted cz-small">
			Used by the facilitator to phrase its messages and by the analysis to draft findings. Any
			OpenAI-compatible endpoint works, including your own.
		</p>
		<div class="cz-field-row">
			<label class="cz-field cz-field--grow">
				<span>Base URL</span>
				<input v-model="settings.llm_base_url" type="text" placeholder="https://ollama.com/v1" />
			</label>
			<label class="cz-field">
				<span>Model</span>
				<input v-model="settings.llm_model" type="text" placeholder="glm-5.2:cloud" />
			</label>
		</div>
		<label class="cz-field">
			<span>
				API key
				<em v-if="settings.llm_api_key_set" class="cz-muted">— currently set ({{ settings.llm_api_key_hint }})</em>
			</span>
			<input v-model="llmKey" type="password" autocomplete="off" placeholder="leave empty to keep the current key" />
		</label>
		<div class="cz-actions">
			<CzButton small @click="test('llm')">Test</CzButton>
			<span class="cz-muted cz-small">{{ probe.llm }}</span>
		</div>

		<h3>Speech to text</h3>
		<div class="cz-field-row">
			<label class="cz-field">
				<span>Engine</span>
				<select v-model="settings.stt_provider">
					<option value="vosk">Vosk (self-hosted)</option>
					<option value="whisper">Whisper / OpenAI-compatible</option>
					<option value="mistral">Mistral Voxtral</option>
					<option value="none">None</option>
				</select>
			</label>
			<label class="cz-field cz-field--grow">
				<span>Vosk server URL</span>
				<input v-model="settings.vosk_url" type="text" placeholder="ws://citizens-vosk:2700" />
			</label>
		</div>
		<label class="cz-field">
			<span>Vosk models per language</span>
			<input v-model="settings.vosk_language_models" type="text"
				placeholder="en=/models/vosk-model-small-en-us-0.15,it=/models/vosk-model-small-it-0.22" />
		</label>
		<div class="cz-actions">
			<CzButton small @click="test('vosk')">Test</CzButton>
			<span class="cz-muted cz-small">{{ probe.vosk }}</span>
		</div>

		<h3>Facilitation and moderation</h3>
		<div class="cz-checks">
			<label><input v-model="settings.facilitator_enabled" true-value="1" false-value="0" type="checkbox" /> Facilitator bot</label>
			<label><input v-model="settings.moderation_enabled" true-value="1" false-value="0" type="checkbox" /> Check transcripts for abusive language</label>
		</div>
		<div class="cz-field-row">
			<label class="cz-field">
				<span>Default speaking policy</span>
				<select v-model="settings.policy_preset">
					<option value="gentle">Gentle</option>
					<option value="strict">Strict</option>
				</select>
			</label>
			<label class="cz-field">
				<span>Talk service account</span>
				<input v-model="settings.talk_service_user" type="text" />
			</label>
			<label class="cz-field">
				<span>Delete audio after (days, 0 = never)</span>
				<input v-model="settings.audio_retention_days" type="number" min="0" max="3650" />
			</label>
		</div>

		<label class="cz-field">
			<span>Extra analysis instructions <em class="cz-muted">(appended, never overrides the evidence rules)</em></span>
			<textarea v-model="settings.analysis_extra_instructions" rows="3"></textarea>
		</label>
		<label class="cz-field">
			<span>Organisation name (shown on reports)</span>
			<input v-model="settings.organization_name" type="text" />
		</label>

		<div class="cz-actions">
			<CzButton variant="primary" :disabled="saving" @click="save">
				{{ saving ? 'Saving…' : 'Save settings' }}
			</CzButton>
		</div>
	</div>
</template>
