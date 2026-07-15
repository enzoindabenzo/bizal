# BizAL — convenience targets.
#
# `lock` / `lock-check` added as part of the requirements.txt audit fix:
# requirements.txt is a generated lockfile (full transitive pin closure),
# requirements.in is the hand-edited source of direct dependencies. Never
# edit requirements.txt by hand — run `make lock` after changing
# requirements.in, and commit the regenerated requirements.txt alongside it.

.PHONY: lock lock-check

lock:
	cd backend && pip install -q pip-tools && \
	pip-compile requirements.in --output-file requirements.txt --strip-extras

lock-check:
	cd backend && pip install -q pip-tools && \
	pip-compile requirements.in --output-file /tmp/requirements.lock.check --strip-extras && \
	diff -u requirements.txt /tmp/requirements.lock.check && \
	echo "OK: requirements.txt is in sync with requirements.in"
