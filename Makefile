# BizAL — convenience targets.
#
# `lock` / `lock-check` added as part of the requirements.txt audit fix:
# requirements.txt is a generated lockfile (full transitive pin closure),
# requirements.in is the hand-edited source of direct dependencies. Never
# edit requirements.txt by hand — run `make lock` after changing
# requirements.in, and commit the regenerated requirements.txt alongside it.

.PHONY: lock lock-check loadtest

# Regenerate backend/requirements.txt from backend/requirements.in.
# Requires network access to PyPI (this target cannot run in a
# network-isolated sandbox — see backend/requirements.txt header).
# requirements-dev.txt needs no separate lock step: it layers on top of
# requirements.txt via `-r requirements.txt` and pins only its own
# additional direct packages (coverage/flower/pytest), so it is already
# fully pinned by hand without a transitive closure of its own.
lock:
	cd backend && pip install -q pip-tools && \
	pip-compile requirements.in --output-file requirements.txt --strip-extras

# CI target: fail the build if requirements.in changed without regenerating
# requirements.txt. Compiles into a scratch copy and diffs against the
# committed lockfile rather than overwriting it in place.
#
# The scratch copy is compiled with --output-file requirements.txt (same
# basename as the committed file, just in a different directory) rather
# than an arbitrary /tmp path. pip-compile embeds the literal --output-file
# value it was given into the generated header comment, so comparing against
# a differently-named output file would make line 5 of the diff fail
# unconditionally, every time, independent of whether the actual dependency
# pins are in sync.
lock-check:
	rm -rf /tmp/lock-check && mkdir -p /tmp/lock-check && \
	cp backend/requirements.in /tmp/lock-check/requirements.in && \
	pip install -q pip-tools && \
	cd /tmp/lock-check && pip-compile requirements.in --output-file requirements.txt --strip-extras && cd - >/dev/null && \
	diff -u backend/requirements.txt /tmp/lock-check/requirements.txt && \
	echo "OK: requirements.txt is in sync with requirements.in"

# Headless load test against a locally-running server (see backend/loadtest/
# README.md for the full explanation and how to interpret results). Assumes
# `python manage.py runserver` is already up on :8000 and the DB is seeded
# (`python backend/seed.py`) — this target does not start the server itself
# so it can equally be pointed at a docker-compose or staging host by
# overriding HOST, e.g. `make loadtest HOST=https://staging.bizal.al`.
HOST ?= http://localhost:8000
USERS ?= 50
SPAWN_RATE ?= 10
RUN_TIME ?= 60s

loadtest:
	cd backend && locust -f loadtest/locustfile.py --host=$(HOST) \
	--headless -u $(USERS) -r $(SPAWN_RATE) --run-time $(RUN_TIME) \
	--csv=loadtest/results/run_$$(date +%Y%m%d_%H%M%S)