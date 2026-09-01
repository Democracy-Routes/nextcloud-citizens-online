// SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
// SPDX-License-Identifier: AGPL-3.0-or-later
// The API is young and its shapes still move; components read what they need
// rather than re-declaring every field here.
export type SessionStatus = 'DRAFT' | 'READY' | 'ACTIVE' | 'PROCESSING' | 'REVIEW' | 'COMPLETE'
export type RoundStatus = 'NOT_STARTED' | 'ACTIVE' | 'ENDED' | 'PROCESSING' | 'READY_FOR_REVIEW'
