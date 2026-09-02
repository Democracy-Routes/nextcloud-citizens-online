<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The notice is generated from the live configuration (spec §27), so it cannot
// drift away from what the app actually does. If transcription is off, it does
// not claim to be on; if a hosted provider is configured, it is named.
import { computed } from 'vue'
import CzButton from '../ui/CzButton.vue'

const props = defineProps<{ handling: Record<string, any>; session: Record<string, any> }>()
defineEmits<{ accept: []; decline: [] }>()

const audioDestination = computed(() => {
	if (!props.handling?.stt_enabled) {
		return 'Your audio is recorded and stored on this server. No speech-recognition engine is configured, so it is not sent anywhere.'
	}
	return props.handling.stt_hosted
		? `Your audio is recorded and sent to an external speech-recognition service (${props.handling.stt_provider}) to be turned into text.`
		: 'Your audio is recorded and turned into text by a speech-recognition engine running on this organisation’s own infrastructure.'
})

const analysisDestination = computed(() => {
	if (!props.handling?.analysis_enabled) return 'No AI analysis is configured for this session.'
	return props.handling.analysis_hosted
		? `The text of the discussion (never the audio) is sent to an external AI service at ${props.handling.analysis_endpoint_host} to draft findings, which an organizer reviews.`
		: 'The text of the discussion (never the audio) is analysed by a model running on this organisation’s own infrastructure to draft findings, which an organizer reviews.'
})

const retention = computed(() => {
	const days = props.handling?.audio_retention_days ?? 0
	return days > 0
		? `Recordings are deleted automatically ${days} days after the session closes.`
		: 'Recordings are kept until an organizer deletes them; no automatic deletion is configured.'
})
</script>

<template>
	<div class="cz-page">
		<div class="cz-eyebrow">{{ session.name }}</div>
		<h2>Before you join</h2>
		<p class="cz-muted">
			This is a recorded and AI-assisted deliberation. Please read what that means here.
		</p>

		<ul class="cz-consent__list">
			<li>
				<strong>Your microphone is recorded.</strong> {{ audioDestination }}
			</li>
			<li>
				<strong>Speaking time is measured.</strong> The app measures how long each person
				speaks, from the audio itself, and a facilitator may point out when one voice is
				taking most of the room's time.
			</li>
			<li v-if="handling?.analysis_enabled">
				<strong>AI drafts the findings.</strong> {{ analysisDestination }} Every finding
				quotes the passages it rests on, and nothing is published until a human approves it.
			</li>
			<li v-if="handling?.moderation_enabled">
				<strong>Moderation.</strong> Transcripts are checked for abusive language. Political
				disagreement is not moderated — only conduct. Serious action is always taken by a
				person, never automatically.
			</li>
			<li><strong>Retention.</strong> {{ retention }}</li>
			<li>
				<strong>You can decline.</strong> If you do, you can still watch the discussion, but
				you will not be recorded and nothing you say will enter the transcript.
			</li>
		</ul>

		<div class="cz-row">
			<CzButton variant="primary" @click="$emit('accept')">I understand — let me join</CzButton>
			<CzButton @click="$emit('decline')">Not now</CzButton>
		</div>
	</div>
</template>
