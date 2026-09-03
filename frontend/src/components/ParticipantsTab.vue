<script setup lang="ts">
// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Every participant is checked against Nextcloud before it is stored. A name
// that is not a real account used to look perfectly fine here and then simply
// fail to appear in Talk when the round started.
import { computed, onMounted, ref } from 'vue'
import { mdiAccountGroup, mdiPlus, mdiRefresh } from '@mdi/js'
import { api } from '../api'
import CzButton from './ui/CzButton.vue'
import CzEmptyState from './ui/CzEmptyState.vue'
import CzUserPicker, { type DirectoryHit } from './ui/CzUserPicker.vue'
import SvgIcon from './ui/SvgIcon.vue'
import { toast } from './ui/toast'

const props = defineProps<{ session: any }>()
const emit = defineEmits<{ changed: [] }>()

const people = ref<any[]>([])
const busy = ref(false)
const pasteOpen = ref(false)
const pasted = ref('')
const rejected = ref<string[]>([])

/** Groups already imported, derived from the participants themselves. */
const groups = computed(() => {
	const counts = new Map<string, number>()
	for (const person of people.value) {
		if (person.added_via_group) {
			counts.set(person.added_via_group, (counts.get(person.added_via_group) || 0) + 1)
		}
	}
	return [...counts.entries()].map(([id, count]) => ({ id, count }))
})

async function load(): Promise<void> {
	people.value = await api.listParticipants(props.session.id)
}

async function done(message: string): Promise<void> {
	toast(message)
	await load()
	emit('changed')
}

async function pick(hit: DirectoryHit): Promise<void> {
	busy.value = true
	rejected.value = []
	try {
		if (hit.source === 'groups') {
			const result = await api.addParticipantsFromGroup(props.session.id, hit.id)
			await done(
				result.added.length
					? `${result.added.length} of ${result.members} added from ${hit.id}`
					: `Everyone in ${hit.id} was already here`,
			)
		} else {
			const result = await api.addParticipants(props.session.id, [{ nc_user_id: hit.id }])
			await done(result.added.length ? `${hit.label} added` : `${hit.label} was already here`)
		}
	} catch (error: any) {
		toast(error?.message || 'Could not add', 'error')
	} finally {
		busy.value = false
	}
}

async function addPasted(): Promise<void> {
	const ids = pasted.value
		.split(/[\s,;]+/)
		.map((s) => s.trim())
		.filter(Boolean)
	if (!ids.length) return
	busy.value = true
	rejected.value = []
	try {
		const result = await api.addParticipants(
			props.session.id,
			ids.map((id) => ({ nc_user_id: id })),
		)
		rejected.value = result.unknown
		pasted.value = ''
		await done(
			result.unknown.length
				? `${result.added.length} added, ${result.unknown.length} not recognised`
				: `${result.added.length} participant(s) added`,
		)
	} catch (error: any) {
		toast(error?.message || 'Could not add participants', 'error')
	} finally {
		busy.value = false
	}
}

async function resync(groupId: string): Promise<void> {
	busy.value = true
	try {
		const result = await api.resyncGroup(props.session.id, groupId)
		const parts = [`${result.added.length} added`]
		// Departures are reported, never applied: someone who has left the group
		// may already have consented and been recorded in this session.
		if (result.departed.length) {
			parts.push(
				`${result.departed.map((p: any) => p.display_name).join(', ')} left the group ` +
					'and are still here — remove them by hand if you want them gone',
			)
		}
		await done(parts.join('. '))
	} catch (error: any) {
		toast(error?.message || 'Could not re-sync', 'error')
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
			<label>Add people</label>
			<CzUserPicker :disabled="busy" @select="pick" />
		</div>

		<p class="cz-muted cz-small">
			Participants need an account on this server. Adding a group copies its members in once —
			it is a snapshot, so use Re-sync if the group changes later.
		</p>

		<div v-if="groups.length" class="cz-row">
			<span v-for="group in groups" :key="group.id" class="cz-groupchip">
				<SvgIcon :path="mdiAccountGroup" :size="15" />
				<span>{{ group.id }}</span>
				<span class="cz-muted cz-small">{{ group.count }}</span>
				<button type="button" class="cz-groupchip__action" :disabled="busy" @click="resync(group.id)">
					<SvgIcon :path="mdiRefresh" :size="15" />
					<span>Re-sync</span>
				</button>
			</span>
		</div>

		<p>
			<button type="button" class="cz-linklike" @click="pasteOpen = !pasteOpen">
				{{ pasteOpen ? 'Hide the list box' : 'Paste a list of usernames' }}
			</button>
		</p>

		<div v-if="pasteOpen" class="cz-card">
			<div class="cz-field">
				<label>One per line, or separated by spaces or commas</label>
				<textarea v-model="pasted" rows="3" placeholder="co1 co2 co3"></textarea>
			</div>
			<div class="cz-row">
				<CzButton variant="primary" :icon="mdiPlus" :disabled="busy" @click="addPasted">
					{{ busy ? 'Checking…' : 'Add them' }}
				</CzButton>
			</div>
			<p v-if="rejected.length" class="cz-error cz-small">
				Not accounts on this server, so not added: {{ rejected.join(', ') }}
			</p>
		</div>

		<table v-if="people.length" class="cz-table">
			<thead>
				<tr><th>User</th><th>Name</th><th>Added</th><th>Consent</th><th></th></tr>
			</thead>
			<tbody>
				<tr v-for="person in people" :key="person.id">
					<td><code>{{ person.nc_user_id }}</code></td>
					<td>{{ person.display_name }}</td>
					<td>
						<span v-if="person.added_via_group" class="cz-muted cz-small">
							via {{ person.added_via_group }}
						</span>
						<span v-else class="cz-muted cz-small">directly</span>
					</td>
					<td>
						<span v-if="person.consented" class="cz-dot cz-dot--green" title="consented"></span>
						<span v-else class="cz-dot cz-dot--gray" title="not yet"></span>
					</td>
					<td><CzButton small variant="tertiary" @click="remove(person)">Remove</CzButton></td>
				</tr>
			</tbody>
		</table>

		<CzEmptyState
			v-else
			:icon="mdiAccountGroup"
			title="No participants yet"
			hint="Search for people by name above, or add a whole Nextcloud group at once." />
	</div>
</template>
