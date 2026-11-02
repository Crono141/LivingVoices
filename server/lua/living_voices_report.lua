-- living_voices_report.lua -- "/lv bad <note>" from the Living Voices add-on, written to the realm's database.
-- (2026-10-31, the producer: a wrong voice-over line noted where it is heard, on the server, not in a file on the PC.)
--
-- The add-on whispers the player THEMSELVES on the addon channel (an add-on-to-server channel any ALE script can read):
--   prefix "LVR", message  <addon version> \t <line> \t <npc> \t <quest title> \t <zone> \t <note> [\t <report key>]
-- and is answered on the same channel with "OK\t<report key>" once the row is written, so the add-on knows which of
-- its saved reports reached the realm and sends the rest again at the next login (2026-10-31: the producer's first
-- report was made before this script was installed).
-- Only that shape is acted on: a self-whisper (a group member cannot file reports in someone else's name), fields cut
-- to the table's widths, at most one report every 2 seconds and 60 an hour per character. Who reported it is taken
-- from the server's own player object. The whisper itself is swallowed (it would only echo back to the sender).
-- Table: server/sql/60_living_voices_report.sql (acore_characters.living_voices_report).

local ADDON_EVENT_ON_MESSAGE = 30
local CHAT_MSG_WHISPER = 7
local PREFIX = "LVR"
local WIDTH = { 16, 64, 64, 128, 64, 255 }          -- addon_version, line, npc, title, zone, note

local recent = {}                                    -- guid -> { last = os.time(), hour = start, n = count }

local function sql_string(s, width)
    s = tostring(s or ""):gsub("[%z\1-\31]", " ")
    if #s > width then                               -- cut to the column, never inside a UTF-8 character
        s = s:sub(1, width)
        local i = #s
        while i > 0 and s:byte(i) >= 0x80 and s:byte(i) < 0xC0 do i = i - 1 end
        if i > 0 and s:byte(i) >= 0xC0 then
            local need = s:byte(i) >= 0xF0 and 4 or s:byte(i) >= 0xE0 and 3 or 2
            if #s - i + 1 < need then s = s:sub(1, i - 1) end
        end
    end
    return "'" .. s:gsub("\\", "\\\\"):gsub("'", "\\'") .. "'"
end

local function allowed(guid)
    local now, r = os.time(), recent[guid]
    if not r or now - r.hour >= 3600 then r = { last = 0, hour = now, n = 0 }; recent[guid] = r end
    if now - r.last < 2 or r.n >= 60 then return false end
    r.last, r.n = now, r.n + 1
    return true
end

local function OnAddonMessage(event, sender, msgType, prefix, msg, target)
    if prefix ~= PREFIX then return end              -- not ours: untouched
    if msgType ~= CHAT_MSG_WHISPER or not sender or not target or target:GetGUIDLow() ~= sender:GetGUIDLow() then
        return false                                 -- ours, but not a self-whisper: dropped, never acted on
    end
    local f, i = {}, 1
    for field in (msg .. "\t"):gmatch("([^\t]*)\t") do f[i] = field; i = i + 1 end
    if not f[2] or f[2] == "" or not f[2]:match("^[%w%-]+$") then return false end   -- a line name: 9676-complete
    if not allowed(sender:GetGUIDLow()) then
        sender:SendBroadcastMessage("|cff88ccffLiving Voices|r: too many reports at once; wait a moment.")
        return false
    end
    CharDBExecute(string.format(
        "INSERT INTO living_voices_report (account, guid, char_name, race, class, gender, addon_version, line, npc, title, zone, note) "
        .. "VALUES (%d, %d, %s, %d, %d, %d, %s, %s, %s, %s, %s, %s)",
        sender:GetAccountId(), sender:GetGUIDLow(), sql_string(sender:GetName(), 12), sender:GetRace(), sender:GetClass(),
        sender:GetGender(), sql_string(f[1], WIDTH[1]), sql_string(f[2], WIDTH[2]), sql_string(f[3], WIDTH[3]),
        sql_string(f[4], WIDTH[4]), sql_string(f[5], WIDTH[5]), sql_string(f[6], WIDTH[6])))
    sender:SendBroadcastMessage("|cff88ccffLiving Voices|r: report on " .. f[2] .. " saved on the realm. Thank you!")
    if f[7] and f[7]:match("^[%w%-%:% ]+$") then sender:SendAddonMessage(PREFIX, "OK\t" .. f[7], CHAT_MSG_WHISPER, sender) end
    return false
end

RegisterServerEvent(ADDON_EVENT_ON_MESSAGE, OnAddonMessage)
