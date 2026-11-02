LIVING VOICES -- quest voice-over for World of Warcraft 3.3.5a
==============================================================
Every quest giver speaks: what they say when you talk to them (the chat window, before you pick a quest), the offer
when you open a quest, the progress line when you come back mid-quest, and the turn-in line when you hand it in. The
voice stops the moment you close the window or walk away.

Install (keep the game closed):
 1. Copy LivingVoices.dll and LivingVoicesPatcher.exe into your World of Warcraft folder, next to Wow.exe.
 2. Copy the Interface folder into the same World of Warcraft folder (it merges with the one already there; the
    add-on lands in Interface\AddOns\LivingVoices -- do not rename that folder).
 3. Double-click LivingVoicesPatcher.exe. It lets Wow.exe load the voice engine and keeps the original as
    Wow.exe.stock. (No Windows? patch_wowexe.py does the same with Python: python3 patch_wowexe.py Wow.exe)
 4. Start the game. Chat says "Living Voices: engine 0.4 ready." once you log in.

The lines are in two archives in Interface\AddOns\LivingVoices: LivingVoices.MPQ and LivingVoices.part2.MPQ (3.6 GB
together; the GitHub release ships them as two zips, part1 and part2 -- unzip both into the same place). Keep them
where they are; the engine reads every .MPQ in that folder.

Settings:
 - Interface -> Sound & Voice -> Sound: a "Voice" slider under Ambience sets the voice-over volume; the box beside
   it turns voice-over on and off at once.
 - /lv on | off     turn it on or off      /lv volume 0-100   voice volume
 - /lv stop         cut the line playing   /lv test           play a test line
 - /lv status       engine and add-on state
 - /lv bad <note>   report the line just played, while it plays or right after. A realm that collects reports
                    takes it at once; anywhere else a box opens with a link to the project's GitHub form, filled
                    in: Ctrl+C, paste it into your browser, submit. /lv reports copy does it again later.

Undo: run LivingVoicesPatcher.exe again and answer y (Wow.exe goes back to the original), then delete
LivingVoices.dll and Interface\AddOns\LivingVoices.

Trouble:
 - "engine NOT loaded" in /lv status: LivingVoices.dll is not next to Wow.exe, or Wow.exe is not the patched one.
   LivingVoices.log next to Wow.exe says what the engine saw.
 - The patcher refuses: it only patches the stock 3.3.5a (12340) Wow.exe. If another tool changed Wow.exe, put that
   tool's original back first.

A fan work: not affiliated with, endorsed by or sponsored by Blizzard Entertainment.
See LICENSES.txt for what is whose.
