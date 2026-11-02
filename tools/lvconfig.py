"""Where this machine keeps things: paths, servers, the realm's database login. Every tool reads them from here.

The values come from config.local.json at the repository root (untracked: it describes one machine), over the
defaults in config.example.json, which documents each setting. Copy the example and edit it:

    cp config.example.json config.local.json

A setting can also be given in the environment as LV_<NAME> (LV_DB_CNF=~/.my.cnf), which wins over both files.
Paths may start with ~.
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _load():
    cfg = {}
    for name in ('config.example.json', 'config.local.json'):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            cfg.update({k: v for k, v in json.load(open(p)).items() if not k.startswith('_')})
    for k in list(cfg):
        if f'LV_{k.upper()}' in os.environ:
            v = os.environ[f'LV_{k.upper()}']
            cfg[k] = json.loads(v) if isinstance(cfg[k], (dict, list)) else v
    return cfg

CFG = _load()

def _path(k):
    v = CFG.get(k) or ''
    return os.path.expanduser(v) if isinstance(v, str) else v

AC_SQL = _path('azerothcore_sql')          # AzerothCore's base world SQL (data/sql/base/db_world)
DB_CNF = _path('db_reader_cnf')            # a MariaDB/MySQL defaults file for a read-only realm login
WOW_DATA = _path('wow_client_data')        # the 3.3.5a client's Data folder (MPQs: voice clips, sounds)
WAR3_ARCHIVE = _path('war3_archive')       # Warcraft III's War3.mpq (some characters' own voices)
OUTPUTS = _path('comfy_output_dir')        # the output folder of the ComfyUI on card 0 (its --output-directory)
COMFY_SUBDIR = CFG.get('comfy_subdir', 'audio/wow_voices')   # this pipeline's folder inside it
COMFY_OUT = os.path.join(OUTPUTS, COMFY_SUBDIR) if OUTPUTS else ''
COMFYUI = _path('comfyui_dir')             # a ComfyUI install with TTS Audio Suite (comfy2.sh runs instances of it)
MODELS = _path('models_dir')               # model folder (ASR, TTS, classifiers)
CORPORA = _path('voice_corpora')           # speech corpora used in experiments (children's voices)
SCRATCH = _path('scratch_dir')             # throwaway space for experiments
SHARE = _path('share_dir')                 # where finished release zips are published (a file share)
PORTAL_WEB = _path('portal_web')           # the realm website's folder (help page)
RENDERERS = CFG.get('renderers', {})       # card -> ComfyUI URL: '0', '1', '0b'
OWN_RENDERERS = CFG.get('own_renderers', {})   # card -> tools/comfy2.sh instance this pipeline starts and stops
LLM_URL = CFG.get('llm_url', '')           # an OpenAI-compatible chat server (the director and judge)
LLM_MODEL = CFG.get('llm_model', '')
LLM_PINNED = tuple(CFG.get('llm_pinned', ()))  # models never unloaded before the speech check
JUDGE_URL = CFG.get('judge_url') or LLM_URL    # experiments: a second LLM server
