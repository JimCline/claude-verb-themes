# Contributing to claude-verb-themes

Thanks for wanting to make Claude's spinner more fun! 🌀

## Adding a theme pack

Theme packs live in `themes/`, one JSON file per pack:

```json
{
  "name": "western",
  "title": "Western",
  "emoji": "🤠",
  "description": "Wranglin' code at high noon",
  "verbs": ["Wranglin'", "Lassoing", "Tumbleweed-watching"]
}
```

| Field | Rules |
|---|---|
| `name` | kebab-case, unique across `themes/`, matches the filename (`western` → `themes/western.json`) |
| `title` | Human-readable name shown in the wizard |
| `emoji` | One emoji, used in wizard labels and confirmations |
| `description` | One short, punchy line (shown as the option description) |
| `verbs` | 15–25 strings |

### Verb style guide

- **Gerund-led phrases read best**: "Lassoing", "Consulting Gandalf" — the spinner renders them as "Consulting Gandalf…". But short quotes and gags are welcome too: "He's dead, Jim", "Throwing the dwarf (don't tell the elf)". Spaces are fine; no need to hyphenate. Dropped-g forms ("Wranglin'") are great when they fit.
- **Short-ish**: aim for under ~40 characters; the spinner renders in the status line. A couple of long gag verbs per pack are fine, ten are not.
- **Silly beats literal**: the best verbs are jokes fans instantly recognize, not just theme-adjacent activities.
- **Keep it fun and inclusive (SFW)**: nothing mean-spirited, explicit, or targeting real people/groups. Pop-culture references are great; keep them recognizable to fans.
- **No duplicates within a pack** (cross-pack overlap is fine — the plugin de-duplicates on merge).

### Before opening a PR

1. Validate the JSON parses and has all required fields:
   ```bash
   python3 -c "import json; d=json.load(open('themes/YOURPACK.json')); assert all(k in d for k in ('name','title','emoji','description','verbs'))"
   ```
2. Check the `name` doesn't collide with an existing pack.
3. Add your pack to the theme list in `README.md`.
4. In the PR description, include 3–5 sample verbs so reviewers get the flavor without opening the file.

No other registration is needed — the `/verb-themes` wizard discovers packs from `themes/*.json` at runtime.

## Other contributions

- **Wizard/command changes**: the whole flow lives in `commands/verb-themes.md`. It's a prompt, not code — keep instructions explicit and unambiguous, and preserve the settings-file safety steps (surgical edit of only the `spinnerVerbs` key, JSON validation after writing, restore on failure).
- **Bug reports**: open an issue with your Claude Code version (`claude --version`) and, if relevant, your `spinnerVerbs` block from `~/.claude/settings.json`.

## A note on the setting itself

`spinnerVerbs` is currently an undocumented Claude Code setting (verified against v2.1.220): `{ "mode": "append" | "replace", "verbs": [...] }`. If a Claude Code release changes its shape, the fix belongs in `commands/verb-themes.md` — please include the version you observed the change in.
