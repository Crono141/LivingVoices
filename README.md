# Living Voices

**An experiment: can one person with two consumer GPUs give every quest giver in World of Warcraft 3.3.5a a voice
that sounds acted, not read?**

Living Voices is the result. It is a full voice-over for the Wrath of the Lich King client (build 12340), made between
2026-10-10 and 2026-11-02 for a small AzerothCore realm:

- **24,517 lines** from **4,137 speakers**: every quest's offer, progress and turn-in text, and every quest giver's
  chat (gossip) text. That is about 1.2 million words and **100 hours** of speech.
- **24,194 race and class clips**, another 25 hours. A sentence that says "brave paladin" or "night elf" is rendered
  once for each race or class the hearer can be, and is spliced into the line as it plays.
- Every line was **directed** by a language model, **performed** by a speech model, **checked by software** for wrong
  words, bad pauses, rushed stops and held sounds, and **retaken** until it passed. A human producer listened only to
  the lines that failed six takes in a row.
- On the client side: an add-on, a small playback engine (the stock client cannot stop a sound once it starts), and a
  one-file archive of the lines at 64 kbps (3.6 GB).

This repository is the pipeline and the client, with the methods we settled on and what we tried before them. It
contains **no Blizzard text or audio**: the game's quest text, recordings and sounds are read from your own client
and server (see [Data](#what-is-not-in-this-repository)). The finished pack is published as a release.

**Producer:** [Crono141](https://github.com/Crono141). He set the goals, judged every listening test and wrote the rules
the pipeline follows; "the producer" in the code comments is him. **Engineering:** Claude (Anthropic), working in Claude
Code, wrote the pipeline, the engine and the checks with him over those three weeks. Dates in comments mark when each
decision was made and why.

---

## Results

| | |
|---|---:|
| Quest lines (offer, progress, turn-in) | 21,805 (93 h) |
| Chat lines (gossip and quest-list greetings) | 2,712 (7 h) |
| Race/class sentence clips | 24,194 (25 h) |
| Speakers | 4,137 |
| Production nights (01:00-09:00, two RTX 3090s) | about 19, plus day runs |
| Render speed per card | about 1.16x real time (IndexTTS-2, one beam) |
| Takes that failed the automatic check, first attempt | 16-20% for whole lines (October), 3-8% for race/class clips |
| Lines sent to the producer after six failed takes | about 3.8% of the main pass; every one resolved for 1.1.1 |
| Release 1.1.1 | 48,691 files in one MPQ, 3.64 GB zip |

The single most useful finding: **automatic retakes are cheap, a human listening is not.** Every check was tuned to
send a doubtful take to another seed rather than to the producer, and a line was accepted as good enough once it had
failed six times and the best take was heard once.

---

## The pipeline

```
quest text (AzerothCore) ──► clean & respell ──► director (Gemma) ──► IndexTTS-2 (ComfyUI) ──► filters & pacing
                                    ▲                    │                     ▲                      │
                           pronunciation rules     beats, emotion,      voice reference           speech check
                                                   intensity, notes     (casting)                 (Whisper, aligner,
                                                                                                    Gemma judge)
                                                                                                        │
                       review page ◄── fails 6 seeds ──────────────────────── fails: next seed ◄───────┤
                                                                                                        ▼ passes
                          race/class clips ──► splice points ──► 64 kbps ──► one MPQ ──► add-on + engine
```

Everything runs from `tools/` against a SQLite queue (`overnight.py`), from 01:00 to 09:00 each night
(`nightly.py`, `tools/systemd/`).

---

## Methods

Each section gives what we use now, then what we tried and why it did not last.

### 1. Playing a line, and stopping it

**What we use.** The 3.3.5a client gives add-ons `PlaySoundFile` but no way to stop a sound. A voice-over built on it
keeps talking after you close the quest window. So the add-on plays through a small engine, `LivingVoices.dll`
(miniaudio for playback, StormLib to read the archive). The DLL adds `LivingVoices.Play/Stop/SetVolume/IsPlaying/
PlaySpliced` to the game's Lua. The stock `Wow.exe` loads it after a patch from
[awesome_wotlk](https://github.com/FrostAtom/awesome_wotlk) (three byte patches, the DLL's name in place of theirs).
`LivingVoicesPatcher.exe` applies that patch, checks every byte against the stock 12340 exe first, and keeps
`Wow.exe.stock`. Running it again undoes it.

The add-on speaks the offer, progress and turn-in text, and a quest giver's chat text. It waits 1.5 s so it does not
talk over the NPC's own greeting, and it fades out when the window closes or you walk away. A full-bags turn-in that
closes and reopens the window does not cut the line. `/lv bad <note>` reports the line just heard to the realm
(`server/`), where it is queued for retakes.

**What we tried.** The community VoiceOver add-on plays voices as music and stops them by playing silence, and its
stop-on-close option is off by default. We proposed cutting each line into 1-2 s files so the add-on could stop
between them. The producer turned it down before it was built: "stuttering playback, delayed segments, early
segments, disk thrashing… I'd like to think more about what tools we have and how we can … bend them to our will."
Precedents found in research (awesome_wotlk's DLL loader, WrathClassicAPI's way of registering Lua functions on 12340)
made the engine possible.

### 2. Finding which line to play

**What we use.** The client tells an add-on the quest's title, not its id, and titles are shared: "Taming the Beast"
is eighteen hunter quests. Each line carries a 40-character verbatim stretch of its text, taken from the realm's live
database, and plays only if that stretch is on screen. A unique stretch beats a matching NPC, which beats a shared
stretch, and no match plays nothing. Chat lines are matched by NPC plus a stretch. A simulation over all 21,000 quest
lines against the live texts gave no wrong lines.

**What we tried.** Matching by title alone. A realm-only quest with a shared title played a tauren's line from a
different NPC.

### 3. The text

**What we use.** The text is the realm's own: AzerothCore's world database, plus the realm's custom and holiday
quests read from the live database (`extract_live.py`). Before anything is spoken:
- `$N`, `$C`, `$R` become "adventurer", "hero", "traveler", and `$G` text gets a version for each sex.
- Typos are fixed (`data/text_fixes.json`). Numbers, Roman numerals, possessives and contractions are normalised, so
  "Buzzbox 827" is not "eight hundred twenty seven" and "IV" is not "eye vee".
- Lines whose commas misled the voice ("What is next, dragons") get a reading script. Claude wrote these after four
  attempts to have the director model do it over-edited the text.
- Stage directions ("<Erona eyes you.>") are read by a narrator voice or left silent. Sound words (`*snort*`, `*cluck*`,
  `*whir*`) become sounds cut from the client (`build_sfx.py`, `data/sfx.json`), and murloc speech is built from murloc
  sounds.
- The text on screen never changes; only what the voice reads does.

**What we tried.** Dropping bare addresses ("Greetings, Mage!" read as "Greetings"). That was the right call until the
race/class work (§11) could say them properly, and then they came back.

### 4. Pronunciation

**What we use.** `data/pronounce.json`, 2,700 respellings ("Quel'Thalas" → *Kwelthallahs*, "Desolace" →
*Dessohlace*, "Draenei" → *Draneye*). They come from three sources:
- Warcraft Wiki IPA and respellings, converted with a fixed table (`wiki_pronounce.py`).
- A phoneme search: candidate spellings are spoken by the TTS, phonemised with wav2vec2-espeak, and compared with the
  wiki IPA or with how Blizzard's own actors say the name in the client (`pronounce_search.py`, `phonemes.py`).
- A spreadsheet the producer corrected by hand for names nobody pronounces officially (`pronounce_review.py`).

Rules learned: **no hyphens** in respellings (the voice breaks at them), and no extra letters to lengthen sounds. Names
are also checked when spoken: `_heard_wrong` lists transcripts that mean a name was misread ("Defy U.S."; "Drani" for
draenei), and `_heard_right` lists the speech recogniser's own misspellings of a correct reading ("Torrin" for tauren).

**What we tried.** Respelling by ear alone, then letting the speech recogniser judge. The producer: "I'm not sure I
understand how gemma and whisper are going to get this right. Lets google a pronunciation guide." Automatic wiki
respellings also produced bad ones (Theramore as "Deramaw"), and nineteen were removed after an audit. "Defias" took
three weeks and more than twenty seeds on some lines.

### 5. The speech model

**What we use.** [IndexTTS-2](https://github.com/index-tts/index-tts), zero-shot voice cloning with emotion control,
run in ComfyUI through TTS Audio Suite. Settings:
- one beam;
- the reference trimmed to its first 12 s, with every silence in it capped at 0.3 s (the model copies a reference's
  pauses);
- segments of 120 tokens, temperature 0.8.

[Qwen3-TTS VoiceDesign](https://github.com/QwenLM) is used only to *design* reference voices for speakers with no
recording (§6). IndexTTS-2 then clones those.

**What we tried.**
- **Qwen3-TTS VoiceDesign as the performer.** Its voices were "fine for the human and the night elf, but the dwarf
  didn't sound anything like a dwarf… the forsaken sounded entirely too chipper", and "too smooth" overall.
- **Three beams.** The producer: "I can't hear a difference in the quality between B1 and B3. In fact, B1 might have
  more emotion."
- **Other levers:** shorter segments, a lower temperature and rendering sentence by sentence each made no improvement,
  or a worse one.
- **ChatterBox voice conversion** carried a dialect from a speech corpus onto a designed voice. It "works well enough",
  but it was not needed once game voices were used.

### 6. Casting: whose voice

**What we use.** Each speaker is cast once, and all their lines use that voice. The order of preference:
1. **The character's own recording** from the client (raid and quest lines), or their **Warcraft III** voice (Thrall,
   Rexxar, Malfurion, Shandris…).
2. **A same-body voice** (a flesh golem speaks like Patchwerk; a centaur like a centaur).
3. **A race voice from the client:** the NPC greeting sets (the Ironforge dwarf, the tauren shaman, the Forsaken man,
   Vol'jin for the darkest trolls), Warcraft III units (Gazlowe for goblins), and for blood elves the player character's
   own voice.
4. **A designed voice:** the director model writes a casting brief from the character's dialogue ("lived-in and
   textured, never smooth"), Qwen3 VoiceDesign speaks one of their lines, and that clip becomes the reference.

**One recording, many speakers.** Each speaker gets its own point in a pitch × formant grid (Praat's *Change Gender*,
applied to the reference), so one race voice becomes a hundred different people. Each grid was found by pushing a 5×5
test to failure and keeping the range the producer accepted.

**References.** A single clip in a normal speaking voice beats a longer one. Longer references fill with shouting and
lose the accent. A yelled reference is swapped for the calmest clip the character has, which won four of five. Overrides
chosen by ear are kept in `data/game_ref_override.json`.

**Children.** Boys clone young Anduin's three greetings, offset ±1 semitone by race. Girls are designed, then shifted
into 335-390 Hz (the ceiling is the producer's "Mootoo the Younger"; higher was "chipmunk").

**Accents.** Only dwarves, draenei, trolls and goblins have one; humans stay neutral. Troll dialect spellings ("deir")
help: "it certainly sells the accent". A blanket dwarf dialect made things worse and was removed.

**What we tried.**
- **Reusing the existing fan voice-over packs** (AI VoiceOver, the carevass packs, Spoken Quests, SpeakStone). Text
  matching found 14,643 of 21,446 lines already voiced. We dropped it twice:
  - for quality: "In an AB test… ours came out better than our reference packs. So unfortunately I think the right
    decision is to render the entire lot ourselves";
  - for licence: none of the packs grants permission to redistribute its audio.

  Some speakers still clone the voice players know from those packs, but no pack recording ships.
- **A children's speech corpus** (Plymouth, Zenodo 200495). It took days, and young Anduin's three greetings, already
  in the client, beat it outright: "I'm a little miffed we wasted so much time when we had that voice sample right next
  to us the whole time." Since then: **search the game's files before any dataset.**
- **Shifting the output instead of the reference** ("the overall post method doesn't sound very good at all"), and
  **shifting voices up** (it corrupts the high end).
- **Assembling a reference from several clips** gave odd performances: "a mix of sentences strung together".
- **Pack clones for blood elves**, which were flat: "Player voice is way better than both."

### 7. Direction

**What we use.** A director model (Gemma 12B through llama.cpp) reads a whole quest before any of it is spoken: the
title, zone, chain, speakers, objectives and all three texts (`direct.py`). For each line it returns:
- an **actor's note** ("Marshal McBride to the hero; authoritative yet encouraging");
- the **subtext**;
- **beats**: groups of the line's numbered sentences. The text is never rewritten. A line is one beat unless it really
  turns (`steady_check.py`).

For each beat it gives a **style**, an **emotion phrase** ("warmly welcoming, with a slight dry chuckle at
'farming'") and an **intensity** from 1 to 10. A per-character note, written by the model from everything the character
says and what others say of them, steadies a speaker across quests (`actor_read.py`).

IndexTTS-2 receives the emotion phrase as text. Intensity sets the emotion strength:
`alpha = clamp(0.30 + 0.06 × intensity, 0.2, 0.6)`. Women read at an intensity floor of 5. Beats at intensity 4 or
below read "!" as ".". A question gets "???" so it rises. **Restraint is the rule:** intensity is saved for
world-shaking stakes. See `examples/direction_783.json`.

**What we tried.**
1. **Emotion vectors:** "sounds like someone delivering in the style of Captain Kirk being dramatic, pauses and all."
2. **Style clips** from game recordings as the emotion reference: at alpha 0.65 the clip's own voice bled into the
   NPC's, and the delivery drifted between phrases.
3. **Emotion text plus the actor's notes** won: "This is the best delivery by far … I think we have a winning formula."
4. **Splitting lines into beats freely:** the director split 63% of lines in two, and long lines ran away at the second
   beat. "The one beat versions are so much better… Each and every one is better."
5. **A fixed emotion strength:** Marshal McBride's errand to Goldshire "sounds like he's sending us to mount doom to
   destroy the ring." A cap of 0.75 let lines run away; 0.6 holds.
6. **No intensity floor for women:** 12 of 37 women came out flat, against 2 of 39 men.

### 8. After the performance

**What we use.**
- **Pacing.** A line slower than its voice's floor (2.5 words a second; 2.7 for dwarves and trolls, 2.3 for tauren) is
  sped up with the pitch kept, at most 1.25×. Beats are matched to the line's mean tempo. Undead men keep only their
  longest pause; other pauses over 0.5 s are cut to 0.4 s.
- **Character filters** (`morph_presets.py`): a faint echo for a dragon in mortal form and a strong one in its own
  shape, a ghost filter for friendly spirits, a whisperer for monstrous ones, and novelty morphs for beasts, golems,
  giants and robots. The speech check hears the line before the filter.
- **Drawn-out sounds** ("Ssstrike", "sorrrrowful") are stretched in the finished audio (`stretch_sounds.py`). Spelling
  them long did not work.

**What we tried.** Speeding up the reference instead of the result cost the troll women their accent: "We lost
Maywiki's accent." (Two references sped up 12% early on were kept: they had been approved by ear before this lesson.)

### 9. The speech check

**What we use.** Every take is heard by software before anyone else hears it (`overnight.py check`, `asr_check.py`).
1. **Words.** faster-whisper large-v3-turbo transcribes the take; it must match the script at **≥ 0.85**. A dropped
   word is a retake even when the score passes. Laughs, hums and a dialect's own spellings are not counted against it.
   If words seem dropped, the take is heard again without the voice detector, which can cut a last word after a pause.
2. **Pace.** Under 2.0 words a second is a retake (lines under 10 words, and halting lines with "…", are exempt). A
   race/class clip is judged against its own take's pace.
3. **Odd pauses.** The take is aligned word by word to the script (Meta's MMS forced aligner via torchaudio). Every
   silence of **0.5 s or more** where the script has no punctuation goes to the director model, which judges whether an
   actor would breathe there or whether the pause breaks a phrase.
4. **Held sounds.** Loud sound where the aligner finds no word ("noooOOOUUEEE?", "jerkinnnnn"). Over **0.75 s** is a
   retake.
5. **Missed stops.** A full stop, question, exclamation, colon or semicolon read straight through: aligned gap ≤ 0.10 s
   and no silence.
6. **Mispronounced names** (§4).

A take that fails goes to the next of **six seeds**. A line that fails all six goes to a review page with its best take
and every alternative, where the producer accepts one, sends it back for six more seeds, or notes a fix.

**What we tried.**
- **Judging quality with models.** UTMOS ordered take pairs the producer's way 47% of the time, "a coin flip", and an
  arousal model could not tell good takes from flat ones.
- **Cycling seeds 1, 2, 3.** "Seed 1 has historically been bad all around." Seeds are now hashed from the line's name.
- **Three seeds,** then keeping the third take regardless: "I'd rather increase the seed attempts than keep bad takes."
- **Splicing a pause into a missed stop** instead of retaking: "the hard stop is noticeable."
- **An odd-pause limit of 0.3 s:** after reviewing 686 flagged lines the producer set 0.5 s ("The median longest pause
  is 0.44s? I'd say accept anything under 0.5 seconds"), which passed 404 lines at once.
- **Blind listening samples** of 120 lines per round measured progress: 46%, then 54%, then 56% rated good or better.
  That was short of the 60-70% target, so the full set was rendered with the automatic retakes, and the remaining bad
  lines were fixed from listening and playtests rather than by more sampling.

### 10. Production

**What we use.** A SQLite queue, one render worker per renderer, and a director thread that directs and casts ahead of
the renderers. Run from 01:00 to 09:00 by a systemd timer (`nightly.py`), on two RTX 3090s that also serve other work:
- card 1: its own ComfyUI beside the realm's chat LLM;
- card 0: a ComfyUI shared with the producer's own work, whose jobs the renderer waits for, and from 11-01 a second
  IndexTTS-2 instance beside it.

When the queue runs dry before 09:00, the run scores what it has and renders the retakes the same night, round after
round. The morning steps prepare the splices, re-encode, build, and publish.

**Throughput tuning, after the fact.** On 2026-11-01 we measured the run:
- the speech check used one CPU core and 16% of a GPU, decoding each take six times;
- one IndexTTS-2 left its card half idle;
- the judge used four of the LLM server's eight slots.

Decoding once, running three checkers, a second renderer and all eight slots roughly halved the run. The producer's
lesson: "Had these changes gone into place before the full run, it could have been completed in half the time." Tune
on a sample first.

**What broke, and what we learned.**
- A VRAM manager that freed the card before every prompt cost seconds a line.
- A ComfyUI port inside Linux's ephemeral range sometimes failed to bind; it is now retried, and the port reserved.
- An out-of-memory error mid-check once threw away a whole night's scores. Each line is now checked on its own.
- Loading a large model on a card mid-run killed the renderer. Jobs now time out and lost jobs are detected.
- Another project's ComfyUI wiped a shared temp folder at midnight. Every instance now has its own, and jobs on the
  shared machine are surveyed before anything is scheduled.
- Lines waiting for an undesigned voice starved the queue. Voices are now designed before retakes.

### 11. Race and class in the voice

**What we use.** The producer's design: a sentence with `$R` or `$C` is rendered once for every race or class the
hearer can be (from the quest's allowed races, else the giver's faction), and spliced into the line's accepted take
at playback (`variants.py`, `splices.py`, engine 0.4's `PlaySpliced`).
- The take is aligned once, and each sentence is cut at the quietest point of the pauses around it.
- Each clip is trimmed, paced to the sentence it replaces (0.87-1.15×), matched in level, padded with the original's
  silence and stored at 64 kbps.
- The engine decodes the take and the hearer's clips and swaps them in memory. Every race hears the same performance
  with their own word in it.

Lines with narration, sounds, a filter or a second speaker are spliced too, but are heard spliced by the speech
recogniser before their clips ship (all 243 passed). A three-word clip can take its beat's emotion too strongly ("Well
done, warlock" came out cackling), so a clip can be given its own direction (`data/variant_beats.json`).

**What we tried.** Re-rendering whole lines per race and class would have thrown away hours of accepted audio and
given each race a different performance. Joining the clips ahead of time would have added about 2.4 GB to the download;
splicing at playback adds 0.8 GB.

### 12. Packaging

**What we use.** All lines in one MPQ in the add-on's folder (`vo\<line>.mp3`), written by `client/build/mkpack` and
read back in full through the engine's own reader before anything is zipped. 64 kbps MP3: in a blind test the producer
heard no difference down to 48 kbps ("All bitrates sound the same to me"). Fixes from in-game reports ship as a small
`LivingVoices.patch.MPQ`, which the engine mounts after the main archive.

**What we tried.** 1.0.0 shipped 21,456 loose files (5.4 GB). One archive is faster to copy, and an antivirus scans one
file, not twenty-four thousand.

---

## What is not in this repository

Everything that holds Blizzard's text or audio, or this realm's casting, stays on the machine that made it. Each is
rebuilt from your own client and server:

| File (in `data/`) | What it is | Made by |
|---|---|---|
| `ac_quests.json`, `gossip.json`, `live_world.json` | quest and chat text | `extract_quests.py` (AzerothCore SQL), `gossip_plan.py`, `extract_live.py` (live database) |
| `plan_v3.csv` | every line: speaker, race, sex, voice source | `plan_v3.py` |
| `race_cast.json`, `voice_cast.json`, `actor_notes.json` | casting and character notes | `race_cast.py`, `design_voices.py cast`, `actor_read.py` |
| `directions.jsonl` | the director's beats for every quest | `overnight.py` (director thread, `direct.py`) |
| `clone_refs/`, `child_refs/`, `style_sets/<race>/`, `game_voices/`, `sfx/` | voice references and sounds | `game_voices.py`, `bakeoff.py bank2`, `child_cast.py`, `build_style_sets.py`, `build_sfx.py`, all from the client's MPQs (and Warcraft III's) |
| `designed_voices/` | designed reference voices | `design_voices.py render` |
| `scripts.json`, `rewrites.json` | reading scripts and placeholder rewrites | written per line during review |
| `variants.json`, `splices.json` | race/class clips and their cut points | `variants.py`, `splices.py` |
| `render/`, `render64/`, `overnight.sqlite` | takes, the 64 kbps copies, the queue and every score | the nightly run |

`examples/` shows the formats on one quest: Marshal McBride's "A Threat Within" (783), with its plan rows, casting,
direction and the two finished lines.

---

## Running it

You need:
- an AzerothCore 3.3.5a world database (and, for the realm's own quests and in-game reports, a read-only login to it);
- the 3.3.5a client's `Data` folder;
- ComfyUI with TTS Audio Suite and IndexTTS-2;
- an OpenAI-compatible LLM server (we used llama.cpp with Gemma 12B);
- faster-whisper and torchaudio in `.venv`;
- an NVIDIA GPU, ideally two.

```
cp config.example.json config.local.json      # every path, server and login file; documented inside
cd data
python3 ../tools/extract_quests.py            # quest text from AzerothCore
../.venv/bin/python ../tools/game_voices.py   # voice references from the client
python3 ../tools/plan_v3.py                   # who speaks each line, and in which voice
~/ComfyUI/venv/bin/python ../tools/overnight.py enqueue
~/ComfyUI/venv/bin/python ../tools/overnight.py run --until 09:00 --force
```

`tools/systemd/` runs it nightly. `tools/review_server.py` serves the review page on localhost. `client/build.sh`
builds the engine, patcher and archive tools (MinGW and g++), and `client/build_release.py` builds the release.
`server/` holds the AzerothCore (ALE Lua) side of `/lv bad`.

Many scripts in `tools/` are the experiments described above (bake-offs, grids, children, accents, clone benches).
They are kept as the record of how each choice was made, and some expect files those experiments produced.

---

## Credits

- **Blizzard Entertainment.** The quest text, the characters, the world and every recording the voices are cloned
  from are © Blizzard Entertainment. This is a fan work, not affiliated with, endorsed by or sponsored by Blizzard, and
  not for sale.
- **The fan voice-over projects that came first:**
  - [SpeakStone](https://github.com/dandwhelan) by dandwhelan, [Spoken Quests](https://github.com/rusty-key/spoken-wow)
    by Rusty Key, [VoiceOver](https://github.com/mrthinger/wow-voiceover) by mrthinger, and the carevass packs
    mirrored by [celguar](https://github.com/celguar/wow-voiceover).
  - They showed it could be done; some of our speakers keep the voices players know from them. None of their
    recordings are included.
- **Models:**
  - [IndexTTS-2](https://github.com/index-tts/index-tts) (bilibili)
  - [Qwen3-TTS](https://github.com/QwenLM) (Alibaba Qwen)
  - [Gemma](https://ai.google.dev/gemma) (Google) via [llama.cpp](https://github.com/ggml-org/llama.cpp)
  - [Whisper](https://github.com/openai/whisper) (OpenAI) via [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  - the MMS forced aligner (Meta, via torchaudio)
  - wav2vec2-espeak phoneme recognition
- **Tools:**
  - [ComfyUI](https://github.com/comfyanonymous/ComfyUI) and TTS Audio Suite
  - [miniaudio](https://miniaud.io) (David Reid)
  - [StormLib](https://github.com/ladislav-zezula/StormLib) (Ladislav Zezula)
  - [awesome_wotlk](https://github.com/FrostAtom/awesome_wotlk) (FrostAtom), whose Wow.exe patch the patcher applies
  - Praat (via Parselmouth)
  - [AzerothCore](https://www.azerothcore.org/)
  - Warcraft Wiki's pronunciation guides

## Licence

GPL-3.0 (`LICENSE`). The patcher applies awesome_wotlk's GPL-3.0 patch. StormLib (`client/third_party/StormLib`) is
MIT, and miniaudio is public domain or MIT-0. The licence covers this code only, not the game's text or audio or the
voice pack built from them.
