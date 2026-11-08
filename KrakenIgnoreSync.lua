-- Kraken Ignore Sync: one ignore list shared by every character on your account.
--
-- WoW keeps a separate ignore list per character. This addon keeps an account-wide
-- list in SavedVariables. Each character adds what it ignores to that list, and on
-- login every character ignores whatever is missing. Unignoring someone removes them
-- from all your characters too. The most recent change wins (ignore or unignore).

local ADDON_NAME = ...
local TITLE = "Kraken Ignore Sync"
local MAX_IGNORES = 50
local ADD_INTERVAL = 0.4   -- seconds between list changes, so the server isn't flooded
local READY_CHECK = 5      -- seconds between checks for the server's ignore list at login
local GIVE_UP = 60         -- after this long an empty list is believed

local db, char
local ready = false        -- true once this character's real ignore list has arrived
local loginAt              -- when this login began
local checkPending = false
local listSeen = false     -- an IGNORELIST_UPDATE has arrived since login
local applying = false
local queue = {}
local failedThisSession = {}   -- names already tried this session
local playerKey

local function say(msg)
    DEFAULT_CHAT_FRAME:AddMessage("|cff66ccff" .. TITLE .. "|r: " .. msg)
end

local function safe(fn, ...)
    if type(fn) ~= "function" then return nil end
    local ok, a, b = pcall(fn, ...)
    if ok then return a, b end
end

local function Now()
    return safe(GetServerTime) or time()
end

local function RealmName()
    local realm = safe(GetNormalizedRealmName) or safe(GetRealmName) or ""
    return (realm:gsub("%s", ""))
end

-- Forever's regional unique names: names are "First Surname" with no realm.
local function UniqueNames()
    return safe(RegionalUniqueNamesEnabled) == true
end

local function HasQualifier(name)
    return name:find("[-%s]") ~= nil
end

-- The identity used to match names across characters.
local function Key(name, realm)
    if not UniqueNames() and not HasQualifier(name) and realm and realm ~= "" then
        name = name .. "-" .. realm
    end
    return (name:lower():gsub("[-%s]+", "-"):gsub("^%-+", ""):gsub("%-+$", ""))
end

-- The name to hand to AddIgnore/DelIgnore on the current character.
local function NameForHere(entry)
    if not UniqueNames() and not HasQualifier(entry.name) and entry.realm and entry.realm ~= RealmName() then
        return entry.name .. "-" .. entry.realm
    end
    return entry.name
end

local function CharLabel()
    local name = safe(UnitName, "player") or "?"
    return name .. "-" .. RealmName()
end

local function IsActive(entry)
    return entry and (entry.added or 0) > (entry.removed or -1)
end

---------------------------------------------------------------- reading the list
local function CurrentList()
    local list = {}
    local count = tonumber(safe(C_FriendList and C_FriendList.GetNumIgnores)) or 0
    for i = 1, count do
        local name = safe(C_FriendList.GetIgnoreName, i)
        if type(name) == "string" and name ~= "" and name ~= UNKNOWN then
            list[Key(name, RealmName())] = name
        end
    end
    return list, count
end

---------------------------------------------------------------- changes made on this character
local function Record(key, name, removed)
    local entry = db.entries[key]
    if not entry then
        entry = {}
        db.entries[key] = entry
    end
    local now = Now()
    if removed then
        entry.removed, entry.removedBy = now, CharLabel()
    else
        if not entry.name or not HasQualifier(entry.name) then
            -- keep the most specific spelling we've seen
            entry.name = name
            if HasQualifier(name) then entry.realm = nil else entry.realm = RealmName() end
        end
        entry.added, entry.addedBy = now, CharLabel()
    end
end

-- Compares the list against what this character had last time and records new
-- ignores and unignores in the shared list.
local function Names(list)
    if #list <= 3 then return table.concat(list, ", ") end
    return table.concat(list, ", ", 1, 3) .. (" and %d more"):format(#list - 3)
end

local function Learn(list, detectRemovals)
    local newNames, goneNames = {}, {}
    for key, name in pairs(list) do
        local entry = db.entries[key]
        if not entry then
            Record(key, name, false)
            newNames[#newNames + 1] = name
        elseif not IsActive(entry) and not char.known[key] and char.initialized then
            -- ignored again on this character after another character unignored them
            Record(key, name, false)
            newNames[#newNames + 1] = name
        end
        -- A first-run character with a name another character unignored leaves it
        -- for the sync to remove: the unignore is the newer, deliberate choice.
    end
    if detectRemovals then
        for key in pairs(char.known) do
            if not list[key] and IsActive(db.entries[key]) then
                Record(key, nil, true)
                goneNames[#goneNames + 1] = db.entries[key].name or key
            end
        end
    end
    if #newNames > 0 then
        table.sort(newNames)
        say(("Shared with all your characters: %s now ignored everywhere."):format(Names(newNames)))
    end
    if #goneNames > 0 then
        table.sort(goneNames)
        say(("Unignored on all your characters: %s."):format(Names(goneNames)))
    end
    char.known = {}
    for key in pairs(list) do char.known[key] = true end
    char.initialized = true
end

---------------------------------------------------------------- applying the shared list here
local Pump

local function BuildQueue()
    wipe(queue)
    if db.paused then return end
    local list, count = CurrentList()
    local free = MAX_IGNORES - count
    local skippedFull = 0
    local adds, removes = {}, {}
    for key, entry in pairs(db.entries) do
        if key ~= playerKey and not failedThisSession[key] then
            if IsActive(entry) and not list[key] and not (char.excluded and char.excluded[key]) then
                adds[#adds + 1] = { key = key, entry = entry, add = true, at = entry.added or 0 }
            elseif not IsActive(entry) and list[key] then
                removes[#removes + 1] = { key = key, name = list[key], add = false }
            end
        end
    end
    -- removals first (they free space), then the most recent ignores first
    table.sort(adds, function(a, b) return a.at > b.at end)
    for _, job in ipairs(removes) do queue[#queue + 1] = job; free = free + 1 end
    for _, job in ipairs(adds) do
        if free > 0 then
            queue[#queue + 1] = job
            free = free - 1
        else
            skippedFull = skippedFull + 1
        end
    end
    if skippedFull > 0 then
        say(("Your ignore list is full (%d). %d shared name%s couldn't be added on this character."):format(MAX_IGNORES, skippedFull, skippedFull == 1 and "" or "s"))
    end
end

local added, removed = 0, 0

local function Finish()
    applying = false
    -- Catch any change the player made while we were applying. Our own adds and
    -- removes match the shared list, so they aren't mistaken for the player's.
    Learn((CurrentList()), true)
    if added > 0 or removed > 0 then
        local parts = {}
        if added > 0 then parts[#parts + 1] = ("ignored %d"):format(added) end
        if removed > 0 then parts[#parts + 1] = ("unignored %d"):format(removed) end
        say("Synced from your other characters: " .. table.concat(parts, ", ") .. ".")
    end
    added, removed = 0, 0
end

-- The game's own answer for one name: true, false, or nil when it won't say.
local function IsIgnoredHere(name)
    if not (C_FriendList and C_FriendList.IsIgnored) or type(name) ~= "string" then return nil end
    local ok, value = pcall(C_FriendList.IsIgnored, name)
    if not ok or (type(issecretvalue) == "function" and issecretvalue(value)) then return nil end
    if value == true or value == false then return value end
    return nil
end

Pump = function()
    local job = table.remove(queue, 1)
    if not job then Finish(); return end
    if job.add then
        local name = NameForHere(job.entry)
        -- One try per session; /kis sync or the next login tries again.
        failedThisSession[job.key] = true
        if IsIgnoredHere(name) == true then
            -- Already on this character's list under another spelling: nothing to do.
        else
            local ok = safe(C_FriendList.AddIgnore, name)
            if ok == false then
                say(("Couldn't ignore %s on this character (the name may have changed)."):format(name))
            else
                added = added + 1
            end
        end
    else
        failedThisSession[job.key] = true
        if IsIgnoredHere(job.name) ~= false then
            safe(C_FriendList.DelIgnore, job.name)
            removed = removed + 1
        end
    end
    C_Timer.After(ADD_INTERVAL, Pump)
end

local function Apply()
    if not ready or applying then return end
    BuildQueue()
    if #queue == 0 then return end
    applying = true
    Pump()
end

---------------------------------------------------------------- events
-- Whether the server has sent this character's ignore list yet. It arrives a little
-- after login (often after the friends list), and until then the list reads as empty:
-- syncing then would re-ignore everybody already on it. So: wait for the game's
-- IGNORELIST_UPDATE. An empty list that comes with it is believed only from a
-- character that had nobody ignored; after GIVE_UP seconds, whatever is there is.
local function ListArrived()
    if loginAt ~= nil and GetTime() - loginAt >= GIVE_UP then return true end
    if not listSeen then return false end
    local _, count = CurrentList()
    return count > 0 or not next(char.known)
end

local BecomeReady
local function CheckLater()
    if checkPending or ready then return end
    checkPending = true
    C_Timer.After(READY_CHECK, function() checkPending = false; BecomeReady() end)
end

BecomeReady = function()
    if ready then return end
    if not ListArrived() then CheckLater(); return end
    ready = true
    local list = CurrentList()
    -- At login only additions are learned. Anything missing gets re-added
    -- unless another character unignored it.
    Learn(list, false)
    Apply()
end

local function OnListUpdate()
    if not ready then BecomeReady(); return end
    -- Ignore the list updates our own adds and removes cause while we're applying.
    -- Learn picks those up afterwards without treating them as the user's changes.
    if applying then return end
    Learn((CurrentList()), true)
    Apply()
end

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_LOGIN")
events:RegisterEvent("IGNORELIST_UPDATE")
events:RegisterEvent("FRIENDLIST_UPDATE")
events:SetScript("OnEvent", function(_, event, arg1)
    if event == "ADDON_LOADED" then
        if arg1 ~= ADDON_NAME then return end
        KrakenIgnoreSync_DB = KrakenIgnoreSync_DB or {}
        KrakenIgnoreSync_Char = KrakenIgnoreSync_Char or {}
        db, char = KrakenIgnoreSync_DB, KrakenIgnoreSync_Char
        db.entries = db.entries or {}
        char.known = char.known or {}
        char.excluded = char.excluded or {}
    elseif event == "PLAYER_LOGIN" then
        playerKey = Key(safe(UnitName, "player") or "", RealmName())
        loginAt = GetTime()
        safe(C_FriendList and C_FriendList.ShowFriends)
        CheckLater()
    elseif db and playerKey then
        if event == "IGNORELIST_UPDATE" then
            listSeen = true
            OnListUpdate()
        elseif event == "FRIENDLIST_UPDATE" and not ready then
            BecomeReady()
        end
    end
end)

---------------------------------------------------------------- /kis
local function Find(text)
    local key = Key(text, RealmName())
    if db.entries[key] then return key, db.entries[key] end
    for k, entry in pairs(db.entries) do
        if (entry.name or ""):lower() == text:lower() then return k, entry end
    end
end

local function Sorted(filter)
    local rows = {}
    for key, entry in pairs(db.entries) do
        if filter(entry) then rows[#rows + 1] = entry.name or key end
    end
    table.sort(rows)
    return rows
end

local HELP = {
    "/kis list - names ignored on all your characters",
    "/kis status - counts for this character",
    "/kis sync - apply the shared list to this character now",
    "/kis remove Name - unignore someone on every character",
    "/kis keep Name - don't add this name on this character",
    "/kis pause - stop syncing (again to resume)",
}

SLASH_KRAKENIGNORESYNC1 = "/kis"
SLASH_KRAKENIGNORESYNC2 = "/ignoresync"
SlashCmdList.KRAKENIGNORESYNC = function(msg)
    local cmd, rest = (msg or ""):match("^%s*(%S*)%s*(.-)%s*$")
    cmd = cmd:lower()
    if cmd == "list" then
        local rows = Sorted(IsActive)
        say(("%d name%s ignored on all characters%s"):format(#rows, #rows == 1 and "" or "s", #rows > 0 and ":" or "."))
        for i = 1, #rows, 8 do say(table.concat(rows, ", ", i, math.min(i + 7, #rows))) end
    elseif cmd == "status" then
        local _, count = CurrentList()
        local shared = #Sorted(IsActive)
        say(("Shared list: %d. This character: %d of %d. Syncing: %s."):format(shared, count, MAX_IGNORES, db.paused and "paused" or (ready and "on" or "waiting for the ignore list")))
    elseif cmd == "sync" then
        if not ready then say("Still waiting for the server's ignore list."); return end
        wipe(failedThisSession)
        Learn((CurrentList()), false)
        Apply()
        if not applying then say("Already in sync.") end
    elseif cmd == "remove" and rest ~= "" then
        local key, entry = Find(rest)
        if not key or not IsActive(entry) then say(rest .. " isn't on the shared list."); return end
        Record(key, nil, true)
        say(("%s will be unignored on all your characters."):format(entry.name or rest))
        Apply()
    elseif cmd == "keep" and rest ~= "" then
        local key, entry = Find(rest)
        key = key or Key(rest, RealmName())
        char.excluded[key] = not char.excluded[key] or nil
        say(("%s %s be added on this character."):format(entry and entry.name or rest, char.excluded[key] and "won't" or "will again"))
    elseif cmd == "pause" then
        db.paused = not db.paused
        say(db.paused and "Paused on all characters." or "Resumed.")
        if not db.paused then Apply() end
    else
        for _, line in ipairs(HELP) do say(line) end
    end
end
