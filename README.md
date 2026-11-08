# Kraken Ignore Sync

One ignore list for all your characters in World of Warcraft: Forever.

WoW keeps a separate ignore list on each character. With this addon, when you ignore
someone on one character, your other characters ignore them the next time you log
in on them. Unignoring works the same way.

Current version: **1.0.1**, for the official Forever client (build 1.60.1.70790,
interface 16001).

## How it works

- **Use the game's normal ignore.** Right-click → Ignore, `/ignore Name`, or the
  Friends window. The addon notices the change and adds it to a shared list
  stored account-wide in `KrakenIgnoreSync_DB`.
- **Login.** When a character logs in, the addon waits for the server to send that
  character's ignore list, then ignores anyone on the shared list who's missing and
  unignores anyone you unignored elsewhere. Changes are made one every 0.4 seconds.
  - **Waiting for the real list.** The server often sends the friends list before
    the ignore list, and until the ignore list arrives it reads as empty. Syncing
    then would re-ignore everybody already on it, which 1.0.0 did at every login.
    Sync now waits for the ignore list itself. If a character that had people
    ignored shows an empty list, it keeps waiting, for up to a minute.
  - **Checking each name.** Before ignoring or unignoring anyone, it asks the game
    whether they're already on the list, so nobody is re-sent.
- **Your existing lists.** A character's current ignores are added to the shared
  list the first time it logs in with the addon. Log in on each character once and
  everything is merged.
- **Newest change wins.** If you unignore someone on one character and later ignore
  them again on another, they end up ignored everywhere (and the reverse).
- **The 50-name limit** still applies per character. If the shared list is bigger,
  the most recently ignored names are added first and you get a warning. Slots
  freed later are filled with the remaining names.
- Your own characters are never ignored on themselves.
- A name the server rejects (renamed or deleted characters) is tried once per
  session. `/kis sync` or the next login tries again.

## Commands

- `/kis list` — names ignored on all your characters.
- `/kis status` — shared list size and this character's count.
- `/kis sync` — apply the shared list to this character now.
- `/kis remove Name` — unignore someone on every character.
- `/kis keep Name` — never add this name on the current character (run again to undo).
- `/kis pause` — stop syncing on all characters (run again to resume).

`/ignoresync` works as an alias for `/kis`.

## Limits

- **Only while the addon is on.** Ignore changes made while the addon is off are
  only partly picked up. New ignores are shared at the next login, but an unignore
  made while it was off is undone (the name is re-added from the shared list). Use
  `/kis remove Name` for those.
- **One WoW account.** SavedVariables are stored per WoW account, so characters on
  a second WoW account under the same Battle.net login keep a separate shared list.
- **Battle.net blocks** (BattleTag blocking) are already account-wide and aren't
  touched.

## Installation

Put the folder in `_forever_\Interface\AddOns` so it directly contains
`KrakenIgnoreSync.toc`. Fully restart WoW (`/reload` doesn't pick up new addons)
and enable it at character select.

## Testing

`tests/kis_harness.py` runs the addon against a mock client with
[lupa](https://pypi.org/project/lupa/). It plays several characters logging in one
after another and sharing the account's saved data:

```
python -I tests/kis_harness.py .
```

It covers:

- importing existing lists, and syncing in both directions
- unignore and re-ignore, last change winning
- the empty list the server sends at login not being read as unignores
- rejected names
- the 50-name limit
- `/kis remove`, `keep`, `pause`, `status` and `list`
- cross-realm names, and Forever's "First Surname" unique names

It's a mock, so it still needs checking in the live client.

## License

The [LICENSE](LICENSE) applies: copyright 2026 tf4482, all rights reserved unless
otherwise explicitly stated.
