#!/bin/bash
# Regression tests for hooks/rotate.py.
#
# Everything runs against a throwaway $HOME, so this never touches your real
# ~/.claude. Run it from anywhere:  bash tests/test_rotate.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/hooks/rotate.py"
SANDBOX="$(mktemp -d)"
export HOME="$SANDBOX"
mkdir -p "$HOME/.claude"
STATE="$HOME/.claude/verb-themes-state.json"
SETTINGS="$HOME/.claude/settings.json"

PASS=0
FAIL=0
trap 'rm -rf "$SANDBOX"' EXIT

ok()   { PASS=$((PASS + 1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  FAIL %s\n     expected: %s\n     actual:   %s\n' "$1" "$2" "$3"; }
is()   { [ "$2" = "$3" ] && ok "$1" || bad "$1" "$3" "$2"; }

# Run the hook exactly as Claude Code would; capture what it would emit.
hook_out() { python3 "$SCRIPT" 2>&1; }
# Number of announcements in a hook run (0 or 1).
announced() { hook_out | grep -c additionalContext; }
jq_state() { python3 -c "import json,sys;print(json.load(open('$STATE'))$1)"; }

echo "== silent no-op unless the user turned rotation on"
rm -f "$STATE"
is "no state file          -> no output" "$(hook_out)" ""
printf 'not json at all {{{' > "$STATE"
is "unparseable state file -> no output" "$(hook_out)" ""
echo '{"activeThemes":["pirate"],"mode":"append"}' > "$STATE"
is "no rotation key        -> no output" "$(hook_out)" ""
echo '{"rotation":{"enabled":false,"interval":"daily"}}' > "$STATE"
is "rotation disabled      -> no output" "$(hook_out)" ""
python3 "$SCRIPT" >/dev/null 2>&1
is "hook always exits 0" "$?" "0"

echo "== --enable only rewrites spinnerVerbs"
cat > "$SETTINGS" <<'EOF'
{
    "model": "opus",
    "permissions": {
        "allow": [
            "Bash(ls:*)"
        ]
    }
}
EOF
rm -f "$STATE"
python3 "$SCRIPT" --enable --interval daily > "$SANDBOX/enable.json"
is "reports ok"        "$(python3 -c 'import json;print(json.load(open("'"$SANDBOX"'/enable.json"))["ok"])')" "True"
is "applies a pack"    "$(python3 -c 'import json;print(bool(json.load(open("'"$SANDBOX"'/enable.json"))["justApplied"]["name"]))')" "True"
is "unrelated keys kept" \
   "$(python3 -c 'import json;d=json.load(open("'"$SETTINGS"'"));print(d["model"], sorted(d), d["permissions"]["allow"])')" \
   "opus ['model', 'permissions', 'spinnerVerbs'] ['Bash(ls:*)']"
is "existing 4-space indent kept" \
   "$(python3 -c 'print(open("'"$SETTINGS"'").read().split(chr(10))[1].startswith("    \""))')" "True"

echo "== announce lands in the session where the pack is live, exactly once"
is "first session start announces" "$(announced)" "1"
is "same session again is silent"  "$(announced)" "0"

echo "== schedule is honoured"
python3 "$SCRIPT" --enable --interval session --pool pirate,cat,wizard >/dev/null
is "pool stored"  "$(jq_state '["rotation"]["pool"]')" "['pirate', 'cat', 'wizard']"
announced >/dev/null; announced >/dev/null; announced >/dev/null
is "rotation stayed inside the pool" \
   "$(python3 -c "import json;d=json.load(open('$STATE'));print(d['rotation']['lastPack'] in d['rotation']['pool'])")" "True"
python3 "$SCRIPT" --enable --interval daily >/dev/null
before="$(jq_state '["rotation"]["lastPack"]')"
announced >/dev/null
is "not due -> pack unchanged" "$(jq_state '["rotation"]["lastPack"]')" "$before"

echo "== bad input is rejected before any state is touched"
python3 "$SCRIPT" --enable --interval "every fortnight" > "$SANDBOX/bad.json" 2>&1
is "bad interval exits 1"    "$?" "1"
is "bad interval reports ok=false" "$(python3 -c 'import json;print(json.load(open("'"$SANDBOX"'/bad.json"))["ok"])')" "False"
python3 "$SCRIPT" --enable --interval daily --pool pirate,notareal > "$SANDBOX/bad2.json" 2>&1
is "unknown pack exits 1"    "$?" "1"
is "unchanged interval after rejection" "$(jq_state '["rotation"]["interval"]')" "daily"

echo "== manual overrides cooperate with the schedule"
python3 "$SCRIPT" --enable --interval hourly >/dev/null
pack_before="$(jq_state '["rotation"]["lastPack"]')"
python3 "$SCRIPT" --touch >/dev/null
is "--touch drops the pending announcement" "$(announced)" "0"
is "--touch keeps lastPack so repeats are still avoided" "$(jq_state '["rotation"]["lastPack"]')" "$pack_before"
python3 "$SCRIPT" --disable >/dev/null
is "--disable silences the hook" "$(hook_out)" ""
is "--disable leaves the verbs in place" \
   "$(python3 -c 'import json;print("spinnerVerbs" in json.load(open("'"$SETTINGS"'")))')" "True"

echo "== concurrent session starts compete for exactly one rotation"
python3 "$SCRIPT" --enable --interval daily >/dev/null
python3 - "$STATE" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
d["rotation"]["lastRotatedAt"] = "2020-01-01T00:00:00Z"          # genuinely due
d["rotation"]["lastAnnouncedPack"] = d["rotation"]["lastPack"]   # nothing pending
json.dump(d, open(sys.argv[1], "w"), indent=2)
PY
before="$(jq_state '["rotation"]["lastPack"]')"
for _ in $(seq 12); do python3 "$SCRIPT" >/dev/null 2>&1 & done
wait
after="$(jq_state '["rotation"]["lastPack"]')"
is "12 simultaneous starts rotate once, not 12" \
   "$( [ "$before" != "$after" ] && echo one-rotation || echo none )" "one-rotation"
is "settings.json matches the pack state records" \
   "$(python3 -c "
import json
d = json.load(open('$STATE'))
s = json.load(open('$SETTINGS'))
t = json.load(open('$ROOT/themes/' + d['rotation']['lastPack'] + '.json'))
print(s['spinnerVerbs']['verbs'] == t['verbs'])")" "True"
is "state file still valid JSON"    "$(python3 -c "import json;json.load(open('$STATE'));print('True')")" "True"
is "settings file still valid JSON" "$(python3 -c "import json;json.load(open('$SETTINGS'));print('True')")" "True"
is "lock is released, not leaked"   "$(python3 "$SCRIPT" --status | python3 -c 'import json,sys;print(json.load(sys.stdin)["ok"])')" "True"

echo "== end to end: the exact command string hooks.json runs"
# Same invocation, same env var, and a realistic SessionStart payload on stdin
# that the script never reads -- that must not break the pipe.
python3 "$SCRIPT" --enable --interval session >/dev/null
export CLAUDE_PLUGIN_ROOT="$ROOT"
payload='{"session_id":"abc123","transcript_path":"/tmp/t.jsonl","cwd":"/tmp","hook_event_name":"SessionStart","source":"startup"}'
e2e="$(printf '%s' "$payload" | sh -c 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/rotate.py" 2>/dev/null || true'; echo "rc=$?")"
is "hook command exits 0"          "$(printf '%s' "$e2e" | tail -1)" "rc=0"
is "emits SessionStart hook JSON" \
   "$(printf '%s' "$e2e" | head -1 | python3 -c 'import json,sys;print(json.load(sys.stdin)["hookSpecificOutput"]["hookEventName"])')" \
   "SessionStart"
is "resolves themes via CLAUDE_PLUGIN_ROOT" \
   "$(printf '%s' "$e2e" | head -1 | python3 -c 'import json,sys;print("spinner verb pack" in json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])')" "True"
# A CLAUDE_PLUGIN_ROOT with no themes/ must fall back to the script's own location.
is "bad CLAUDE_PLUGIN_ROOT falls back" \
   "$(CLAUDE_PLUGIN_ROOT=/nonexistent python3 "$SCRIPT" --status | python3 -c 'import json,sys;print(json.load(sys.stdin)["ok"])')" "True"
unset CLAUDE_PLUGIN_ROOT

echo "== works with no settings.json at all"
rm -f "$SETTINGS"
python3 "$SCRIPT" --rotate-now >/dev/null
is "creates settings.json with just spinnerVerbs" \
   "$(python3 -c 'import json;print(sorted(json.load(open("'"$SETTINGS"'"))))')" "['spinnerVerbs']"

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
