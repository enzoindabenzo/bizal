# BizAL — convenience targets.
#
# `lock` / `lock-check` added as part of the requirements.txt audit fix:
# requirements.txt is a generated lockfile (full transitive pin closure),
# requirements.in is the hand-edited source of direct dependencies. Never
# edit requirements.txt by hand — run `make lock` after changing
# requirements.in, and commit the regenerated requirements.txt alongside it.

.PHONY: lock lock-check

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
# requirements.txt. Compiles into a temp file and diffs against the
# committed lockfile rather than overwriting it in place.
lock-check:
	cd backend && pip install -q pip-tools && \
	pip-compile requirements.in --output-file /tmp/requirements.lock.check --strip-extras && \
	diff -u requirements.txt /tmp/requirements.lock.check && \
	echo "OK: requirements.txt is in sync with requirements.in"
