# 🌀 claude-verb-themes

> 🎩 Hat tip to [@ryanlanciaux](https://x.com/ryanlanciaux) for the inspiration.
>
> 🤖 Built with [Claude Code](https://claude.com/claude-code) — Claude is a co-author on every commit.

Fun, switchable **spinner-verb theme packs** for [Claude Code](https://code.claude.com). Swap the built-in "Pondering… / Reticulating…" spinner verbs for pirate speak, wizard incantations, cat behavior, corporate synergy, and more — picked at runtime through a wizard-style slash command.

## What it looks like

With the 🥥 Monty Python pack active, the working spinner cycles through things like:

```text
✻ Pining for the fjords… (esc to interrupt)

✽ NOBODY expects the Spanish Inquisition… (12s · ↓ 2.1k tokens)

✻ Calculating unladen swallow airspeed… (37s · ↓ 8.4k tokens)

✽ Not dead yet… (1m 3s · ↓ 19.2k tokens)
```

(Example output — your session's timings, token counts, and level of shrubbery may vary.)

## How it works

Claude Code supports a (currently undocumented, verified against v2.1.220) setting in `settings.json`:

```json
"spinnerVerbs": {
  "mode": "append",
  "verbs": ["Conjuring", "Plunderin'", "Kneading"]
}
```

- Verbs are **one global pool** sampled randomly by the spinner — they aren't tied to specific actions.
- That means theme packs are **cumulative**: activate as many as you like and the plugin merges their verbs into one list.
- `mode: "append"` mixes your verbs with Claude's built-ins; `mode: "replace"` uses only yours.

The plugin's `/verb-themes` command presents the packs in a paged, multi-select wizard and writes the merged result to `~/.claude/settings.json`.

## Install

```
/plugin marketplace add JimCline/claude-verb-themes
/plugin install verb-themes@claude-verb-themes
```

(Working from a local clone? `/plugin marketplace add /path/to/claude-verb-themes` works too.)

## Usage

| Command | What it does |
|---|---|
| `/verb-themes` | Wizard: pick packs (multi-select, paged), then append/replace mode |
| `/verb-themes pirate cat` | Apply specific packs directly, no wizard |
| `/verb-themes pirate cat --replace` | Same, but use ONLY themed verbs (no built-ins) |
| `/verb-themes bsg --append` | Apply BSG mixed in with Claude's default verbs |
| `/verb-themes random` | Surprise me |
| `/verb-themes list` | Show all packs and which are active |
| `/verb-themes status` | Show current spinnerVerbs config |
| `/verb-themes reset` | Remove the override, back to stock verbs |
| `/verb-themes schedule on` | Wizard: rotate to a new random pack on a schedule |
| `/verb-themes schedule off` | Stop rotating (keeps the pack you're on) |
| `/verb-themes schedule now` | Rotate early, right now |

`--append` (mix with Claude's built-in verbs) and `--replace` (themed verbs only) work with any applying form, including the wizard — where a flag skips the mode question. The chosen mode is remembered as the default for next time; without a flag or saved preference, `append` is used.

Changes apply to new sessions — restart Claude Code if the spinner doesn't change immediately.

## Scheduled rotation

Don't want to choose? Let it surprise you:

```
/verb-themes schedule on
```

A short wizard asks how often (daily, hourly, weekly, every session, or anything like `6h` / `3d`) and whether to draw from all packs or a shortlist you pick. From then on, a new random pack turns up on that schedule and Claude tells you when it does:

```text
🎲 New pack today: 🥥 Monty Python — expect shrubbery.
```

**This is entirely opt-in.** Install the plugin and nothing rotates; the hook checks one file, sees rotation was never enabled, and exits. Turn it off any time with `/verb-themes schedule off`, which leaves you on whatever pack you're currently wearing.

A few things worth knowing:

- **A new pack goes live in your *next* session.** Claude Code reads `settings.json` once at startup, so the pack chosen at the start of one session is the one you see in the following one. The announcement is deliberately delayed to match, so in normal use you're told about a pack in the session where it's actually spinning rather than the one where it was picked.
- **"Daily" means "at most once a day, checked when a session starts"** — it's a staleness check, not a cron job. Nothing runs while Claude Code is closed, so if you don't open it for three days you get one new pack, not three.
- **Concurrent sessions won't fight over it.** Rotation takes an exclusive `flock` and re-reads `settings.json` inside it, so twelve sessions starting at once produce exactly one rotation. Only the `spinnerVerbs` key is rewritten; your other settings and the file's indentation are left alone.
- **Picking packs by hand wins.** Running `/verb-themes pirate` while rotation is on restarts the schedule clock instead of letting a due rotation overwrite your choice. `/verb-themes reset` turns rotation off as well.

The rotation itself lives in [`hooks/rotate.py`](hooks/rotate.py), wired up as a `SessionStart` hook. Its tests:

```
bash tests/test_rotate.sh
```

(They run against a throwaway `$HOME` and never touch your real `~/.claude`.)

## Theme packs

**Classics:** 🏴‍☠️ Pirate · 🧙 Wizard · 🚀 Space · 🐱 Cat · 👨‍🍳 Chef · 💼 Corporate · 💾 90s Hacker Movie · 🕵️ Detective Noir · 💪 Gym Bro · 🐉 Dungeon Crawler · 🌊 Ocean · ☕ Cozy Café

**Pop culture:** 🤖 Battlestar Galactica (2003) · 💍 Lord of the Rings · 🌌 Star Wars · 🎄 Die Hard · 🖖 Star Trek (all series) · ⭐ TOS · 🫖 TNG · 🪐 DS9 · ☄️ Voyager · 🎖️ Military Speak · 🥥 Monty Python

## Adding your own pack (local)

Drop a JSON file in `themes/`:

```json
{
  "name": "my-pack",
  "title": "My Pack",
  "emoji": "✨",
  "description": "Short blurb shown in the wizard",
  "verbs": ["Sparkling", "Glittering", "Dazzling"]
}
```

Verbs render in the status line as "Sparkling…" — gerund-led phrases read best ("Consulting Gandalf"), but short quotes and gags work too ("He's dead, Jim"). Keep them under ~40 characters and SFW. The wizard picks the pack up automatically — no other registration needed.

## Contributing

New theme packs are the easiest (and most fun) way to contribute:

1. **Fork** this repo and create a branch (`git checkout -b theme/western`).
2. **Add** your pack as `themes/<name>.json` using the schema above.
3. **Validate** it: `python3 -c "import json; json.load(open('themes/<name>.json'))"`.
4. **Open a PR** with a couple of sample verbs in the description.

See [CONTRIBUTING.md](CONTRIBUTING.md) for pack guidelines (naming, verb style, what gets merged). Bug reports and improvements to the `/verb-themes` wizard are welcome via issues and PRs too.

## State

The plugin remembers active packs in `~/.claude/verb-themes-state.json` (display only); `~/.claude/settings.json` is the source of truth for the verbs.

If you enable rotation, that same state file grows a `rotation` object recording the interval, the shortlist, when it last rotated, and which pack has already been announced. Deleting the file is safe — it just turns rotation off and forgets which packs were active.
