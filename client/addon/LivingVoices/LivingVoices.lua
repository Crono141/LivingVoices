-- Living Voices: plays the realm's quest voice-over through LivingVoices.dll, which can stop a line at
-- once -- the stock 3.3.5a client cannot. Offer / progress / turn-in play when the quest window shows that text, and
-- stop when the window closes. Clips: vo\<quest>-<accept|progress|complete>[-m|-f].mp3 (Index.lua lists them).
-- (1.0.0) Every line is the realm's own render: the pilot's vo_ours\ and /lv ours|pack (pack vs ours) are gone.
-- (1.1.0) A quest giver's chat text -- the gossip window's, or the quest list's greeting -- plays too:
-- vo\g<npc>...-gossip[-m|-f].mp3, found by the NPC and a stretch of the text shown (Index.lua's gossip table).

local ADDON_DIR = "Interface\\AddOns\\LivingVoices\\"
local VO = LivingVoices            -- the DLL's table; nil when the engine is not loaded
local frame = CreateFrame("Frame")
local warned = false
local playing                      -- name of the clip playing, for /lv status
local lastLabel, lastEnded = nil, 0 -- the last line started, and when it finished (math.huge while it plays)
-- (1.1.0, the producer) a chat line is not replayed within 30 s of when it last stopped or ended, whatever played in
-- between: talk -> open a quest -> back to the chat brought it round again every time
local GOSSIP_REPLAY = 30
local heardAt = {}                 -- chat line -> GetTime() when it last stopped or ended
local lastNpc, lastTitle           -- who spoke the last line started, and its quest (for /lv bad)
local function heard(label, t) lastEnded = t; if label:find("-gossip", 1, true) then heardAt[label] = t end end

local ADDON_VERSION = "1.1.2"
local function say(msg) DEFAULT_CHAT_FRAME:AddMessage("|cff88ccffLiving Voices:|r " .. msg) end
local function dbg(msg)
    if LivingVoicesDB and LivingVoicesDB.debug then
        DEFAULT_CHAT_FRAME:AddMessage(("|cff888888lv %.2f|r %s"):format(GetTime() % 1000, msg))
    end
end

-- WoW's master slider x our own Voice slider (Sound options, under Ambience); silent when all sound is off, and in
-- the background when the game's "Sound in Background" is off (the engine plays outside WoW's mixer, so the client's
-- own background mute never reaches it; IsForeground needs engine 0.2)
local function voiceSetting() return (LivingVoicesSettings and LivingVoicesSettings.volume) or 1 end
-- voice-over on/off without a reload (the Voice checkbox beside the slider, or /lv on|off); on unless turned off
local function enabled() return not (LivingVoicesSettings and LivingVoicesSettings.enabled == false) end
local stop
local function setEnabled(on)
    LivingVoicesSettings.enabled = on and true or false
    if not on and stop then stop() end
    if _G.LivingVoicesEnableCheck then _G.LivingVoicesEnableCheck:SetChecked(on) end
    -- off: the slider is disabled outright (greyed and deaf to the mouse, the game's own way), the label greyed
    local s = _G.LivingVoicesVolumeSlider
    if s then
        if on then
            if BlizzardOptionsPanel_Slider_Enable then BlizzardOptionsPanel_Slider_Enable(s) else s:Enable() end
        else
            if BlizzardOptionsPanel_Slider_Disable then BlizzardOptionsPanel_Slider_Disable(s) else s:Disable() end
        end
        s:EnableMouse(on and true or false)
        if s.voiceLabel then
            if on then s.voiceLabel:SetTextColor(NORMAL_FONT_COLOR.r, NORMAL_FONT_COLOR.g, NORMAL_FONT_COLOR.b)
            else s.voiceLabel:SetTextColor(GRAY_FONT_COLOR.r, GRAY_FONT_COLOR.g, GRAY_FONT_COLOR.b) end
        end
    end
end
local function volume()
    if GetCVar("Sound_EnableAllSound") == "0" then return 0 end
    if GetCVar("Sound_EnableSoundWhenGameIsInBG") == "0" and VO and VO.IsForeground and not VO.IsForeground() then return 0 end
    return (tonumber(GetCVar("Sound_MasterVolume")) or 1) * voiceSetting()
end

-- A "Voice" slider in the game's own Sound panel (Interface -> Sound & Voice -> Sound), styled like Ambience.
-- The Volume box is 144 px tall and its four sliders end near 131 px: grow it by one slider row and add ours.
local function addVoiceSlider()
    local box, above = _G.AudioOptionsSoundPanelVolume, _G.AudioOptionsSoundPanelAmbienceVolume
    if not box or not above or _G.LivingVoicesVolumeSlider then return false end
    box:SetHeight(box:GetHeight() + 27)
    local s = CreateFrame("Slider", "LivingVoicesVolumeSlider", _G.AudioOptionsSoundPanel, "OptionsSliderTemplate")
    s:SetWidth(100); s:SetHeight(17)
    s:SetPoint("TOPRIGHT", above, "BOTTOMRIGHT", 0, -10)
    _G[s:GetName() .. "Low"]:Hide(); _G[s:GetName() .. "High"]:Hide(); _G[s:GetName() .. "Text"]:Hide()
    local label = s:CreateFontString(nil, "ARTWORK", "GameFontNormalSmallLeft")
    label:SetWidth(64); label:SetHeight(14)
    label:SetPoint("RIGHT", s, "LEFT", -4, 1)
    label:SetText("Voice")
    s.voiceLabel = label
    s:SetMinMaxValues(0, 1); s:SetValueStep(0.05)
    s:SetScript("OnShow", function(self) self:SetValue(voiceSetting()) end)
    s:SetScript("OnValueChanged", function(self, value)
        dbg(("Voice slider -> %.2f"):format(value))
        LivingVoicesSettings.volume = value
        if VO then VO.SetVolume(volume()) end
    end)
    s.tooltipText = "Volume of quest voice-over (Living Voices)."
    s:SetScript("OnEnter", function(self) GameTooltip:SetOwner(self, "ANCHOR_RIGHT"); GameTooltip:SetText(self.tooltipText, nil, nil, nil, nil, 1) end)
    s:SetScript("OnLeave", GameTooltip_Hide)
    s:SetValue(voiceSetting())
    -- the on/off box, between the "Voice" label and the slider (left of the label it spilled out of the Volume box;
    -- the producer, 2026-10-16); the slider is disabled while voice-over is off
    local c = CreateFrame("CheckButton", "LivingVoicesEnableCheck", _G.AudioOptionsSoundPanel, "OptionsCheckButtonTemplate")
    c:SetWidth(22); c:SetHeight(22)
    c:SetPoint("RIGHT", s, "LEFT", -2, 0)
    -- the template's click area runs ~100 px right for its label text: over the slider it took every click (0.1.8)
    c:SetHitRectInsets(0, 0, 0, 0)
    if _G[c:GetName() .. "Text"] then _G[c:GetName() .. "Text"]:SetText("") end
    c.tooltipText = "Quest voice-over on or off (Living Voices). Takes effect at once."
    c:SetScript("OnEnter", function(self) GameTooltip:SetOwner(self, "ANCHOR_RIGHT"); GameTooltip:SetText(self.tooltipText, nil, nil, nil, nil, 1) end)
    c:SetScript("OnLeave", GameTooltip_Hide)
    c:SetScript("OnShow", function(self) self:SetChecked(enabled()) end)
    c:SetScript("OnClick", function(self) dbg("Voice checkbox -> " .. tostring(self:GetChecked() and true)); setEnabled(self:GetChecked() and true) end)
    setEnabled(enabled())
    return true
end

-- the NPC you are talking to, by its creature entry: a 3.3.5 GUID is 0x F130 EEEEEE CCCCCC (type, entry, counter)
local function npcEntry()
    local g = UnitGUID("npc")
    if not g or g:sub(3, 4) ~= "F1" then return end
    return tonumber(g:sub(7, 12), 16)
end

local talkText                      -- the chat text on screen (GOSSIP_SHOW / QUEST_GREETING)
local function gossipClip()
    local id, text = npcEntry(), talkText
    if not id or not text then return end
    for _, x in ipairs(LivingVoicesIndex.gossip and LivingVoicesIndex.gossip[id] or {}) do
        if text:find(x[1], 1, true) then return x[2] end
    end
    dbg(("no chat line for npc %s: %s"):format(tostring(id), text:sub(1, 40)))
end

-- (1.1.0, 2026-10-31) race and class in the voice: Index.rc[line] = { {sentence, "R"|"C"|"RC", from_ms, to_ms}, ... }
-- -- the sentences that name the hearer's race or class -- and vo\<line>_s<sentence>_<word>.mp3 is that sentence for
-- one race ("night_elf"), class ("death_knight") or both ("blood_elf_mage"). Engine 0.4 cuts them into the take.
local RACE_KEY = { Human = "human", Orc = "orc", Dwarf = "dwarf", NightElf = "night_elf", Scourge = "undead", Tauren = "tauren",
                   Gnome = "gnome", Troll = "troll", BloodElf = "blood_elf", Draenei = "draenei" }
local function splices(label)
    local rc = LivingVoicesIndex.rc and LivingVoicesIndex.rc[label]
    if not rc or not VO.PlaySpliced or (tonumber(VO.Version) or 0) < 0.4 then return end
    local _, rt = UnitRace("player"); local _, ct = UnitClass("player")
    local race, class = RACE_KEY[rt or ""], ct and (ct == "DEATHKNIGHT" and "death_knight" or ct:lower())
    local args = {}
    for _, e in ipairs(rc) do
        local w = e[2] == "R" and race or e[2] == "C" and class or (race and class and (race .. "_" .. class))
        local name = w and (label .. "_s" .. e[1] .. "_" .. w)
        if name and LivingVoicesIndex.vo[name] then
            args[#args + 1] = e[3]; args[#args + 1] = e[4]; args[#args + 1] = ADDON_DIR .. "vo\\" .. name .. ".mp3"
        end
    end
    if #args > 0 then return args end
end

local function clip(kind)
    if kind == "gossip" then
        local base = gossipClip()
        if not base then return end
        for _, name in ipairs({ base .. (UnitSex("player") == 3 and "-f" or "-m"), base }) do
            if LivingVoicesIndex.vo[name] then return "vo\\" .. name, name end
        end
        return
    end
    local q = GetQuestID and GetQuestID() or 0
    if not q or q == 0 then                                 -- no GetQuestID: find the quest by its title
        -- (1.1.0) titles are shared ("Paladin Training": a draenei's and a blood elf's; "Taming the Beast": eighteen
        -- hunter quests and a realm quest with no voice): Index.pick has, for every quest line, who speaks it and a
        -- stretch of its text as the window shows it. A line plays only if that stretch is on screen; among those, the
        -- one the NPC in front of you speaks. None on screen: a quest the pack does not voice, and it stays silent.
        local npc, best = npcEntry(), 0
        local shown = (kind == "accept" and GetQuestText() or kind == "progress" and GetProgressText() or GetRewardText()) or ""
        -- a stretch unique among the title's quests outranks the NPC, which outranks a stretch they share
        local title = (GetTitleText() or ""):gsub("^%s+", ""):gsub("%s+$", "")   -- some live titles end in a space
        for _, id in ipairs(LivingVoicesIndex.title[title] or {}) do
            if LivingVoicesIndex.vo[id .. "-" .. kind] or LivingVoicesIndex.vo[id .. "-" .. kind .. "-m"] then
                local p = LivingVoicesIndex.pick and LivingVoicesIndex.pick[id .. "-" .. kind]
                if not p or p[2] == "" or shown:find(p[2], 1, true) then
                    local score = 1 + ((p and npc and p[1] == npc) and 1 or 0) + ((p and p[3] == 1 and p[2] ~= "") and 2 or 0)
                    if score > best then q, best = id, score end
                end
            end
        end
        if best == 0 then dbg(("no line matches this %s text (%s)"):format(kind, tostring(GetTitleText()))) end
    end
    if not q or q == 0 then return end
    local base = q .. "-" .. kind
    local sexed = base .. (UnitSex("player") == 3 and "-f" or "-m")   -- lines that differ by the player's sex
    for _, name in ipairs({ sexed, base }) do
        if LivingVoicesIndex.vo[name] then return "vo\\" .. name, name end
    end
end

local function play(kind)
    if not enabled() then return end
    if not VO then
        if not warned then say("engine not loaded (LivingVoices.dll / patched Wow.exe missing) -- no voice-over."); warned = true end
        return
    end
    -- chat text gives way to a quest line: the gossip window can come back while an offer or turn-in still plays
    if kind == "gossip" and playing and not playing:find("-gossip", 1, true) and VO.IsPlaying() then
        dbg("chat text waits: " .. playing .. " is playing"); return
    end
    local path, label = clip(kind)
    if not path then VO.Stop(); playing = nil; return end
    -- the same line again (e.g. turn-in with full bags: the client closes and reopens the window): never restart it
    if label == lastLabel and (VO.IsPlaying() or GetTime() - lastEnded < 15) then
        dbg(("skip repeat %s (playing=%s, ended %.1fs ago)"):format(label, tostring(VO.IsPlaying() and true), GetTime() - lastEnded))
        playing = playing or label; return
    end
    if kind == "gossip" and heardAt[label] and GetTime() - heardAt[label] < GOSSIP_REPLAY then
        dbg(("skip chat %s (heard %.1fs ago)"):format(label, GetTime() - heardAt[label])); return
    end
    dbg("play " .. label)
    VO.SetVolume(volume())
    if playing and VO.IsPlaying() then heard(playing, GetTime()) end      -- the line this one cuts off
    local ok, err
    local pieces = splices(label)
    if pieces then ok, err = VO.PlaySpliced(ADDON_DIR .. path .. ".mp3", unpack(pieces)) end
    if not ok then ok, err = VO.Play(ADDON_DIR .. path .. ".mp3") end   -- no pieces, or they would not play
    if ok then playing, lastLabel, lastEnded = label, label, math.huge; lastNpc, lastTitle = UnitName("npc"), kind ~= "gossip" and GetTitleText() or nil
    else say("cannot play " .. label .. ": " .. tostring(err)); playing = nil end
end

local pending                       -- a line waiting for the NPC's greeting (see below)
function stop()
    if VO then VO.Stop() end
    if playing then heard(playing, GetTime()) end
    playing, pending = nil, nil
end

-- The NPC's own greeting ("Greetings, citizen") plays when you click them; don't talk over it. A conversation starts
-- with the first window of an interaction (gossip, quest greeting or quest text); a line due less than GREETING
-- seconds after that start waits for the rest of it. Mid-conversation lines (Continue -> turn-in) play at once.
local GREETING = 1.5
local talkStart                     -- GetTime() when the current conversation began
local talkEnded                     -- GetTime() when its last window closed (a new window within 0.5 s continues it:
                                    -- gossip closes just before the quest text it hands over to opens)
local pendingAt
local stopAt                        -- a deferred stop after the quest window closed
-- (1.1.0, the producer: "speech isn't properly stopped after clicking through a quest (deny/cancel path)") a line
-- plays on past its window only when the quest was accepted or turned in. Declining, Cancel, Goodbye or Escape stops
-- it; the chat window that comes back after a decline used to cancel the stop and then wait for the line instead.
local kept                          -- AcceptQuest / GetQuestReward was called for the window on screen
hooksecurefunc("AcceptQuest", function() kept = true end)
hooksecurefunc("GetQuestReward", function() kept = true end)
local function beginTalk()
    local now = GetTime()
    if not talkStart or (talkEnded and now - talkEnded > 0.5) then talkStart = now end
    talkEnded = nil
end
local function endTalk() talkEnded = GetTime() end
local function request(kind)
    if kind ~= "gossip" then stopAt = nil end   -- a quest window is back: the pending stop is cancelled
    beginTalk()
    local wait = talkStart + GREETING - GetTime()
    if wait > 0.05 then pending, pendingAt = kind, GetTime() + wait; dbg(("%s waits %.1fs for the greeting"):format(kind, wait))
    else pending = nil; play(kind) end
end

-- (1.1.0, the producer) "/lv bad <note>": a line that sounds wrong is noted where it is heard, on the realm. The
-- report is whispered to the player themselves on the addon channel (prefix LVR); the realm's Lua
-- (server/lua/living_voices_report.lua) writes it to acore_characters.living_voices_report, says so in chat, and
-- answers "OK\t<key>"; tools/import_reports.py puts the line on the review page with its note. Every report
-- is also kept in LivingVoicesReports (account-wide SavedVariables) until the realm confirms it, and one still
-- unconfirmed is sent again at the next login or with "/lv reports send" (the first report ever made went out before
-- the realm had the script).
local askAt, askFor                  -- when to offer the GitHub link, and for which report (/lv bad, below)
local outbox, nextSend, loginSent = {}, 0, false      -- reports waiting to go out, 2.5 s apart (the realm takes one per 2 s)

local function sendReport(r)
    local head = table.concat({ r.v or ADDON_VERSION, r.line, (r.npc or ""):sub(1, 40), (r.title or ""):sub(1, 60),
        (r.zone or ""):sub(1, 40) }, "\t") .. "\t"
    local tail = "\t" .. r.at
    local note = (r.note or ""):sub(1, math.max(0, 250 - #"LVR" - 1 - #head - #tail))
    SendAddonMessage("LVR", head .. note .. tail, "WHISPER", UnitName("player"))
end

local function queueUnsent()
    local n = 0
    for _, r in ipairs(LivingVoicesReports or {}) do if not r.sent then table.insert(outbox, r); n = n + 1 end end
    return n
end

local function report(note)
    local line = (playing ~= "test" and playing) or lastLabel
    if not line then say("nothing has played yet to report.") return end
    note = (note or ""):gsub("[\t|]", " ")
    LivingVoicesReports = LivingVoicesReports or {}
    local r = { line = line, npc = lastNpc, title = lastTitle, note = note ~= "" and note or nil,
                at = date("%Y-%m-%d %H:%M:%S"), zone = GetRealZoneText() or "", v = ADDON_VERSION }
    table.insert(LivingVoicesReports, r); table.insert(outbox, r)
    say(("reporting %s%s%s ..."):format(line, lastNpc and (" (" .. lastNpc .. ")") or "", note ~= "" and (': "' .. note .. '"') or ""))
    askFor, askAt = r, GetTime() + 6 + 2.5 * #outbox    -- the realm answers within a second; nothing by then: GitHub
end

local function confirmed(key)
    for _, r in ipairs(LivingVoicesReports or {}) do if r.at == key then r.sent = true end end
end

-- (2026-11-02, the producer) on a realm without the report script nothing confirms a report: after 6 s the add-on
-- shows a link to the project's GitHub issue form, filled in with the report, to copy (Ctrl+C) into a browser. WoW's
-- chat cannot be copied from, an edit box can. "/lv reports copy" does the same for every unconfirmed report.
local ISSUES = "https://github.com/Crono141/LivingVoices/issues/new?template=bad-line.yml"
local function urlenc(s)
    return (tostring(s or ""):gsub("[^%w%-%._~]", function(c) return ("%%%02X"):format(c:byte()) end))
end
local function issueURL(r, more)
    local u = ISSUES .. "&title=" .. urlenc("Bad line: " .. r.line) .. "&line=" .. urlenc(r.line)
        .. "&note=" .. urlenc(r.note or "") .. "&npc=" .. urlenc(r.npc or "") .. "&quest=" .. urlenc(r.title or "")
        .. "&zone=" .. urlenc(r.zone or "") .. "&version=" .. urlenc(r.v or ADDON_VERSION)
    if more and more ~= "" then u = u .. "&more=" .. urlenc(more) end
    return u
end
local copyFrame
local function showCopy(text, title)
    if not copyFrame then
        local f = CreateFrame("Frame", "LivingVoicesCopyFrame", UIParent)
        f:SetWidth(580); f:SetHeight(130); f:SetPoint("CENTER", 0, 140); f:SetFrameStrata("DIALOG")
        f:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
                        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
                        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
        f:EnableMouse(true); f:SetMovable(true); f:RegisterForDrag("LeftButton")
        f:SetScript("OnDragStart", f.StartMoving); f:SetScript("OnDragStop", f.StopMovingOrSizing)
        f.title = f:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
        f.title:SetPoint("TOP", 0, -20); f.title:SetWidth(540)
        local eb = CreateFrame("EditBox", "LivingVoicesCopyBox", f, "InputBoxTemplate")
        eb:SetWidth(520); eb:SetHeight(20); eb:SetPoint("TOP", f.title, "BOTTOM", 0, -12)
        eb:SetAutoFocus(true); eb:SetMaxLetters(0)
        eb:SetScript("OnEscapePressed", function() f:Hide() end)
        eb:SetScript("OnEnterPressed", function() f:Hide() end)
        eb:SetScript("OnEditFocusGained", function(self) self:HighlightText() end)
        eb:SetScript("OnTextChanged", function(self) if self:GetText() ~= f.text then self:SetText(f.text); self:HighlightText() end end)
        f.eb = eb
        local b = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
        b:SetWidth(90); b:SetHeight(22); b:SetPoint("BOTTOM", 0, 16); b:SetText(CLOSE or "Close")
        b:SetScript("OnClick", function() f:Hide() end)
        tinsert(UISpecialFrames, "LivingVoicesCopyFrame")       -- Escape closes it
        copyFrame = f
    end
    copyFrame.text = text; copyFrame.title:SetText(title); copyFrame:Show()
    copyFrame.eb:SetText(text); copyFrame.eb:SetFocus(); copyFrame.eb:HighlightText()
end
local function offerGitHub(list)
    if #list == 0 then say("no report to copy.") return end
    local more = {}
    for i = 2, #list do
        local r = list[i]
        table.insert(more, ("%s | %s | %s"):format(r.line, r.npc or "", r.note or ""))
    end
    showCopy(issueURL(list[1], table.concat(more, "\n")),
        "This realm does not collect Living Voices reports. Press Ctrl+C to copy the link, paste it into your\n"
        .. "browser and submit the form on GitHub. Thank you!" .. (#list > 1 and ("\n(" .. #list .. " reports in one)") or ""))
end

frame:SetScript("OnEvent", function(_, event, ...)
    if event ~= "CVAR_UPDATE" and event ~= "ADDON_LOADED" then
        dbg(("%s quest=%s title=%s"):format(event, tostring(GetQuestID and GetQuestID()), tostring(GetTitleText and GetTitleText())))
    end
    if event == "QUEST_DETAIL" then kept = false; request("accept")
    elseif event == "QUEST_PROGRESS" then kept = false; request("progress")
    elseif event == "QUEST_COMPLETE" then kept = false; request("complete")
    elseif event == "GOSSIP_SHOW" or event == "QUEST_GREETING" then
        talkText = event == "GOSSIP_SHOW" and GetGossipText() or GetGreetingText()
        request("gossip")
    elseif event == "QUEST_FINISHED" then
        -- close-then-reopen (full bags at turn-in) must not cut the line: stop only if no quest window is back in 0.4 s;
        -- an accepted or turned-in quest's line plays on
        endTalk()
        if kept then dbg("quest accepted or turned in: the line plays on")
        else stopAt = GetTime() + 0.4; dbg("stop deferred 0.4s") end
    elseif event == "PLAYER_LEAVING_WORLD" then stop(); endTalk()
    elseif event == "GOSSIP_CLOSED" then
        endTalk()
        -- walking away stops the chat line; a quest the gossip hands over to cancels this and plays its own
        if playing and playing:find("-gossip", 1, true) then stopAt = GetTime() + 0.4 end
    elseif event == "CVAR_UPDATE" and VO then VO.SetVolume(volume())
    elseif event == "CHAT_MSG_ADDON" then
        local prefix, text, _, from = ...
        if prefix == "LVR" and from == UnitName("player") then
            local key = text:match("^OK\t(.+)$")
            if key then confirmed(key) end
        end
    elseif event == "PLAYER_ENTERING_WORLD" and not loginSent then
        loginSent = true
        local n = queueUnsent(); nextSend = GetTime() + 5           -- give the realm a moment after the loading screen
        if n > 0 then say(("sending %d report(s) the realm has not confirmed yet."):format(n)) end
    elseif event == "ADDON_LOADED" and ... == "LivingVoices" then
        LivingVoicesDB = LivingVoicesDB or {}
        local restored = type(LivingVoicesSettings) == "table" and tonumber(LivingVoicesSettings.volume)
        LivingVoicesSettings = LivingVoicesSettings or { volume = 1 }
        say(("voice-over %s, volume %d%% (%s)."):format(enabled() and "on" or "OFF (/lv on)", voiceSetting() * 100 + 0.5,
            restored and "restored from saved settings" or "default -- nothing saved yet"))
        if not addVoiceSlider() then say("could not add the Voice slider to the Sound panel -- use /lv volume 0-100.") end
        say(VO and ("engine " .. VO.Version .. " ready. /lv for options.") or "engine NOT loaded -- see /lv status.")
        -- (1.1.0) the lines are in LivingVoices.MPQ, which engines before 0.3 cannot read
        if VO and (tonumber(VO.Version) or 0) < 0.3 then
            say("this engine is too old for the 1.1.0 lines: copy the new LivingVoices.dll from the download next to Wow.exe.")
        end
    end
end)
for _, e in ipairs({ "QUEST_DETAIL", "QUEST_PROGRESS", "QUEST_COMPLETE", "QUEST_FINISHED", "PLAYER_LEAVING_WORLD",
                     "GOSSIP_SHOW", "QUEST_GREETING", "GOSSIP_CLOSED", "CVAR_UPDATE", "ADDON_LOADED", "CHAT_MSG_ADDON",
                     "PLAYER_ENTERING_WORLD" }) do frame:RegisterEvent(e) end

-- the sliders can change without CVAR_UPDATE in 3.3.5, and focus has no event: re-apply 4x a second while a line plays
local elapsed = 0
frame:SetScript("OnUpdate", function(_, dt)
    if stopAt and GetTime() >= stopAt then stopAt = nil; dbg("deferred stop fires"); stop() end
    if pending and GetTime() >= pendingAt then local k = pending; pending = nil; play(k) end
    if outbox[1] and GetTime() >= nextSend then sendReport(table.remove(outbox, 1)); nextSend = GetTime() + 2.5 end
    if askAt and GetTime() >= askAt then
        local r = askFor; askAt, askFor = nil, nil
        if r and not r.sent then offerGitHub({ r }) end
    end
    elapsed = elapsed + dt
    if elapsed < 0.25 then return end
    elapsed = 0
    if VO and playing then
        VO.SetVolume(volume())
        if not VO.IsPlaying() then heard(playing, GetTime()); playing = nil end
    end
end)

SLASH_LIVINGVOICES1 = "/lv"
SLASH_LIVINGVOICES2 = "/livingvoices"
SlashCmdList.LIVINGVOICES = function(msg)
    local raw = (msg or ""):gsub("^%s+", "")
    msg = raw:lower()
    if msg == "bad" or msg:match("^bad%s") then report((raw:match("^%S+%s+(.-)%s*$") or "")) return end
    if msg == "reports" then
        local r = LivingVoicesReports or {}
        say(("%d report(s) saved%s"):format(#r, #r > 0 and ":" or "."))
        for i = math.max(1, #r - 4), #r do say(("  %s  %s%s  %s"):format(r[i].at, r[i].line, r[i].note and (' "' .. r[i].note .. '"') or "",
            r[i].sent and "(on the realm)" or "(not confirmed yet)")) end
        return
    elseif msg == "reports send" then say(("sending %d unconfirmed report(s)."):format(queueUnsent())) return
    elseif msg == "reports copy" then
        local list = {}
        for _, r in ipairs(LivingVoicesReports or {}) do if not r.sent then table.insert(list, r) end end
        -- every report taken by the realm: the latest one, to file on GitHub as well
        if #list == 0 and LivingVoicesReports and #LivingVoicesReports > 0 then list = { LivingVoicesReports[#LivingVoicesReports] } end
        offerGitHub(list) return
    elseif msg == "reports clear" then LivingVoicesReports = {}; outbox = {}; say("reports cleared.") return end
    if msg == "stop" then stop(); say("stopped.")
    elseif msg == "on" or msg == "off" then
        setEnabled(msg == "on"); say("voice-over " .. (enabled() and "on." or "off."))
    elseif msg:match("^volume") then
        local v = tonumber(msg:match("(%d+)"))
        if v then
            LivingVoicesSettings.volume = math.max(0, math.min(100, v)) / 100
            if _G.LivingVoicesVolumeSlider then _G.LivingVoicesVolumeSlider:SetValue(LivingVoicesSettings.volume) end
            if VO then VO.SetVolume(volume()) end
        end
        say(("voice volume %d%%."):format(voiceSetting() * 100 + 0.5))
    elseif msg == "test" then
        if not VO then say("engine not loaded.") return end
        VO.SetVolume(volume())
        -- (0.4) with your class in it, as McBride's offer plays in game ("young paladin")
        local pieces, ok, err = splices("783-accept")
        if pieces then ok, err = VO.PlaySpliced(ADDON_DIR .. "test.mp3", unpack(pieces)) end
        if not ok then ok, err = VO.Play(ADDON_DIR .. "test.mp3") end
        say(ok and "playing test line (/lv stop to cut it)." or ("test failed: " .. tostring(err)))
        playing = ok and "test" or nil
    elseif msg == "debug" then
        LivingVoicesDB.debug = not LivingVoicesDB.debug
        say("debug " .. (LivingVoicesDB.debug and "ON: quest-window events print to chat." or "off."))
    elseif msg == "status" then
        if not VO then
            say("engine NOT loaded. Check LivingVoices.log next to Wow.exe, and that Wow.exe is the patched one.")
        else
            local p, pos, len = VO.IsPlaying()
            say(("add-on %s, engine %s, voice-over %s, voice %d%% (x master = %.2f), %s"):format(ADDON_VERSION, VO.Version,
                enabled() and "on" or "OFF", voiceSetting() * 100 + 0.5, volume(),
                p and ("playing %s %.1f/%.1fs"):format(playing or "?", pos, len) or "idle"))
        end
    else
        say("/lv on / off | stop | volume <0-100> | test | status | debug | bad <note> | reports [send | copy | clear]")
    end
end
