# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# The targets CI actually runs, so a green `make check` means a green pipeline.
# Python tooling runs inside the image because the runtime image ships no dev
# extras; the frontend runs on the host, where node_modules already lives.

IMAGE       ?= citizens-online-test
CONTAINER   ?= nc_app_citizens_online
PY_PATHS    := citizens_online scripts tests

.PHONY: help image test lint typecheck build bundles check e2e up register unregister

help:
	@grep -E '^[a-z0-9-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

image: ## Build the image with test tooling (espeak-ng for speech fixtures)
	docker build --build-arg WITH_TEST_TOOLS=1 -t $(IMAGE) .

test: ## Run the Python suite
	docker run --rm --user root -v "$(CURDIR)":/app -w /app --entrypoint sh $(IMAGE) \
		-c "pip install -q pytest && python -m pytest -q"

lint: ## Ruff over every Python path CI checks
	docker run --rm --user root -v "$(CURDIR)":/app -w /app --entrypoint sh $(IMAGE) \
		-c "pip install -q ruff && ruff check $(PY_PATHS)"

typecheck: ## vue-tsc over the frontend
	cd frontend && npm run typecheck

build: ## Rebuild the committed js/ and css/ bundles
	cd frontend && npm run build

bundles: build ## Fail if the committed bundles are stale, as CI does
	@git diff --quiet -- js css || { \
		echo "Committed bundles differ from a fresh build; commit the result."; \
		git --no-pager diff --stat -- js css; exit 1; }

check: lint test typecheck bundles ## Everything CI runs

# Deliberately NOT part of `check`: these drive a real browser against a real
# Nextcloud with this ExApp registered, which CI does not have. Local gate only.
e2e: ## Browser tests (needs NEXTCLOUD_URL, CO_TEST_USER, CO_TEST_PASSWORD)
	cd frontend && npm run e2e

# --- local development against a running Nextcloud ------------------------

up: ## Rebuild and restart the dev container
	sh scripts/dev-up.sh

register: ## Register the ExApp with AppAPI
	sh scripts/register.sh

unregister: ## Remove the ExApp registration (leaves the data volume alone)
	sh scripts/unregister.sh
