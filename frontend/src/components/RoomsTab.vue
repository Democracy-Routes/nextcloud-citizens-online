<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import CzButton from './ui/CzButton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ session: any }>()
const emit = defineEmits<{ changed: [] }>()

const selectedRound = ref<string>(props.session.rounds?.[0]?.id || '')
const rooms = ref<any[]>([])
const loading = ref(false)

const round = computed(() =>
	(props.session.rounds || []).find((r: any) => r.id === selectedRound.value),
)

async function load(): Promise<void> {
	if (!selectedRound.value) return
	loading.value = true
	try {
		rooms.value = await api.rooms(selectedRound.value)
	} finally {
		loading.value = false
	}
}

async function randomize(): Promise<void> {
	rooms.value = await api.randomize(selectedRound.value)
	toast('Participants distributed')
	emit('changed')
}

async function copyPrevious(): Promise<void> {
	rooms.value = await api.copyPrevious(selectedRound.value)
	toast('Copied the previous round')
}

async function move(participantId: string, roomId: string): Promise<void> {
	rooms.value = await api.moveParticipant(selectedRound.value, participantId, roomId)
}

watch(selectedRound, load, { immediate: true })
</script>

<template>
	<div>
		<div class="cz-fieldgrid">
			<div class="cz-field">
				<label>Round</label>
				<select v-model="selectedRound">
					<option v-for="r in session.rounds" :key="r.id" :value="r.id">
						{{ r.title }} — {{ r.status.replaceAll('_', ' ').toLowerCase() }}
					</option>
				</select>
			</div>
			<CzButton @click="randomize">Distribute randomly</CzButton>
			<CzButton @click="copyPrevious">Copy previous round</CzButton>
		</div>

		<p v-if="round && round.status === 'ACTIVE'" class="cz-muted cz-small">
			This round is running. Moving someone here changes the plan; use <strong>Remix</strong> on
			the Live tab to apply it to the open Talk rooms.
		</p>

		<div v-if="loading" class="cz-muted">Loading…</div>
		<div v-else class="cz-rooms">
			<div v-for="room in rooms" :key="room.id" class="cz-card">
				<div class="cz-row cz-row--spread" style="flex-wrap: nowrap; align-items: flex-start">
					<h3>{{ room.label || `Room ${room.number}` }}</h3>
					<span class="cz-muted cz-small">{{ room.members.length }} people</span>
				</div>
				<ul class="cz-memberlist">
					<li v-for="member in room.members" :key="member.participant_id">
						{{ member.display_name || member.nc_user_id }}
						<select
							class="cz-inline-select"
							:value="room.id"
							@change="move(member.participant_id, ($event.target as HTMLSelectElement).value)">
							<option v-for="target in rooms" :key="target.id" :value="target.id">
								Room {{ target.number }}
							</option>
						</select>
					</li>
				</ul>
				<p v-if="!room.members.length" class="cz-muted cz-small">Empty</p>
			</div>
		</div>
	</div>
</template>
