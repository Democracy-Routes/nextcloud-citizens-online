<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
import { onMounted, ref } from 'vue'
import { api } from '../api'
import CzButton from './ui/CzButton.vue'
import { toast } from './ui/toast'

const props = defineProps<{ session: any }>()
const emit = defineEmits<{ changed: [] }>()
const people = ref<any[]>([])
const input = ref('')
const busy = ref(false)

async function load(): Promise<void> {
	people.value = await api.listParticipants(props.session.id)
}

async function add(): Promise<void> {
	const ids = input.value
		.split(/[\s,;]+/)
		.map((s) => s.trim())
		.filter(Boolean)
	if (!ids.length) return
	busy.value = true
	try {
		const created = await api.addParticipants(
			props.session.id,
			ids.map((id) => ({ nc_user_id: id, display_name: id })),
		)
		toast(`${created.length} participant(s) added`)
		input.value = ''
		await load()
		emit('changed')
	} catch (error: any) {
		toast(error?.message || 'Could not add participants', 'error')
	} finally {
		busy.value = false
	}
}

async function remove(person: any): Promise<void> {
	await api.deleteParticipant(person.id)
	await load()
	emit('changed')
}

onMounted(load)
</script>

<template>
	<div>
		<div class="cz-field">
			<label>Add Nextcloud users</label>
			<input
				v-model="input"
				type="text"
				placeholder="co1 co2 co3 — usernames, separated by spaces or commas"
				@keyup.enter="add" />
		</div>
		<CzButton :disabled="busy" @click="add">{{ busy ? 'Adding…' : 'Add' }}</CzButton>

		<p class="cz-muted cz-small">
			Participants must already have a Nextcloud account on this server; they are added to the
			Talk conversation automatically when a round starts.
		</p>

		<table v-if="people.length" class="cz-table">
			<thead>
				<tr><th>User</th><th>Name</th><th>Role</th><th>Consent</th><th></th></tr>
			</thead>
			<tbody>
				<tr v-for="person in people" :key="person.id">
					<td><code>{{ person.nc_user_id }}</code></td>
					<td>{{ person.display_name }}</td>
					<td>{{ person.role }}</td>
					<td>
						<span v-if="person.consented" class="cz-dot cz-dot--green"></span>
						<span v-else class="cz-dot cz-dot--gray"></span>
					</td>
					<td><CzButton small variant="tertiary" @click="remove(person)">Remove</CzButton></td>
				</tr>
			</tbody>
		</table>
		<p v-else class="cz-muted">No participants yet.</p>
	</div>
</template>
