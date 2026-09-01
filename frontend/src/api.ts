// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later

// Derive the ExApp base URL from our own <script src>, so the app works both
// through /apps/app_api/proxy/citizens_online/... and a /exapps/ rewrite.
function detectBase(): string {
	const current = document.currentScript as HTMLScriptElement | null
	const el =
		current && current.src
			? current
			: document.querySelector<HTMLScriptElement>('script[src*="citizens-online-main"]')
	if (el && el.src) {
		return el.src.replace(/\/js\/citizens-online-main\.js.*$/, '')
	}
	return '/exapps/citizens_online'
}

export const BASE = detectBase()

export class ApiError extends Error {
	status: number

	constructor(status: number, message: string) {
		super(message)
		this.status = status
	}
}

// Partial updates use PUT, never PATCH: AppAPI's proxy registers handlers for
// GET/POST/PUT/DELETE only, so a PATCH is answered 405 by Nextcloud's router
// and never reaches the app. tests/unit/test_proxy_verbs.py enforces this.
async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
	const response = await fetch(BASE + path, {
		method,
		headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body),
		credentials: 'same-origin',
	})
	if (!response.ok) {
		let detail = `HTTP ${response.status}`
		try {
			const data = await response.json()
			if (data && typeof data.detail === 'string') detail = data.detail
		} catch {
			/* not JSON */
		}
		throw new ApiError(response.status, detail)
	}
	if (response.status === 204) return undefined as T
	return (await response.json()) as T
}

export interface RoundIn {
	title?: string
	question?: string
	duration_minutes?: number
}

export const api = {
	// --- organizer -------------------------------------------------------
	listSessions: () => request<any[]>('GET', '/api/v1/sessions'),
	createSession: (data: Record<string, unknown>) =>
		request<any>('POST', '/api/v1/sessions', data),
	getSession: (id: string) => request<any>('GET', `/api/v1/sessions/${id}`),
	updateSession: (id: string, data: Record<string, unknown>) =>
		request<any>('PUT', `/api/v1/sessions/${id}`, data),
	deleteSession: (id: string) => request<void>('DELETE', `/api/v1/sessions/${id}`),

	addRound: (sessionId: string, data: RoundIn) =>
		request<any>('POST', `/api/v1/sessions/${sessionId}/rounds`, data),
	updateRound: (roundId: string, data: Record<string, unknown>) =>
		request<any>('PUT', `/api/v1/rounds/${roundId}`, data),
	deleteRound: (roundId: string) => request<void>('DELETE', `/api/v1/rounds/${roundId}`),
	startRound: (roundId: string) => request<any>('POST', `/api/v1/rounds/${roundId}/start`),
	endRound: (roundId: string) => request<any>('POST', `/api/v1/rounds/${roundId}/end`),
	extendRound: (roundId: string, minutes: number) =>
		request<any>('POST', `/api/v1/rounds/${roundId}/extend`, { minutes }),
	remixRound: (roundId: string) => request<any>('POST', `/api/v1/rounds/${roundId}/remix`),

	listParticipants: (sessionId: string) =>
		request<any[]>('GET', `/api/v1/sessions/${sessionId}/participants`),
	addParticipants: (sessionId: string, participants: Array<Record<string, unknown>>) =>
		request<any[]>('POST', `/api/v1/sessions/${sessionId}/participants`, { participants }),
	deleteParticipant: (id: string) => request<void>('DELETE', `/api/v1/participants/${id}`),

	rooms: (roundId: string) => request<any[]>('GET', `/api/v1/rounds/${roundId}/rooms`),
	randomize: (roundId: string, rooms?: number) =>
		request<any[]>('POST', `/api/v1/rounds/${roundId}/rooms/randomize`, { rooms }),
	copyPrevious: (roundId: string) =>
		request<any[]>('POST', `/api/v1/rounds/${roundId}/rooms/copy-previous`),
	moveParticipant: (roundId: string, participantId: string, roomId: string) =>
		request<any[]>('POST', `/api/v1/rounds/${roundId}/rooms/move`, {
			participant_id: participantId,
			room_id: roomId,
		}),
	messageRoom: (roomId: string, message: string) =>
		request<any>('POST', `/api/v1/rooms/${roomId}/message`, { message }),
	roomTranscript: (roomId: string) => request<any>('GET', `/api/v1/rooms/${roomId}/transcript`),
	monitor: (roundId: string) => request<any>('GET', `/api/v1/rounds/${roundId}/monitor`),

	findings: (roundId: string) => request<any>('GET', `/api/v1/rounds/${roundId}/findings`),
	updateFinding: (id: string, data: Record<string, unknown>) =>
		request<any>('PUT', `/api/v1/findings/${id}`, data),
	analyze: (roundId: string) => request<any>('POST', `/api/v1/rounds/${roundId}/analyze`),

	report: (sessionId: string, includeDrafts: boolean) =>
		request<any>('GET', `/api/v1/sessions/${sessionId}/report?include_drafts=${includeDrafts}`),
	closeSession: (sessionId: string) =>
		request<any>('POST', `/api/v1/sessions/${sessionId}/close`),
	reopenSession: (sessionId: string) =>
		request<void>('DELETE', `/api/v1/sessions/${sessionId}/close`),
	publishReport: (sessionId: string) =>
		request<any>('POST', `/api/v1/sessions/${sessionId}/report/publish`),
	unpublishReport: (sessionId: string) =>
		request<void>('DELETE', `/api/v1/sessions/${sessionId}/report/publish`),

	// --- administrator ---------------------------------------------------
	adminPing: () => request<{ ok: boolean }>('GET', '/api/v1/admin/ping'),
	getProviders: () => request<any>('GET', '/api/v1/admin/providers'),
	updateProviders: (data: Record<string, unknown>) =>
		request<any>('PUT', '/api/v1/admin/providers', data),
	testProvider: (target: string, extra: Record<string, unknown> = {}) =>
		request<{ ok: boolean; message: string }>('POST', '/api/v1/admin/providers/test', {
			target,
			...extra,
		}),

	// --- participant -----------------------------------------------------
	mySession: () => request<any>('GET', '/api/v1/me/session'),
	consent: (accepted: boolean) => request<any>('POST', '/api/v1/me/consent', { accepted }),

	// --- capture ---------------------------------------------------------
	captureStart: (roundId: string, mimeType: string) =>
		request<{ recording_id: string; state: string }>('POST', '/api/v1/capture/start', {
			round_id: roundId,
			mime_type: mimeType,
		}),
	captureComplete: (recordingId: string, totalChunks: number) =>
		request<{ state: string; missing_sequences: number[] }>(
			'POST',
			`/api/v1/capture/${recordingId}/complete`,
			{ total_chunks: totalChunks },
		),
	captureStatus: (recordingId: string) =>
		request<any>('GET', `/api/v1/capture/${recordingId}`),
	captureLive: (recordingId: string) =>
		request<{ active: boolean; lines: Array<{ t: number; text: string; speaker?: string }>; speaking?: any }>(
			'GET',
			`/api/v1/capture/${recordingId}/live`,
		),
	captureHeartbeat: (payload: Record<string, unknown>) =>
		request<{ ok: boolean }>('POST', '/api/v1/capture/heartbeat', payload),
}

/** Raw chunk upload: octet-stream body, so it bypasses the JSON helper. */
export async function uploadChunk(
	recordingId: string,
	sequence: number,
	blob: Blob,
	sha256: string,
): Promise<{ acknowledged: boolean; duplicate: boolean }> {
	const response = await fetch(
		`${BASE}/api/v1/capture/${recordingId}/chunks/${sequence}`,
		{
			method: 'POST',
			headers: {
				'Content-Type': 'application/octet-stream',
				'X-Chunk-SHA256': sha256,
			},
			body: blob,
			credentials: 'same-origin',
		},
	)
	if (!response.ok) {
		let detail = `HTTP ${response.status}`
		try {
			const data = await response.json()
			if (data && typeof data.detail === 'string') detail = data.detail
		} catch {
			/* not JSON */
		}
		throw new ApiError(response.status, detail)
	}
	return await response.json()
}
