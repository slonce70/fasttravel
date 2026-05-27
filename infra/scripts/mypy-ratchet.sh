#!/usr/bin/env bash
# Mypy ratchet — audit Sprint #11.
#
# The audit caught: pyproject says `strict = true`, but CI ran mypy
# with `continue-on-error: true` AND `|| true`. So the gate looked
# meaningful but never failed. Worst of both worlds.
#
# Plain "make strict pass everywhere" is a multi-week refactor we
# don't have budget for right now. The ratchet pattern lets us:
#   - keep strict=true (so new code is type-checked properly);
#   - record the CURRENT error count per service in
#     infra/scripts/mypy-baseline.txt;
#   - fail CI if any service's error count exceeds its baseline.
# Result: typing debt monotonically decreases. New code that introduces
# more errors than baseline must fix existing ones or come down again.
#
# Usage in CI:
#   ./infra/scripts/mypy-ratchet.sh api scheduler ingest bot
#
# To regenerate the baseline after a deliberate cleanup:
#   ./infra/scripts/mypy-ratchet.sh --refresh-baseline api
#
# Output format of mypy-baseline.txt (one line per service):
#   api 17
#   bot 9
#   scheduler 42
#   ingest 4
#
# Lines starting with `#` are comments, ignored. Order doesn't matter.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASELINE_FILE="${ROOT}/infra/scripts/mypy-baseline.txt"
REFRESH=false

if [[ "${1:-}" == "--refresh-baseline" ]]; then
    REFRESH=true
    shift
fi

if [[ $# -eq 0 ]]; then
    echo "Usage: $0 [--refresh-baseline] <service> [<service>...]" >&2
    exit 2
fi

# Lookup helper: read baseline for $1 from BASELINE_FILE (default 0).
get_baseline() {
    local svc="$1"
    if [[ ! -f "$BASELINE_FILE" ]]; then
        echo "0"; return
    fi
    awk -v svc="$svc" '$1==svc {print $2; found=1; exit} END{if(!found) print "0"}' \
        "$BASELINE_FILE"
}

# Replace or append `<svc> <count>` in BASELINE_FILE.
set_baseline() {
    local svc="$1" count="$2"
    mkdir -p "$(dirname "$BASELINE_FILE")"
    touch "$BASELINE_FILE"
    if grep -q "^${svc} " "$BASELINE_FILE"; then
        # Portable sed in-place: write to tmp, mv back.
        local tmp; tmp="$(mktemp)"
        awk -v svc="$svc" -v count="$count" \
            '$1==svc {print svc, count; next} {print}' \
            "$BASELINE_FILE" > "$tmp"
        mv "$tmp" "$BASELINE_FILE"
    else
        echo "${svc} ${count}" >> "$BASELINE_FILE"
    fi
}

# Resolve a usable poetry invocation up front so each service iteration
# doesn't silently fall through to "command not found" (the previous
# version masked this with `|| true` and reported 0 errors when really
# poetry wasn't on PATH at all).
POETRY_CMD=()
for cand in poetry "/usr/bin/python3 -m poetry" "python3 -m poetry" "python -m poetry"; do
    if eval "$cand --version" >/dev/null 2>&1; then
        # shellcheck disable=SC2206
        POETRY_CMD=($cand)
        break
    fi
done
if [[ ${#POETRY_CMD[@]} -eq 0 ]]; then
    echo "ERROR: poetry not available via PATH or any python3 candidate" >&2
    echo "       Install with: pipx install poetry==1.8.4 (or pip --user)" >&2
    exit 2
fi
echo "==> using poetry: ${POETRY_CMD[*]}"

exit_code=0
for svc in "$@"; do
    svc_dir="${ROOT}/apps/${svc}"
    if [[ ! -d "$svc_dir" ]]; then
        echo "ERROR: apps/${svc} does not exist" >&2
        exit 2
    fi

    echo "==> mypy ${svc}"
    # mypy returns non-zero when errors are found; we tolerate that here
    # (we WANT the count, not the exit code). The poetry invocation
    # itself MUST succeed — a missing-dependency failure must surface,
    # not get swallowed.
    raw_output="$(cd "$svc_dir" && "${POETRY_CMD[@]}" run mypy src/ 2>&1)" || mypy_rc=$?
    # mypy_rc 0 → no errors, 1 → errors found, other → poetry/mypy crash.
    : "${mypy_rc:=0}"
    if [[ "$mypy_rc" -gt 1 ]]; then
        echo "  ERROR: mypy crashed (exit ${mypy_rc}):"
        printf '%s\n' "$raw_output" | tail -20
        exit_code=1
        continue
    fi
    count="$(printf '%s\n' "$raw_output" | grep -c '^[^[:space:]].*: error:' || true)"
    baseline="$(get_baseline "$svc")"

    if $REFRESH; then
        set_baseline "$svc" "$count"
        echo "  baseline refreshed: ${svc} = ${count}"
        continue
    fi

    if [[ "$count" -gt "$baseline" ]]; then
        echo "  FAIL: ${svc} has ${count} errors (baseline ${baseline})"
        echo "  --- new errors above baseline ---"
        printf '%s\n' "$raw_output" | tail -50
        exit_code=1
    elif [[ "$count" -lt "$baseline" ]]; then
        echo "  OK + improvement: ${svc} has ${count} errors (baseline ${baseline})"
        echo "  Consider re-running with --refresh-baseline to lock the gain."
    else
        echo "  OK: ${svc} matches baseline (${count})"
    fi
done

exit $exit_code
