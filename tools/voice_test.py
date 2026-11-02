import json, re, sys, time, urllib.request
import lvconfig as LV
URL = LV.RENDERERS['1']
q = json.load(open(sys.argv[1]))

def clean(t):
    t = re.sub(r'\$[bB]', '\n', t)
    t = re.sub(r'\$[nN]', 'adventurer', t)
    t = re.sub(r'\$[cC]', 'adventurer', t)
    t = re.sub(r'\$[rR]', 'traveler', t)
    t = re.sub(r'\$[gG]([^:;]*):([^;]*);', r'\1', t)
    t = re.sub(r'<[^>]*>', '', t)
    return re.sub(r'\n\s*\n+', '\n', t).strip()

cast = [
  ("human_marshal", "783", "A middle-aged human soldier, a marshal of the realm. Firm, commanding baritone with a steady, measured "
   "delivery and a trace of weariness. Plain English accent, speaks to a new recruit."),
  ("dwarf_outfitter", "179", "An older dwarf, a hearty mountain trader. Deep, gravelly bass with a thick Scottish brogue, warm and "
   "gruff, a little teasing, chuckles easily."),
  ("nightelf_conservator", "456", "An ancient night elf, calm and serene. Soft, low, airy male voice, slow and graceful phrasing, "
   "speaks with quiet wisdom as if the forest were listening."),
  ("forsaken_undertaker", "363", "An undead man, a gravekeeper of a crypt. Dry, raspy, hollow voice with a faint rattle; slow, "
   "sardonic and darkly amused, but not unkind."),
]

def post(path, body):
    r = urllib.request.Request(URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=60))

def wait(pid):
    t0 = time.time()
    while True:
        h = json.load(urllib.request.urlopen(f"{URL}/history/{pid}", timeout=30))
        if pid in h:
            st = h[pid].get("status", {})
            return h[pid], time.time() - t0, st.get("status_str"), st.get("messages")
        time.sleep(2)

if len(sys.argv) > 2:
    cast = json.load(open(sys.argv[2]))
SUB = sys.argv[3] if len(sys.argv) > 3 else 'voice_test'
for name, qid, desc in cast:
    text = clean(q[qid]["desc"])
    wf = {
      "1": {"class_type": "Qwen3TTSEngineNode", "inputs": {"model_size": "1.7B", "device": "cuda",
            "voice_preset": "None (Zero-shot / Custom)", "language": "English", "instruct": "", "top_k": 50,
            "top_p": 1.0, "temperature": 0.9, "repetition_penalty": 1.05, "max_new_tokens": 4096}},
      "2": {"class_type": "Qwen3TTSVoiceDesignerNode", "inputs": {"TTS_engine": ["1", 0], "voice_description": desc,
            "reference_text": text, "language": "English", "character_name": "wow_" + name, "overwrite_character": True}},
      "3": {"class_type": "SaveAudioMP3", "inputs": {"audio": ["2", 1], "filename_prefix": f"{SUB}/{name}", "quality": "V0"}},
    }
    pid = post("/prompt", {"prompt": wf})["prompt_id"]
    h, secs, status, msgs = wait(pid)
    files = [f["filename"] for o in h.get("outputs", {}).values() for f in o.get("audio", [])]
    err = [m for m in (msgs or []) if m[0] == "execution_error"]
    print(f"{name}: {status} in {secs:.0f}s, words {len(text.split())}, files {files}", flush=True)
    if err:
        print("   ERROR", json.dumps(err[0][1])[:600], flush=True)
