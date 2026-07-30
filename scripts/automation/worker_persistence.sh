#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
helper="$repo_root/scripts/automation/worker_persistence.py"
config_file="${MEMORY_STARGRAPH_AUTOMATION_CONFIG:-${CODEX_HOME:-$HOME/.codex}/automations/memory-stargraph-wish-to-reallity/deployment-targets.env}"
retries="${MEMORY_STARGRAPH_WORKER_API_RETRIES:-3}"

usage() {
  cat >&2 <<'USAGE'
usage:
  worker_persistence.sh [--config FILE] routes [--json]
  worker_persistence.sh [--config FILE] read SLUG [--json]
  worker_persistence.sh [--config FILE] save SLUG --file FILE [--json]
  worker_persistence.sh [--config FILE] tags SLUG [--add TAG] [--remove TAG] [--json]
USAGE
}

if [[ "${1:-}" == "--config" ]]; then
  config_file="${2:?missing --config value}"
  shift 2
fi

command="${1:-}"
if [[ -z "$command" ]]; then
  usage
  exit 2
fi
shift

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/worker-persistence.XXXXXX")"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"
}

retry_delay() {
  case "$1" in
    1) printf '0.25' ;;
    2) printf '0.5' ;;
    *) printf '1' ;;
  esac
}

curl_with_retry() {
  local output="$1"
  shift
  local attempt=1
  local error_file="$tmp_dir/curl-error"
  : >"$error_file"
  while (( attempt <= retries )); do
    if curl -sS --fail "$@" -o "$output" 2>"$error_file"; then
      return 0
    fi
    if (( attempt == retries )); then
      cat "$error_file" >&2
      return 1
    fi
    sleep "$(retry_delay "$attempt")"
    attempt=$((attempt + 1))
  done
}

selected_kind=""
selected_base=""
selected_flags_shell=""
selected_source=""
had_non_loopback=0

select_route() {
  if [[ -n "$selected_base" ]]; then
    return 0
  fi
  while IFS=$'\t' read -r kind base flags_shell source; do
    [[ -z "$base" ]] && continue
    if [[ "$kind" == "non_loopback" ]]; then
      had_non_loopback=1
    fi
    local flags=()
    if [[ -n "$flags_shell" ]]; then
      eval "flags=($flags_shell)"
    fi
    if curl -sS --fail "${flags[@]}" --max-time 8 "$base/api/health" -o "$tmp_dir/health.json"; then
      selected_kind="$kind"
      selected_base="$base"
      selected_flags_shell="$flags_shell"
      selected_source="$source"
      return 0
    fi
  done < <(python3 "$helper" --config "$config_file" routes --shell)
  if (( had_non_loopback )); then
    echo "configured non-loopback worker API routes were unavailable; refusing loopback fallback" >&2
  else
    echo "no healthy worker API route available" >&2
  fi
  return 1
}

selected_flags() {
  if [[ -n "$selected_flags_shell" ]]; then
    eval "printf '%s\n' $selected_flags_shell"
  fi
}

route_json() {
  python3 - <<PY
import json
print(json.dumps({
  "base_url": "$selected_base",
  "curl_flags": [line for line in """$(selected_flags)""".splitlines() if line],
  "source": "$selected_source",
  "loopback": "$selected_kind" == "loopback",
}, indent=2, sort_keys=True))
PY
}

slug_url() {
  python3 "$helper" encode-slug "$1"
}

read_command() {
  local slug="$1"
  local emit_json="${2:-false}"
  select_route
  local flags=()
  if [[ -n "$selected_flags_shell" ]]; then
    eval "flags=($selected_flags_shell)"
  fi
  local encoded
  encoded="$(slug_url "$slug")"
  curl_with_retry "$tmp_dir/read.json" "${flags[@]}" --max-time 45 "$selected_base/api/entity-raw/$encoded"
  if [[ "$emit_json" == "true" ]]; then
    python3 - <<PY
import json
payload=json.load(open("$tmp_dir/read.json"))
payload["ok"] = True
payload["route_source"] = "$selected_source"
print(json.dumps(payload, indent=2, sort_keys=True))
PY
  else
    python3 "$helper" content-from-raw --raw-json-file "$tmp_dir/read.json"
  fi
}

save_command() {
  local slug="$1"
  local file="$2"
  local emit_json="${3:-false}"
  select_route
  local flags=()
  if [[ -n "$selected_flags_shell" ]]; then
    eval "flags=($selected_flags_shell)"
  fi
  local encoded
  encoded="$(slug_url "$slug")"
  python3 "$helper" save-payload --file "$file" --json >"$tmp_dir/save-payload.json"
  local attempt=1
  while (( attempt <= retries )); do
    if curl -sS --fail "${flags[@]}" --max-time 120 -X POST -H 'Content-Type: application/json' -d @"$tmp_dir/save-payload.json" "$selected_base/api/entity-save/$encoded" -o "$tmp_dir/save-response.json" &&
       curl -sS --fail "${flags[@]}" --max-time 45 "$selected_base/api/entity-raw/$encoded" -o "$tmp_dir/readback.json" &&
       python3 "$helper" verify-save --expected-file "$file" --raw-json-file "$tmp_dir/readback.json" --json >"$tmp_dir/verify-save.json" &&
       python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("ok") is True else 1)' "$tmp_dir/verify-save.json"; then
      if [[ "$emit_json" == "true" ]]; then
        python3 - <<PY
import json
payload=json.load(open("$tmp_dir/verify-save.json"))
payload.update({"ok": True, "slug": "$slug", "route_source": "$selected_source", "attempts": $attempt})
print(json.dumps(payload, indent=2, sort_keys=True))
PY
      else
        printf 'saved %s via %s\n' "$slug" "$selected_source"
      fi
      return 0
    fi
    if (( attempt == retries )); then
      echo "save readback verification failed for $slug" >&2
      return 1
    fi
    sleep "$(retry_delay "$attempt")"
    attempt=$((attempt + 1))
  done
}

tags_command() {
  local slug="$1"
  local emit_json="$2"
  shift 2
  local add_args=()
  local remove_args=()
  while (($#)); do
    case "$1" in
      --add)
        add_args+=("$2")
        shift 2
        ;;
      --remove)
        remove_args+=("$2")
        shift 2
        ;;
      *)
        echo "unknown tags argument: $1" >&2
        exit 2
        ;;
    esac
  done
  select_route
  local flags=()
  if [[ -n "$selected_flags_shell" ]]; then
    eval "flags=($selected_flags_shell)"
  fi
  local encoded
  encoded="$(slug_url "$slug")"
  local payload_args=()
  for tag in "${add_args[@]}"; do payload_args+=(--add "$tag"); done
  for tag in "${remove_args[@]}"; do payload_args+=(--remove "$tag"); done
  python3 "$helper" tag-payload "${payload_args[@]}" --json >"$tmp_dir/tag-payload.json"
  curl_with_retry "$tmp_dir/tag-response.json" "${flags[@]}" --max-time 90 -X POST -H 'Content-Type: application/json' -d @"$tmp_dir/tag-payload.json" "$selected_base/api/entity-tags/$encoded"
  curl_with_retry "$tmp_dir/tag-readback.json" "${flags[@]}" --max-time 45 "$selected_base/api/entity-raw/$encoded"
  local verify_args=()
  for tag in "${add_args[@]}"; do verify_args+=(--add "$tag"); done
  for tag in "${remove_args[@]}"; do verify_args+=(--remove "$tag"); done
  python3 "$helper" verify-tags --raw-json-file "$tmp_dir/tag-readback.json" "${verify_args[@]}" --json >"$tmp_dir/verify-tags.json"
  python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("ok") is True else 1)' "$tmp_dir/verify-tags.json"
  if [[ "$emit_json" == "true" ]]; then
    python3 - <<PY
import json
payload=json.load(open("$tmp_dir/verify-tags.json"))
payload.update({"ok": True, "slug": "$slug", "route_source": "$selected_source"})
print(json.dumps(payload, indent=2, sort_keys=True))
PY
  else
    printf 'tags updated %s via %s\n' "$slug" "$selected_source"
  fi
}

case "$command" in
  routes)
    emit_json=false
    if [[ "${1:-}" == "--json" ]]; then emit_json=true; fi
    select_route
    if [[ "$emit_json" == "true" ]]; then
      route_json
    else
      printf '%s %s [%s]\n' "$selected_base" "$selected_source" "$selected_kind"
    fi
    ;;
  read)
    slug="${1:?missing slug}"
    shift
    emit_json=false
    if [[ "${1:-}" == "--json" ]]; then emit_json=true; fi
    read_command "$slug" "$emit_json"
    ;;
  save)
    slug="${1:?missing slug}"
    shift
    file=""
    emit_json=false
    while (($#)); do
      case "$1" in
        --file) file="${2:?missing --file value}"; shift 2 ;;
        --json) emit_json=true; shift ;;
        *) echo "unknown save argument: $1" >&2; exit 2 ;;
      esac
    done
    [[ -n "$file" ]] || { echo "missing --file" >&2; exit 2; }
    save_command "$slug" "$file" "$emit_json"
    ;;
  tags)
    slug="${1:?missing slug}"
    shift
    emit_json=false
    rest=()
    while (($#)); do
      case "$1" in
        --json) emit_json=true; shift ;;
        *) rest+=("$1"); shift ;;
      esac
    done
    tags_command "$slug" "$emit_json" "${rest[@]}"
    ;;
  *)
    usage
    exit 2
    ;;
esac
