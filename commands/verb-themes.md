---
description: Pick spinner-verb theme packs (pirate, wizard, cat…) via a wizard and apply them to Claude Code settings
argument-hint: "[theme names… | list | status | random | reset | schedule on|off] [--append | --replace]"
allowed-tools: ["Read", "Write", "Edit", "Bash", "Glob", "AskUserQuestion"]
---

# Spinner Verb Themes

You are the wizard for the **verb-themes** plugin. Your job: let the user pick one or MORE theme packs of spinner verbs, then write the merged result into their Claude Code settings as the `spinnerVerbs` setting.

## Key facts (do not re-derive)

- The setting lives in `~/.claude/settings.json` under the key `spinnerVerbs` with this exact shape:
  `"spinnerVerbs": { "mode": "append" | "replace", "verbs": ["Conjuring", "Plundering", ...] }`
  - `append` = mix the custom verbs in with Claude Code's built-in verbs.
  - `replace` = use only the custom verbs.
- Verbs are one global pool sampled randomly by the spinner; they are NOT tied to specific actions. Theme packs are therefore **cumulative**: merging multiple packs' verb arrays is fully supported and is the point of this plugin.
- Theme packs are JSON files in `${CLAUDE_PLUGIN_ROOT}/themes/*.json`, each with `name`, `title`, `emoji`, `description`, `verbs` (array of strings).
- Plugin state (which themes are active) is remembered in `~/.claude/verb-themes-state.json` as `{ "activeThemes": ["pirate", ...], "mode": "append"|"replace", "updatedAt": "<ISO date>" }`. Settings.json is the source of truth for the verbs themselves; the state file only exists so this command can show what's active.
- **Scheduled rotation is opt-in and off by default.** When the user turns it on, a `rotation` object is added to the same state file and a SessionStart hook starts picking a new pack on a schedule. All of that is handled by `${CLAUDE_PLUGIN_ROOT}/hooks/rotate.py` — see Step 7. Never hand-edit the `rotation` object yourself; the script holds a lock so that several Claude Code sessions can't fight over the setting.
- Claude Code reads `settings.json` once at startup, so a pack written now becomes visible **next session**. Say so whenever you apply verbs; never claim the spinner has already changed.

## Step 1 — Load themes and current state

In one Bash call, gather everything:

```bash
for f in "${CLAUDE_PLUGIN_ROOT}"/themes/*.json; do cat "$f"; echo; done; echo "---STATE---"; cat ~/.claude/verb-themes-state.json 2>/dev/null || echo '{}'
```

Sort themes alphabetically by `title` for display. A theme is "active" if its name is in the state file's `activeThemes`.

## Step 2 — Handle arguments (skip the wizard when args are given)

Arguments: `$ARGUMENTS`

**Mode flags first:** strip `--append` and `--replace` from the arguments before interpreting the rest. If one is present, it sets the mode for this invocation AND is saved to the state file as the new default. If both are present, tell the user to pick one and stop. The flags matter for theme-name, `random`, and wizard invocations; with `list`, `status`, or `reset` they are ignored.

Then interpret what remains:

- **empty** → run the wizard (Step 3). If a mode flag was given, skip the wizard's mode question and use the flag's mode.
- **`list`** → print a table of all themes (emoji, title, description, verb count, ✓ if active). Stop.
- **`status`** → show active themes, mode, total verb count, and 5 sample verbs from the current `spinnerVerbs` in `~/.claude/settings.json`. Also run `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/rotate.py" --status` and, if `enabled` is true, add a line with the interval, the pool (or "all packs"), and when the next rotation is due. Stop.
- **`reset`** → remove the `spinnerVerbs` key from `~/.claude/settings.json` (Step 5, reset variant), **and** turn rotation off with `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/rotate.py" --disable` — otherwise the next session start would silently re-apply a pack. Mention that you switched rotation off too. Stop.
- **`schedule …`** → scheduled rotation. Go to Step 7.
- **`random`** → pick one theme at random, apply it. Mode: flag if given, else saved mode, else `append`. Skip to Step 5.
- **one or more theme names** (e.g. `pirate cat`) → match case-insensitively against theme `name`s; apply exactly those themes. Mode: flag if given, else saved mode, else `append`. Unknown names: say so and show valid names. Skip to Step 5.

## Step 3 — The wizard (paged multi-select)

Present themes with AskUserQuestion, **3 themes per page**, using the 4th option slot as the pager. Rules:

- `multiSelect: true`, header `"Verb themes"`.
- Each theme option: label `"<emoji> <Title>"` (append `" ✓"` if currently active), description = the theme's description plus verb count, e.g. `"Plunderin' the seven seas… (20 verbs)"`.
- On every page except the last, include a 4th option: label `"➡️ More themes"`, description `"Show the next page (page N of M — selections so far are kept)"`.
- Question text page 1: `"Which spinner verb theme packs do you want? Pick as many as you like — they stack!"`. Later pages: `"More theme packs — keep picking, or finish without selecting the pager."`
- **Pagination protocol:** accumulate selected themes across pages. If the user's selections include "➡️ More themes", show the next page and continue. If they don't, paging ends and the accumulated set is final.
- If the user ends with zero themes selected, ask nothing further; tell them nothing changed (mention `/verb-themes reset` if they wanted to clear).

Then, unless a `--append`/`--replace` flag already decided it, ask ONE more single-select question (header `"Mode"`), question `"How should your themed verbs combine with Claude Code's built-in verbs?"`:
1. `"Mix with defaults (Recommended)"` — description: `"append — your themed verbs join Claude's built-in ones"`
2. `"Themed verbs only"` — description: `"replace — the spinner uses only your selected packs"`

## Step 4 — Merge

Concatenate the `verbs` arrays of all selected themes, de-duplicate case-insensitively while preserving first-seen casing and order.

## Step 5 — Write settings (carefully)

Target file: `~/.claude/settings.json` (user scope, applies to all projects).

1. Read the file. If it doesn't exist, you'll create it fresh as `{ "spinnerVerbs": ... }`.
2. Modify **only** the `spinnerVerbs` key — preserve every other key and the existing formatting as closely as possible. Prefer a surgical Edit when the file already has a `spinnerVerbs` key; otherwise add the key. For **reset**, remove the key entirely (and if the file would become `{}`, that's fine — leave `{}`).
3. Set it to: `{ "mode": "<chosen mode>", "verbs": [ ...merged verbs... ] }`.
4. Validate the result parses: `python3 -c "import json;json.load(open('$HOME/.claude/settings.json'))" && echo OK`. If it fails, restore what you had and report the problem instead of leaving a broken settings file.
5. Update `~/.claude/verb-themes-state.json` with `activeThemes`, `mode`, and `updatedAt` (use `date -u +%Y-%m-%dT%H:%M:%SZ`). On reset, write `{ "activeThemes": [], "mode": "append" }`. Preserve any existing `rotation` object untouched.
6. If that state file has `rotation.enabled === true`, run `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/rotate.py" --touch` afterwards. This restarts the schedule clock so a rotation that was already due doesn't overwrite the pick the user just made, and clears any queued announcement. Tell them their pick stands and rotation resumes from now.

## Step 6 — Confirm

Tell the user, briefly and with the theme emojis:
- Which packs are now active, the mode, and the total verb count.
- Show 5 random sample verbs from the merged list so they get a taste (e.g. `Swashbucklin'… Kneading… Synergizing…`).
- Note: `spinnerVerbs` is applied when a session starts — if the spinner doesn't change in the current session, it will in the next one (or after restarting Claude Code).
- Remind them: `/verb-themes reset` restores the defaults, `/verb-themes status` shows what's active.

## Step 7 — Scheduled rotation (`schedule`)

Rotation is **opt-in**. Until the user runs `schedule on`, the hook does nothing at all. Every operation here goes through the helper script — you never edit the `rotation` state yourself:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/rotate.py" --status
```

It prints JSON: `{ "ok", "enabled", "interval", "pool", "mode", "lastRotatedAt", "nextDueAt", "currentPack", "justApplied"? }`. If `ok` is `false`, show the `error` and stop.

Dispatch on what follows `schedule`:

- **`off`** → `--disable`. Confirm rotation is off and note the current pack stays exactly as it is.
- **`now`** → `--rotate-now`. Rotates immediately even if nothing was due.
- **`status`** → `--status`, reported in prose.
- **`on`, or nothing at all** → run the wizard below.

### The schedule wizard

Ask both questions in a single `AskUserQuestion` call:

**Question 1** — header `"Frequency"`, question `"How often should Claude pick a new spinner pack for you?"`
1. `"Every day (Recommended)"` — `"daily — a fresh pack each morning"`
2. `"Every hour"` — `"hourly — a new pack through the day"`
3. `"Every week"` — `"weekly — one pack to live with for a while"`
4. `"Every session"` — `"session — a new pack each time you start Claude Code"`

The user can type their own via "Other" — pass anything of the form `<number><m|h|d|w>` (e.g. `90m`, `6h`, `3d`) straight through. If they type something the script rejects, show the error and re-ask.

**Question 2** — header `"Pack pool"`, question `"Which packs should it choose from?"`
1. `"All packs (Recommended)"` — `"Any of the <N> installed packs"`
2. `"Let me pick a shortlist"` — `"Rotate only between packs you choose"`

If they chose the shortlist, run the **Step 3 paged multi-select** to collect the pack names (skip the mode question — rotation keeps the mode already saved in state). Fewer than two packs selected: say a shortlist needs at least two and re-ask, or offer all packs instead.

Then apply it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/rotate.py" --enable --interval <interval> --pool <comma,separated,names>
```

Omit `--pool` entirely for "all packs". This turns rotation on **and** picks the first pack straight away, so turning it on visibly does something.

### Reporting back

From the returned JSON, tell the user briefly and playfully:

- The pack in `justApplied` — emoji, title, verb count, and its `samples` as a taste.
- How often it will rotate, and the shortlist if they set one.
- That the new pack goes live **next session** (Claude Code caches `settings.json` at startup), and that from then on you'll mention each new pack as it lands.
- `/verb-themes schedule off` stops it; `/verb-themes schedule now` rotates early.

Keep the whole interaction playful — this is a fun feature — but never sacrifice the settings-file safety rules in Step 5.
