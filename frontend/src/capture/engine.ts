// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Capturing the participant's own microphone.
 *
 * Ported from the in-person app's table recorder, with the discipline that
 * matters kept intact: every chunk is hashed and written to IndexedDB *before*
 * any upload is attempted, uploads are strictly in order and retried forever
 * while recording, and a recording is only "complete" once the server confirms
 * it has every sequence. The network is never the reason audio is lost.
 *
 * Two deliberate differences from the in-person original:
 *
 *  - echo cancellation and noise suppression are **on**. The participant is
 *    listening to a live call through their speakers; without them every
 *    recording would contain everyone else's voice played back.
 *  - identity comes from the Nextcloud session, so there is no bearer token.
 */

import { reactive } from 'vue'
import { api, ApiError, uploadChunk } from '../api'
import { idb, type StoredChunk, type StoredRecording } from './idb'
import { sha256Hex } from './sha'

export const CHUNK_INTERVAL_MS = (() => {
	const override = Number(new URLSearchParams(window.location.search).get('chunkms'))
	return Number.isFinite(override) && override >= 250 ? override : 10_000
})()
const RETRY_BASE_MS = 3_000
const RETRY_MAX_MS = 60_000
const HEARTBEAT_MS = 20_000
const STORAGE_CHECK_MS = 60_000
const LOW_STORAGE_MB = 100

const MIME_CANDIDATES = [
	'audio/webm;codecs=opus',
	'audio/webm',
	'audio/ogg;codecs=opus',
	'audio/mp4',
]

export function pickMimeType(): string | null {
	for (const candidate of MIME_CANDIDATES) {
		if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(candidate)) {
			return candidate
		}
	}
	return null
}

export interface EngineState {
	phase: 'idle' | 'recording' | 'finishing' | 'syncing' | 'done' | 'failed'
	recordingId: string
	startedAt: number
	localChunks: number
	ackedChunks: number
	storageError: boolean
	lowStorage: boolean
	uploadOnline: boolean
	uploadFailure: '' | 'network' | 'server'
	retryInMs: number
	serverState: string
	error: string
	errorKind: '' | 'gone' | 'transient'
}

function isGoneError(error: unknown): boolean {
	return error instanceof ApiError && [401, 403, 404, 410].includes(error.status)
}

export class CaptureEngine {
	state: EngineState = reactive({
		phase: 'idle',
		recordingId: '',
		startedAt: 0,
		localChunks: 0,
		ackedChunks: 0,
		storageError: false,
		lowStorage: false,
		uploadOnline: true,
		uploadFailure: '',
		retryInMs: 0,
		serverState: '',
		error: '',
		errorKind: '',
	})

	mediaStream: MediaStream | null = null
	private mediaRecorder: MediaRecorder | null = null
	private seq = 0
	private chunkPipeline: Promise<void> = Promise.resolve()
	private uploaderActive = false
	private stopRequested = false
	private wakeUploader: (() => void) | null = null
	private timers: number[] = []
	private onlineHandler = () => {
		this.state.uploadOnline = true
		this.retryNow()
	}

	async start(roundId: string): Promise<void> {
		const mimeType = pickMimeType()
		if (!mimeType) throw new Error('This browser cannot record audio.')
		this.mediaStream = await navigator.mediaDevices.getUserMedia({
			audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
		})
		const started = await api.captureStart(roundId, mimeType)
		this.state.recordingId = started.recording_id
		this.state.serverState = started.state
		this.state.phase = 'recording'
		this.state.startedAt = Date.now()
		await idb.putRecording({
			recordingId: started.recording_id,
			roundId,
			roomId: '',
			mimeType,
			startedAt: Date.now(),
			finishedAt: null,
			totalChunks: null,
			serverComplete: false,
		})
		this.mediaRecorder = new MediaRecorder(this.mediaStream, { mimeType })
		this.mediaRecorder.ondataavailable = (event) => {
			if (event.data && event.data.size > 0) this.enqueueChunk(event.data)
		}
		this.mediaRecorder.start(CHUNK_INTERVAL_MS)
		window.addEventListener('online', this.onlineHandler)
		this.startMonitors()
		void this.runUploader()
	}

	/** Resume an unsynchronised recording found in IndexedDB after a reload. */
	async resumeSync(recording: StoredRecording): Promise<void> {
		const meta = { ...recording }
		this.state.recordingId = meta.recordingId
		const chunks = await idb.chunksFor(meta.recordingId)
		this.seq = chunks.reduce((max, c) => Math.max(max, c.seq + 1), 0)
		this.state.localChunks = chunks.length
		this.state.ackedChunks = chunks.filter((c) => c.acked).length
		this.state.phase = 'syncing'
		if (meta.totalChunks === null) {
			meta.totalChunks = this.seq
			meta.finishedAt = meta.finishedAt ?? Date.now()
			await idb.putRecording(meta)
		}
		window.addEventListener('online', this.onlineHandler)
		this.startMonitors()
		void this.runUploader()
	}

	private enqueueChunk(blob: Blob): void {
		const seq = this.seq
		this.seq += 1
		this.chunkPipeline = this.chunkPipeline
			.then(async () => {
				const buffer = await blob.arrayBuffer()
				const sha256 = await sha256Hex(buffer)
				await idb.putChunk({
					key: `${this.state.recordingId}:${seq}`,
					recordingId: this.state.recordingId,
					seq,
					blob,
					sha256,
					sizeBytes: blob.size,
					createdAt: Date.now(),
					acked: false,
					attempts: 0,
				})
				this.state.localChunks += 1
				this.kickUploader()
			})
			.catch(() => {
				// the most serious condition there is: we cannot keep the audio
				this.state.storageError = true
			})
	}

	private kickUploader(): void {
		if (this.wakeUploader) this.wakeUploader()
	}

	retryNow(): void {
		this.state.retryInMs = 0
		this.kickUploader()
	}

	private idleWait(ms: number): Promise<void> {
		return new Promise((resolve) => {
			const timer = window.setTimeout(() => {
				this.wakeUploader = null
				resolve()
			}, ms)
			this.wakeUploader = () => {
				window.clearTimeout(timer)
				this.wakeUploader = null
				resolve()
			}
		})
	}

	private async runUploader(): Promise<void> {
		if (this.uploaderActive) return
		this.uploaderActive = true
		let retryDelay = RETRY_BASE_MS
		try {
			for (;;) {
				const pending = (await idb.chunksFor(this.state.recordingId)).filter((c) => !c.acked)
				if (pending.length === 0) {
					const recording = (await idb.getRecordings()).find(
						(r) => r.recordingId === this.state.recordingId,
					)
					if (recording && recording.totalChunks !== null) break
					if (this.state.phase !== 'recording') break
					await this.idleWait(1000)
					continue
				}
				const chunk = pending[0]
				try {
					await uploadChunk(this.state.recordingId, chunk.seq, chunk.blob, chunk.sha256)
					chunk.acked = true
					chunk.attempts += 1
					await idb.putChunk(chunk)
					this.state.ackedChunks += 1
					this.state.uploadOnline = true
					this.state.uploadFailure = ''
					this.state.retryInMs = 0
					retryDelay = RETRY_BASE_MS
				} catch (error) {
					if (this.state.phase === 'syncing' && isGoneError(error)) {
						this.state.phase = 'failed'
						this.state.errorKind = 'gone'
						this.state.error =
							error instanceof Error ? error.message : 'The server rejected this recording.'
						this.stopMonitors()
						return
					}
					this.state.uploadOnline = false
					this.state.uploadFailure =
						error instanceof ApiError && error.status >= 500 ? 'server' : 'network'
					chunk.attempts += 1
					await idb.putChunk(chunk)
					this.state.retryInMs = retryDelay
					await this.idleWait(retryDelay)
					retryDelay = Math.min(retryDelay * 2, RETRY_MAX_MS)
				}
			}
			await this.sendComplete()
		} finally {
			this.uploaderActive = false
		}
	}

	async finish(): Promise<void> {
		this.stopRequested = true
		if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
			this.state.phase = 'finishing'
			await new Promise<void>((resolve) => {
				this.mediaRecorder!.onstop = () => resolve()
				this.mediaRecorder!.stop()
			})
		}
		this.mediaStream?.getTracks().forEach((track) => track.stop())
		// the final dataavailable must be persisted before we declare a total
		await this.chunkPipeline
		const total = this.seq
		this.state.phase = 'syncing'
		const recording = (await idb.getRecordings()).find(
			(r) => r.recordingId === this.state.recordingId,
		)
		if (recording) {
			recording.finishedAt = Date.now()
			recording.totalChunks = total
			await idb.putRecording(recording)
		}
		this.kickUploader()
		if (!this.uploaderActive) void this.runUploader()
	}

	private async sendComplete(): Promise<void> {
		const deadline = Date.now() + 5 * 60 * 1000
		let delay = RETRY_BASE_MS
		try {
			while (Date.now() < deadline) {
				const recording = (await idb.getRecordings()).find(
					(r) => r.recordingId === this.state.recordingId,
				)
				const total = recording?.totalChunks ?? this.seq
				try {
					const result = await api.captureComplete(this.state.recordingId, total)
					this.state.serverState = result.state
					if (result.missing_sequences.length === 0) {
						if (recording) {
							recording.serverComplete = true
							await idb.putRecording(recording)
						}
						this.state.phase = 'done'
						return
					}
					// re-send exactly what the server says it is missing
					const stored = await idb.chunksFor(this.state.recordingId)
					const bySeq = new Map<number, StoredChunk>(stored.map((c) => [c.seq, c]))
					for (const seq of result.missing_sequences) {
						const chunk = bySeq.get(seq)
						if (!chunk) throw new Error(`Chunk ${seq} is missing locally too.`)
						await uploadChunk(this.state.recordingId, seq, chunk.blob, chunk.sha256)
						chunk.acked = true
						await idb.putChunk(chunk)
					}
				} catch (error) {
					if (isGoneError(error)) {
						this.state.phase = 'failed'
						this.state.errorKind = 'gone'
						this.state.error = error instanceof Error ? error.message : 'Rejected'
						return
					}
					await this.idleWait(delay)
					delay = Math.min(delay * 2, RETRY_MAX_MS)
				}
			}
			this.state.phase = 'failed'
			this.state.errorKind = 'transient'
			this.state.error = 'The upload did not finish. Your audio is still stored on this device.'
		} finally {
			this.stopMonitors()
		}
	}

	private startMonitors(): void {
		void this.sendHeartbeat()
		this.timers.push(window.setInterval(() => void this.sendHeartbeat(), HEARTBEAT_MS))
		this.timers.push(window.setInterval(() => void this.checkStorage(), STORAGE_CHECK_MS))
	}

	private stopMonitors(): void {
		this.timers.forEach((timer) => window.clearInterval(timer))
		this.timers = []
		window.removeEventListener('online', this.onlineHandler)
	}

	private async sendHeartbeat(): Promise<void> {
		try {
			let freeMb: number | undefined
			if (navigator.storage?.estimate) {
				const estimate = await navigator.storage.estimate()
				if (estimate.quota && estimate.usage !== undefined) {
					freeMb = Math.round((estimate.quota - estimate.usage) / (1024 * 1024))
				}
			}
			await api.captureHeartbeat({
				recording_id: this.state.recordingId || undefined,
				recording_active: this.state.phase === 'recording',
				local_chunks: this.state.localChunks,
				acked_chunks: this.state.ackedChunks,
				storage_ok: !this.state.storageError,
				storage_free_mb: freeMb,
			})
		} catch {
			/* a missed heartbeat must never disturb the recording */
		}
	}

	private async checkStorage(): Promise<void> {
		try {
			if (!navigator.storage?.estimate) return
			const estimate = await navigator.storage.estimate()
			if (estimate.quota && estimate.usage !== undefined) {
				const freeMb = (estimate.quota - estimate.usage) / (1024 * 1024)
				this.state.lowStorage = freeMb < LOW_STORAGE_MB
			}
		} catch {
			/* ignore */
		}
	}

	get stopped(): boolean {
		return this.stopRequested
	}
}

/** Recordings still on this device that the server has not confirmed. */
export async function unsyncedRecordings(): Promise<StoredRecording[]> {
	const recordings = await idb.unfinishedRecordings()
	const out: StoredRecording[] = []
	for (const recording of recordings) {
		const chunks = await idb.chunksFor(recording.recordingId)
		if (chunks.some((c) => !c.acked)) out.push(recording)
	}
	return out
}

export async function clearSynchronized(): Promise<number> {
	let removed = 0
	for (const recording of await idb.getRecordings()) {
		if (recording.serverComplete) {
			await idb.deleteChunksFor(recording.recordingId)
			await idb.deleteRecording(recording.recordingId)
			removed += 1
		}
	}
	return removed
}
