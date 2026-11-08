"""Mock-client test for KrakenIgnoreSync (lupa).

Plays several characters logging in one after another on the same account, sharing
KrakenIgnoreSync_DB the way the real client does. Usage:

    python -I tests/kis_harness.py .
"""
import sys, os
from lupa import LuaRuntime

ADDON = sys.argv[1]
SRC = open(os.path.join(ADDON, "KrakenIgnoreSync.lua"), encoding="utf-8").read()

MOCK = r'''
NOW = 0
SERVERTIME = 1000000
function GetTime() return NOW end
function GetServerTime() return SERVERTIME + NOW end
function wipe(t) for k in pairs(t) do t[k] = nil end return t end
UNKNOWN = "Unknown"
CHAT = {}
DEFAULT_CHAT_FRAME = { AddMessage = function(_, m) CHAT[#CHAT+1] = m end }
UNIQUE = false
function RegionalUniqueNamesEnabled() return UNIQUE end
SERVER = {}        -- character -> ignore list (array of names), the "server's" copy
VALID = {}         -- names that exist; AddIgnore of anything else is rejected by the server
CHARS = {}         -- saved per-character variables
KrakenIgnoreSync_DB = nil
CALLS = { add = 0, del = 0, addNames = {} }

function Login(name, realm)
  ME, MYREALM = name, realm
  SERVER[name] = SERVER[name] or {}
  FRAMES, TIMERS, SlashCmdList = {}, {}, {}
  LOADED = false     -- the server's ignore list arrives a moment after login
  KrakenIgnoreSync_Char = CHARS[name]
  CHAT = {}
end
function Logout() CHARS[ME] = KrakenIgnoreSync_Char end

function UnitName(u) if u == "player" then return ME end end
function GetRealmName() return MYREALM end
function GetNormalizedRealmName() return (MYREALM:gsub("%s", "")) end

C_Timer = { After = function(d, fn) TIMERS[#TIMERS+1] = {at=NOW+d, fn=fn} end }
function Advance(to)
  while true do
    table.sort(TIMERS, function(a,b) return a.at < b.at end)
    local n = TIMERS[1]; if not n or n.at > to then break end
    table.remove(TIMERS, 1); NOW = n.at; n.fn()
  end
  NOW = to
end
function CreateFrame()
  local f = { events = {}, scripts = {} }
  function f:RegisterEvent(e) self.events[e] = true end
  function f:SetScript(n, fn) self.scripts[n] = fn end
  FRAMES[#FRAMES+1] = f
  return f
end
function Fire(e, ...) for _, f in ipairs(FRAMES) do if f.events[e] and f.scripts.OnEvent then f.scripts.OnEvent(f, e, ...) end end end

local function list() return LOADED and SERVER[ME] or {} end
local function find(name)
  for i, n in ipairs(SERVER[ME]) do if n:lower() == name:lower() then return i end end
end
C_FriendList = {}
IGNORE_DELAY = nil
NEVER_ARRIVES = false
function C_FriendList.ShowFriends()
  if not IGNORE_DELAY then
    C_Timer.After(2, function() LOADED = true; Fire("FRIENDLIST_UPDATE"); Fire("IGNORELIST_UPDATE") end)
  else
    C_Timer.After(2, function() Fire("FRIENDLIST_UPDATE") end)
    if not NEVER_ARRIVES then C_Timer.After(IGNORE_DELAY, function() LOADED = true; Fire("IGNORELIST_UPDATE") end) end
  end
end
function C_FriendList.IsIgnored(name)
  if not LOADED then return false end
  for _, n in ipairs(SERVER[ME]) do if n:lower():gsub("[%-%s]+", " ") == name:lower():gsub("[%-%s]+", " ") then return true end end
  return false
end
function C_FriendList.GetNumIgnores() return #list() end
function C_FriendList.GetIgnoreName(i) return list()[i] end
-- chat filters and the server's system replies
FILTERS = {}
SHOWN_SYSTEM = {}
function ChatFrame_AddMessageEventFilter(event, fn) FILTERS[#FILTERS+1] = {event=event, fn=fn} end
function System(msg)
  for _, f in ipairs(FILTERS) do
    if f.event == "CHAT_MSG_SYSTEM" and f.fn(nil, "CHAT_MSG_SYSTEM", msg) then return end
  end
  SHOWN_SYSTEM[#SHOWN_SYSTEM+1] = msg
end
function C_FriendList.AddIgnore(name)
  CALLS.add = CALLS.add + 1; CALLS.addNames[#CALLS.addNames+1] = name
  C_Timer.After(0.1, function()
    if not VALID[name:lower()] then System("Player not found.")
    elseif find(name) then System(name .. " is already being ignored.")
    elseif #SERVER[ME] < 50 then
      table.insert(SERVER[ME], name); System(name .. " is now being ignored."); Fire("IGNORELIST_UPDATE")
    end
  end)
  return true
end
function C_FriendList.DelIgnore(name)
  CALLS.del = CALLS.del + 1
  C_Timer.After(0.1, function()
    local i = find(name)
    if i then table.remove(SERVER[ME], i); System(name .. " is no longer being ignored."); Fire("IGNORELIST_UPDATE") end
  end)
  return true
end
-- the player using the game's own ignore/unignore
function UserIgnore(name) table.insert(SERVER[ME], name); Fire("IGNORELIST_UPDATE") end
function UserUnignore(name) local i = assert(find(name), name .. " is not ignored"); table.remove(SERVER[ME], i); Fire("IGNORELIST_UPDATE") end
function Has(name) return find(name) ~= nil end
'''

lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(MOCK)
load = lua.eval("function(s) return assert(load(s, '@KrakenIgnoreSync.lua')) end")(SRC)

def valid(*names):
    for n in names: lua.execute(f'VALID[("{n}"):lower()] = true')

def server(char, *names):
    lua.execute(f'SERVER["{char}"] = {{{", ".join(repr(n).replace(chr(39), chr(34)) for n in names)}}}')

def login(char, realm="Arnold", until=30):
    lua.execute(f'Login("{char}", "{realm}")')
    load("KrakenIgnoreSync", lua.eval("{}"))
    lua.execute(f'Fire("ADDON_LOADED", "KrakenIgnoreSync"); Fire("PLAYER_LOGIN"); Advance(NOW + {until})')

def logout():
    lua.execute('Logout(); NOW = NOW + 100')

def run(code, until=10):
    lua.execute(code); lua.execute(f'Advance(NOW + {until})')

has = lambda n: lua.eval(f'Has("{n}")')
chat = lambda: list(lua.eval("CHAT").values())
count = lambda: lua.eval("#SERVER[ME]")
slash = lambda m: run(f'SlashCmdList.KRAKENIGNORESYNC("{m}")')

results = []
def check(name, cond):
    results.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name)

valid("Troll", "Spammer", "Griefer", "Bob", "Zed", "Zed-Arnold", "Ganker")

# 1. Alice already ignores two people; they go into the shared list.
server("Alice", "Troll", "Spammer")
login("Alice")
check("1 First character's ignores are shared", lua.eval('KrakenIgnoreSync_DB.entries["troll-arnold"] ~= nil and KrakenIgnoreSync_DB.entries["spammer-arnold"] ~= nil'))
check("1 Nothing is added or removed on the character it came from", lua.eval("CALLS.add") == 0 and lua.eval("CALLS.del") == 0 and count() == 2)
check("1 One summary line, not one line per name", sum("Shared with all your characters" in m for m in chat()) == 1)
run('UserIgnore("Bob")')   # Alice ignores Bob, who is also one of the account's characters
logout()

# 2. Bob logs in with his own ignore (Griefer); he gets Troll and Spammer but never himself.
server("Bob", "Griefer")
login("Bob")
check("2 Second character receives the shared ignores", has("Troll") and has("Spammer") and has("Griefer"))
check("2 A character never ignores itself", not has("Bob") and "Bob" not in lua.eval("CALLS.addNames").values())
check("2 Empty list before the server sends it isn't read as unignores", lua.eval('KrakenIgnoreSync_DB.entries["troll-arnold"].removed') is None)
check("2 Reports what it synced", any("Re-applied 2 ignores" in m for m in chat()))
logout()

# 3. Alice gets Bob's Griefer.
login("Alice")
check("3 First character receives the second character's ignore", has("Griefer") and count() == 4)
# 4. Alice unignores Troll with the game's own UI.
run('UserUnignore("Troll")')
check("4 Unignore is recorded for every character", lua.eval('KrakenIgnoreSync_DB.entries["troll-arnold"].removed') is not None)
check("4 Unignore is reported", any("Unignored on all your characters: Troll" in m for m in chat()))
logout()

login("Bob")
check("4 The other character unignores them too", not has("Troll") and has("Spammer"))
# 5. Bob ignores Troll again; that's newer, so Alice re-ignores.
run('UserIgnore("Troll")')
logout()
login("Alice")
check("5 Ignoring again after an unignore spreads back", has("Troll"))
logout()

# 6. A renamed/deleted character: the server rejects it, and it's tried only once.
lua.execute('KrakenIgnoreSync_DB.entries["gone-arnold"] = { name = "Gone", realm = "Arnold", added = 1 }')
before = lua.eval("CALLS.add")
login("Bob")
run('UserIgnore("Ganker")')   # another list update shouldn't retry Gone
gone_tries = sum(1 for n in list(lua.eval("CALLS.addNames").values())[before:] if n == "Gone")
check("6 A name the server rejects is tried once per session", gone_tries == 1)
check("6 A rejected add isn't mistaken for an unignore", lua.eval('KrakenIgnoreSync_DB.entries["gone-arnold"].removed') is None)
logout()

# 7. Full list: Carl has 49 ignores of his own, so only one shared name fits.
own = [f"Own{i}" for i in range(49)]
valid(*own)
server("Carl", *own)
login("Carl")
check("7 Fills up to the 50-name limit and stops", count() == 50)
check("7 Says the list is full", any("ignore list is full" in m for m in chat()))
check("7 Carl's own 49 are shared", lua.eval('KrakenIgnoreSync_DB.entries["own0-arnold"] ~= nil'))
for n in own: slash(f"remove {n}")
check("7 Removing many names unignores them on this character", not any(n.startswith("Own") for n in lua.eval("SERVER.Carl").values()))
check("7 Freed space is filled with shared names that didn't fit before", has("Troll") and has("Spammer"))
logout()

# 8. /kis remove unignores everywhere; /kis keep skips a name on one character.
login("Alice", until=60)
check("7 Removed names are also unignored on other characters", not has("Own0") and not has("Own48"))
slash("remove Spammer")
check("8 /kis remove unignores here", not has("Spammer"))
slash("keep Ganker")
run('UserUnignore("Ganker")')
check("8 Unignoring a kept name still counts as an unignore", lua.eval('KrakenIgnoreSync_DB.entries["ganker-arnold"].removed') is not None)
run('UserIgnore("Ganker")')
logout()
login("Bob")
check("8 /kis remove reaches the other character", not has("Spammer"))
check("8 Ganker ignored again on Alice is ignored on Bob", has("Ganker"))
slash("keep Troll")
check("8 /kis keep confirms", any("won't be added on this character" in m for m in chat()))
run('UserUnignore("Troll")')
lua.execute('KrakenIgnoreSync_DB.entries["troll-arnold"].removed = nil')   # pretend it is still shared
slash("sync")
check("8 A kept name isn't re-added on that character", not has("Troll"))
logout()

# 9. /kis pause stops syncing.
login("Alice")
slash("pause")
logout()
server("Erin")
login("Erin")
check("9 Paused: nothing is added", count() == 0)
slash("pause")
check("9 Resuming syncs", count() > 0)
logout()

# 10. Different realm (no unique names): the realm is added to the name.
lua.execute('KrakenIgnoreSync_DB.paused = nil')
login("Alice")
run('UserIgnore("Zed")')
logout()
server("Dan")
login("Dan", realm="Other Realm")
check("10 A name from another realm is ignored as Name-Realm", "Zed-Arnold" in lua.eval("CALLS.addNames").values() and has("Zed-Arnold"))
check("10 Name-Realm on the list matches the shared entry (no duplicate)", lua.eval('KrakenIgnoreSync_DB.entries["zed-arnold"] ~= nil and KrakenIgnoreSync_DB.entries["zed-arnold-otherrealm"] == nil'))
logout()

# 11. Regional unique names (Forever): "Prime Arnold" style names, no realm.
lua.execute('UNIQUE = true')
valid("Prime Arnold")
server("Fay", "Prime Arnold")
login("Fay")
check("11 'First Surname' keys the same as 'First-Surname'", lua.eval('KrakenIgnoreSync_DB.entries["prime-arnold"] ~= nil'))
logout()
server("Gus")
login("Gus", realm="Other Realm")
check("11 Unique names are sent as-is, without a realm", "Prime Arnold" in lua.eval("CALLS.addNames").values() and has("Prime Arnold"))
slash("status")
check("11 /kis status works", any("Shared list:" in m for m in chat()))
slash("list")
check("11 /kis list works", any("ignored on all characters" in m for m in chat()))
logout()


# 12. The live bug: friends list first, ignore list 12 seconds later. Nobody already
#     ignored is ignored again, and nothing is reported.
lua.execute('UNIQUE = true; KrakenIgnoreSync_DB = nil')
for c in ("Hana", "Ivo"):
    lua.execute(f'CHARS["{c}"] = nil')
valid("Haicrys Corelli", "Artio Stormfeather", "Alex Denton")
server("Hana", "Haicrys Corelli", "Artio Stormfeather", "Alex Denton")
login("Hana")            # first login: list arrives with the friends list (old timing)
logout()
lua.execute('IGNORE_DELAY = 14')
before = lua.eval("CALLS.add")
login("Hana", until=40)
check("12 Ignore list arriving after the friends list: nobody is re-ignored", lua.eval("CALLS.add") == before)
check("12 ...and no 'Synced' message", not any("Re-applied" in m for m in chat()))
check("12 ...and the list is unchanged", count() == 3)
logout()
# Another character, also late, gets the names it lacks and only those.
server("Ivo", "Alex Denton")
before = lua.eval("CALLS.add")
login("Ivo", until=40)
added_now = list(lua.eval("CALLS.addNames").values())[before:]
check("12 A late list still gets what it lacks, and only that", sorted(added_now) == ["Artio Stormfeather", "Haicrys Corelli"] and count() == 3)
logout()
# Already ignored under another spelling: the game says so, nothing is sent
lua.execute('IGNORE_DELAY = nil')
server("Ivo", "Haicrys-Corelli", "Artio Stormfeather", "Alex Denton")
lua.execute('CHARS["Ivo"] = nil')
before = lua.eval("CALLS.add")
login("Ivo", until=40)
check("12 Already on the list under another spelling: not sent again", lua.eval("CALLS.add") == before)
logout()

# 13. The ignore list never arrives: wait a minute, then trust the empty list
lua.execute('IGNORE_DELAY = 14; NEVER_ARRIVES = true')
before = lua.eval("CALLS.add")
login("Hana", until=50)
check("13 No list yet at 50 seconds: still waiting, nothing sent", lua.eval("CALLS.add") == before)
lua.execute('Advance(NOW + 30)')
check("13 After a minute it trusts the empty list and syncs", lua.eval("CALLS.add") > before)
logout()
lua.execute('IGNORE_DELAY = nil; NEVER_ARRIVES = false')

# 14. A brand-new character: syncs as soon as its (empty) list arrives, not before
server("Jun")
before = lua.eval("CALLS.add")
lua.execute('IGNORE_DELAY = 14')
login("Jun", until=12)
check("14 New character: nothing sent before its list arrives", lua.eval("CALLS.add") == before)
lua.execute('Advance(NOW + 6)')
check("14 ...then it syncs without waiting the full minute", lua.eval("CALLS.add") > before)
logout()
lua.execute('IGNORE_DELAY = nil; NEVER_ARRIVES = false')

# 15. Forever since build 70862: the ignore list never comes at login. After the wait
#     the names are re-added, quietly: the server's "now being ignored" lines are hidden
#     and replaced by one summary saying why.
lua.execute('UNIQUE = true; KrakenIgnoreSync_DB = nil')
names = ["Ana Bell", "Cy Dorn", "Eve Fox", "Gil Hart"]
valid(*names)
server("Kai", *names)
lua.execute('CHARS["Kai"] = nil')
login("Kai", until=20)           # first login: list arrives, everything learned
logout()
lua.execute('IGNORE_DELAY = 14; NEVER_ARRIVES = true')
server("Kai")                    # the server dropped them
lua.execute('SHOWN_SYSTEM = {}')
login("Kai", until=90)
shown = list(lua.eval("SHOWN_SYSTEM").values())
check("15 Dropped list: all names re-added", all(has(n) for n in names))
check("15 No 'now being ignored' line per name", not any("now being ignored" in m for m in shown))
check("15 One summary line instead, saying the list was empty at login",
      sum("Re-applied 4 ignores" in m for m in chat()) == 1 and any("empty at login" in m for m in chat()))
logout()
# The server kept them but never sent the list: it answers "already ignored"
lua.execute('SHOWN_SYSTEM = {}')
login("Kai", until=90)
shown = list(lua.eval("SHOWN_SYSTEM").values())
check("15 Kept but unsent: 'already being ignored' lines are hidden too", not any("already being ignored" in m for m in shown))
check("15 ...and the summary says the server already had them", any("server already had 4" in m for m in chat()))
logout()
lua.execute('IGNORE_DELAY = nil; NEVER_ARRIVES = false')
# The player's own /ignore is never hidden
lua.execute('SHOWN_SYSTEM = {}')
login("Kai", until=20)
run('System("Zed is now being ignored.")')
check("15 Messages for names the addon didn't send are left alone", "Zed is now being ignored." in lua.eval("SHOWN_SYSTEM").values())
logout()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
