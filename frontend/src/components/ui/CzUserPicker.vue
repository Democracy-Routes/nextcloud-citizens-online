<!-- SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
     SPDX-License-Identifier: AGPL-3.0-or-later -->
<script setup lang="ts">
// Searches Nextcloud for people and groups, as the logged-in organizer. What
// comes back is what the server lets them see: an administrator finds everyone,
// an ordinary organizer finds what sharing settings allow.
import { onBeforeUnmount, ref } from 'vue'
import { api } from '../../api'

export interface DirectoryHit {
	id: string
	label: string
	source: 'users' | 'groups'
}

const props = withDefaults(defineProps<{ placeholder?: string; disabled?: boolean }>(), {
	placeholder: 'Search people and groups…',
	disabled: false,
})
const emit = defineEmits<{ select: [DirectoryHit] }>()

const query = ref('')
const results = ref<DirectoryHit[]>([])
const open = ref(false)
const busy = ref(false)
const active = ref(-1)
const error = ref('')

let timer: ReturnType<typeof setTimeout> | undefined
// Responses can arrive out of order; only the newest query may paint.
let sequence = 0

onBeforeUnmount(() => clearTimeout(timer))

function onInput(): void {
	clearTimeout(timer)
	error.value = ''
	if (!query.value.trim()) {
		results.value = []
		open.value = false
		return
	}
	timer = setTimeout(run, 250)
}

async function run(): Promise<void> {
	const mine = ++sequence
	busy.value = true
	try {
		const body = await api.searchDirectory(query.value)
		if (mine !== sequence) return
		results.value = body.results
		active.value = body.results.length ? 0 : -1
		open.value = true
	} catch (e: any) {
		if (mine !== sequence) return
		error.value = e?.message || 'Could not search'
		results.value = []
		open.value = true
	} finally {
		if (mine === sequence) busy.value = false
	}
}

function choose(hit: DirectoryHit): void {
	emit('select', hit)
	query.value = ''
	results.value = []
	open.value = false
	active.value = -1
}

// Closing on blur has to outlast the option's mousedown, or clicking a result
// would dismiss the panel before the choice registers.
function onBlur(): void {
	setTimeout(() => (open.value = false), 150)
}

function onKeydown(event: KeyboardEvent): void {
	if (!open.value || !results.value.length) return
	if (event.key === 'ArrowDown') {
		event.preventDefault()
		active.value = (active.value + 1) % results.value.length
	} else if (event.key === 'ArrowUp') {
		event.preventDefault()
		active.value = (active.value - 1 + results.value.length) % results.value.length
	} else if (event.key === 'Enter' && active.value >= 0) {
		event.preventDefault()
		choose(results.value[active.value])
	} else if (event.key === 'Escape') {
		open.value = false
	}
}
</script>

<template>
	<div class="cz-picker">
		<input
			v-model="query"
			type="text"
			:placeholder="props.placeholder"
			:disabled="props.disabled"
			autocomplete="off"
			role="combobox"
			aria-autocomplete="list"
			:aria-expanded="open"
			@input="onInput"
			@keydown="onKeydown"
			@focus="query.trim() && (open = true)"
			@blur="onBlur" />

		<div v-if="open" class="cz-picker__panel" role="listbox">
			<p v-if="error" class="cz-picker__note cz-error">{{ error }}</p>
			<p v-else-if="busy && !results.length" class="cz-picker__note cz-muted">Searching…</p>
			<p v-else-if="!results.length" class="cz-picker__note cz-muted">
				Nobody matches “{{ query }}”. People must already have an account on this server.
			</p>
			<button
				v-for="(hit, index) in results"
				:key="`${hit.source}:${hit.id}`"
				type="button"
				class="cz-picker__hit"
				:class="{ 'cz-picker__hit--active': index === active }"
				role="option"
				:aria-selected="index === active"
				@mousedown.prevent="choose(hit)"
				@mouseenter="active = index">
				<span class="cz-picker__name">{{ hit.label }}</span>
				<span class="cz-picker__meta">
					{{ hit.source === 'groups' ? 'group' : hit.id }}
				</span>
			</button>
		</div>
	</div>
</template>
