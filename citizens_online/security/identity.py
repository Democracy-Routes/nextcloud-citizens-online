# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Current-user identity from AppAPI request headers."""

from typing import Annotated

from fastapi import Depends, HTTPException
from nc_py_api import NextcloudApp
from nc_py_api.ex_app import nc_app


def get_current_user_id(nc: Annotated[NextcloudApp, Depends(nc_app)]) -> str:
    user = nc.user
    if not user:
        raise HTTPException(status_code=401, detail="No authenticated Nextcloud user")
    return user


CurrentUser = Annotated[str, Depends(get_current_user_id)]


def get_current_nc(nc: Annotated[NextcloudApp, Depends(nc_app)]) -> NextcloudApp:
    """The Nextcloud client, already impersonating the browser's user.

    AppAPI seeds the client's identity from the request's authorization header
    and re-stamps it on every outbound call, so `nc.ocs(...)` on this object runs
    with the organizer's own permissions and privacy scoping. That is what a
    directory lookup needs — not `set_user()`, which is service-user
    impersonation and would show every organizer the same results.
    """
    if not nc.user:
        raise HTTPException(status_code=401, detail="No authenticated Nextcloud user")
    return nc


CurrentNc = Annotated[NextcloudApp, Depends(get_current_nc)]
