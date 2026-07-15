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
lock:
	cd backend && pip install -q pip-tools && \
	pip-compile requirements.in --output-file requirements.txt --strip-extras

# CI target: fail the build if requirements.in changed without regenerating
# requirements.txt. Deliberately does NOT recompile the full transitive
# closure and diff it — that broke CI on unrelated transitive-package
# releases and platform-conditional deps (e.g. colorama on Windows vs
# Linux). Instead, it only verifies each direct pin from requirements.in
# is present in requirements.txt. See backend/scripts/check_lock.py.
lock-check:
	cd backend && python scripts/check_lock.py
