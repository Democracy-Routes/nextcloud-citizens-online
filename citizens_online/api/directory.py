# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Looking people up in Nextcloud.

A plain USER route — it must not sit under `/admin/`, which would lock out every
organizer who is not an administrator, nor under `/integrations/`, which AppAPI
serves without a session. The results are whatever the calling organizer is
allowed to see; see `services/directory.py`.
"""

from fastapi import APIRouter, Query

from citizens_online.security.identity import CurrentNc
from citizens_online.services import directory as directory_svc

router = APIRouter(prefix="/directory", tags=["directory"])


@router.get("/search")
def search(nc: CurrentNc, q: str = Query(default="", max_length=64), limit: int = Query(15, le=50)):
    return {"results": directory_svc.search(nc, q, limit=limit)}
