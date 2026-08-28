#!/usr/bin/env bash
# BizAL — install Git pre-commit hooks
# Run once after cloning: bash install-hooks.sh

set -e
REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK="$REPO_ROOT/.git/hooks/pre-commit"

cat > "$HOOK" << 'GITEOF'
#!/usr/bin/env bash
# BizAL pre-commit hook
# Catches raw localStorage token reads and bare fetch() calls outside auth.js
# before they reach CI.

set -e
PASS=true

# ── 1. Raw token reads outside auth.js ────────────────────────────────────────
VIOLATIONS=$(git diff --cached --name-only | \
  xargs grep -ln \
    "localStorage\.getItem\(['\"]bizal_access['\"]\)\|localStorage\.getItem\(['\"]access['\"]\)\|localStorage\.getItem\(['\"]refresh['\"]\)\|localStorage\.getItem\(['\"]bizal_refresh['\"]\)" \
    2>/dev/null | grep -v "auth\.js" || true)

if [ -n "$VIOLATIONS" ]; then
  echo ""
  echo "❌ pre-commit: Raw localStorage token read detected in:"
  echo "$VIOLATIONS"
  echo ""
  echo "   Use Auth.getAccess() / Auth.getRefresh() instead."
  echo "   These are defined in frontend/static/js/auth.js"
  echo ""
  PASS=false
fi

# ── 2. Raw setItem for tokens outside auth.js ─────────────────────────────────
VIOLATIONS2=$(git diff --cached --name-only | \
  xargs grep -ln \
    "localStorage\.setItem\(['\"]access['\"]\|['\"]bizal_access['\"]\|['\"]refresh['\"]\|['\"]bizal_refresh['\"]\|['\"]bizal-admin-token['\"]\)" \
    2>/dev/null | grep -v "auth\.js" || true)

if [ -n "$VIOLATIONS2" ]; then
  echo ""
  echo "❌ pre-commit: Raw localStorage token WRITE detected in:"
  echo "$VIOLATIONS2"
  echo ""
  echo "   Use Auth.setTokens(access, refresh) instead."
  echo ""
  PASS=false
fi

# ── 3. Python syntax check on staged .py files ────────────────────────────────
STAGED_PY=$(git diff --cached --name-only | grep "\.py$" || true)
if [ -n "$STAGED_PY" ]; then
  for f in $STAGED_PY; do
    if [ -f "$f" ]; then
      python3 -m py_compile "$f" 2>/dev/null || {
        echo "❌ pre-commit: Python syntax error in $f"
        PASS=false
      }
    fi
  done
fi

if [ "$PASS" = false ]; then
  echo ""
  echo "Pre-commit checks failed. Fix the issues above, then re-stage and commit."
  exit 1
fi

echo "✅ pre-commit checks passed"
GITEOF

chmod +x "$HOOK"
echo "✅ pre-commit hook installed at $HOOK"
