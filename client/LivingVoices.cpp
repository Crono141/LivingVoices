// LivingVoices -- an audio engine for the World of Warcraft 3.3.5a client (build 12340), for the realm's quest
// voice-over add-on. The stock client can play a sound file but never stop it; this DLL plays voice lines with its own
// streaming audio engine (miniaudio) and lets add-ons stop them at once:
//
//   LivingVoices.Play(path[, volume])  -> true | nil, err   path relative to the WoW folder, inside Interface\AddOns
//   LivingVoices.Stop([fadeMs])                              stops the current line (default 120 ms fade, no click)
//   LivingVoices.SetVolume(v)                                0..1, the add-on passes WoW's own sliders through
//   LivingVoices.IsPlaying()           -> true, position, length | nil
//   LivingVoices.IsForeground()        -> 1 | nil           the WoW window has focus (0.2: the add-on mutes the
//                                                             voice in the background like the game's own sound)
//   LivingVoices.PlaySpliced(path, from1, to1, clip1, ...)    (0.4) the line with each clip in place of take[from:to]
//                                                             (ms): its race/class sentences (lv_splice.h)
//   LivingVoices.Version                                     "0.4"
//
// (0.3, pack 1.1.0) Play() takes a loose file if there is one, else the line from the add-on folder's MPQ archives
// (lv_pack.h, StormLib): read into memory and streamed through miniaudio's decoder.
//
// Loaded by Wow.exe itself (tools/patch_wowexe.py adds it to the client's DLL scan, the awesome_wotlk technique).
// Registration follows awesome_wotlk / WrathClassicAPI: switch off the engine's "Lua C function must live in
// Wow.exe" check, and run our opener at the tail of Lua_OpenFrameXMLApi, which the client calls every time it builds
// the in-game Lua state (login and every /reload) -- before add-ons load, so they see LivingVoices.
//
// Safety first: every byte we change is checked against the stock 12340 client before we touch it; on any mismatch
// nothing is patched and LivingVoices.log (next to Wow.exe) says why. No exceptions, no allocations in the hook.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>

#define MINIAUDIO_IMPLEMENTATION
#define MA_NO_ENCODING
#define MA_NO_GENERATION
#include "third_party/miniaudio.h"
#include "lv_pack.h"
#include "lv_splice.h"

// ---------------------------------------------------------------- Wow.exe 3.3.5a (12340) addresses
// Verified against the realm's shipped Wow.exe (sha1 178f7838...) on 2026-10-11; same as awesome_wotlk/WrathClassicAPI.
struct lua_State;
typedef int(__cdecl *lua_CFunction)(lua_State *);
#define LUA_GLOBALSINDEX (-10002)
#define LUA_TNIL 0
#define LUA_TNUMBER 3

static lua_State *GetLuaState() { return ((lua_State * (__cdecl *)())0x00817DB0)(); }
static void lua_pushcclosure(lua_State *L, lua_CFunction f, int n) { ((void(__cdecl *)(lua_State *, lua_CFunction, int))0x0084E400)(L, f, n); }
static void lua_setfield(lua_State *L, int idx, const char *k) { ((void(__cdecl *)(lua_State *, int, const char *))0x0084E900)(L, idx, k); }
static void lua_createtable(lua_State *L, int a, int r) { ((void(__cdecl *)(lua_State *, int, int))0x0084E6E0)(L, a, r); }
static void lua_pushnumber(lua_State *L, double v) { ((void(__cdecl *)(lua_State *, double))0x0084E2A0)(L, v); }
static void lua_pushstring(lua_State *L, const char *s) { ((void(__cdecl *)(lua_State *, const char *))0x0084E350)(L, s); }
static void lua_pushnil(lua_State *L) { ((void(__cdecl *)(lua_State *))0x0084E280)(L); }
static int lua_gettop(lua_State *L) { return ((int(__cdecl *)(lua_State *))0x0084DBD0)(L); }
static int lua_type(lua_State *L, int i) { return ((int(__cdecl *)(lua_State *, int))0x0084DEB0)(L, i); }
static const char *luaL_checklstring(lua_State *L, int i, size_t *n) { return ((const char *(__cdecl *)(lua_State *, int, size_t *))0x0084F9F0)(L, i, n); }
static double luaL_checknumber(lua_State *L, int i) { return ((double(__cdecl *)(lua_State *, int))0x0084FAB0)(L, i); }

static const DWORD VAR_VALID_FUNCPTR_LO = 0x00D415B8, VAR_VALID_FUNCPTR_HI = 0x00D415BC;
static const DWORD HOOK_LUA_OPEN_FRAMEXML_TAIL = 0x00530F85;              // `ret` + int3 padding in the stock client
static const unsigned char HOOK_EXPECTED[5] = {0xC3, 0xCC, 0xCC, 0xCC, 0xCC};

// ---------------------------------------------------------------- log
static char g_dir[MAX_PATH];                                              // the WoW folder (Wow.exe's), trailing '\'
static void logf(const char *fmt, ...)
{
    char path[MAX_PATH + 32];
    _snprintf(path, sizeof path, "%sLivingVoices.log", g_dir);
    FILE *f = fopen(path, "a");
    if (!f) return;
    SYSTEMTIME t; GetLocalTime(&t);
    fprintf(f, "%04d-%02d-%02d %02d:%02d:%02d ", t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond);
    va_list a; va_start(a, fmt); vfprintf(f, fmt, a); va_end(a);
    fputc('\n', f); fclose(f);
}

// ---------------------------------------------------------------- audio
static ma_engine g_engine;
static bool g_engineOk = false, g_engineTried = false;
static float g_volume = 1.0f;
#define MAX_SOUNDS 4                                                      // the current line + lines still fading out
static ma_sound g_sounds[MAX_SOUNDS];
static bool g_used[MAX_SOUNDS];
static ma_decoder g_dec[MAX_SOUNDS];                                      // a line read from an archive: its decoder,
static void *g_buf[MAX_SOUNDS];                                           // the mp3 in memory (NULL for a loose file)
static double g_len[MAX_SOUNDS];                                          // and its length, worked out before it plays
static ma_audio_buffer g_ab[MAX_SOUNDS];                                  // (0.4) a spliced line: decoded, in memory
static float *g_pcm[MAX_SOUNDS];
static int g_current = -1;

static bool EnsureEngine()
{
    if (g_engineTried) return g_engineOk;
    g_engineTried = true;
    ma_result r = ma_engine_init(NULL, &g_engine);
    g_engineOk = (r == MA_SUCCESS);
    if (g_engineOk) ma_engine_set_volume(&g_engine, g_volume);
    logf("audio engine %s (%d)", g_engineOk ? "started" : "FAILED", (int)r);
    return g_engineOk;
}

static void FreeSlot(int i)                                                // the sound first: it reads the decoder
{
    ma_sound_uninit(&g_sounds[i]);
    if (g_buf[i]) { ma_decoder_uninit(&g_dec[i]); free(g_buf[i]); g_buf[i] = NULL; }
    if (g_pcm[i]) { ma_audio_buffer_uninit(&g_ab[i]); free(g_pcm[i]); g_pcm[i] = NULL; }
    g_used[i] = false;
}

static void Reap()                                                         // free lines that finished or faded out
{
    for (int i = 0; i < MAX_SOUNDS; i++)
        if (g_used[i] && i != g_current && !ma_sound_is_playing(&g_sounds[i])) FreeSlot(i);
    if (g_current >= 0 && !ma_sound_is_playing(&g_sounds[g_current]) && ma_sound_at_end(&g_sounds[g_current])) {
        FreeSlot(g_current); g_current = -1;
    }
}

static void StopCurrent(unsigned fadeMs)
{
    if (g_current < 0) return;
    if (fadeMs) ma_sound_stop_with_fade_in_milliseconds(&g_sounds[g_current], fadeMs);
    else ma_sound_stop(&g_sounds[g_current]);
    g_current = -1;                                                       // reaped once the fade has finished
}

static bool SafeRelative(const char *p)                                    // Interface\AddOns\... only
{
    if (!p || !*p || strstr(p, "..") || strchr(p, ':') || p[0] == '\\' || p[0] == '/') return false;
    return _strnicmp(p, "Interface\\AddOns\\", 17) == 0 || _strnicmp(p, "Interface/AddOns/", 17) == 0;
}

// ---------------------------------------------------------------- archives
// One LvPack per add-on folder, mounted the first time a line is asked for from it (for good: archives do not change
// while the client runs; a new one is found after a restart).
#define MAX_FOLDERS 4
static struct { char folder[64]; LvPack pack; } g_folders[MAX_FOLDERS];
static int g_nFolders = 0;

static int ByName(const void *a, const void *b) { return strcmp((const char *)a, (const char *)b); }

static LvPack *PackFor(const char *folder)
{
    for (int i = 0; i < g_nFolders; i++) if (!_stricmp(g_folders[i].folder, folder)) return &g_folders[i].pack;
    if (g_nFolders >= MAX_FOLDERS || strlen(folder) >= sizeof g_folders[0].folder) return NULL;
    LvPack *p = &g_folders[g_nFolders].pack;
    strcpy(g_folders[g_nFolders++].folder, folder);
    p->n = 0;
    char pattern[MAX_PATH * 2];
    _snprintf(pattern, sizeof pattern, "%sInterface\\AddOns\\%s\\*.MPQ", g_dir, folder);
    static char names[LV_MAX_ARCHIVES][MAX_PATH];
    int n = 0;
    WIN32_FIND_DATAA fd;
    HANDLE fh = FindFirstFileA(pattern, &fd);
    if (fh != INVALID_HANDLE_VALUE) {
        do if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && n < LV_MAX_ARCHIVES) strcpy(names[n++], fd.cFileName);
        while (FindNextFileA(fh, &fd));
        FindClose(fh);
    }
    qsort(names, n, sizeof names[0], ByName);
    for (int i = 0; i < n; i++) {
        char path[MAX_PATH * 2];
        _snprintf(path, sizeof path, "%sInterface\\AddOns\\%s\\%s", g_dir, folder, names[i]);
        bool ok = LvPackMount(p, path);
        logf("archive %s\\%s %s", folder, names[i], ok ? "mounted" : "NOT mounted (not an MPQ, or unreadable)");
    }
    if (!n) logf("no archives in Interface\\AddOns\\%s", folder);
    return p;
}

// the line from an archive into slot `slot`: false (and nothing held) if no archive has it or it does not decode
static bool OpenFromPack(const char *rel, int slot, const char **err)
{
    const char *folder = rel + 17, *slash = strpbrk(folder, "\\/");     // Interface\AddOns\<folder>\<inner>
    char name[64], inner[MAX_PATH];
    if (!slash || slash - folder >= (int)sizeof name) { *err = "cannot open file"; return false; }
    memcpy(name, folder, slash - folder); name[slash - folder] = 0;
    _snprintf(inner, sizeof inner, "%s", slash + 1);
    for (char *c = inner; *c; c++) if (*c == '/') *c = '\\';
    LvPack *p = PackFor(name);
    size_t size = 0;
    void *buf = p ? LvPackRead(p, inner, &size) : NULL;
    if (!buf) { *err = "cannot open file (not on disk or in the add-on's archives)"; return false; }
    ma_decoder_config dc = ma_decoder_config_init(ma_format_f32, 0, 0);
    if (ma_decoder_init_memory(buf, size, &dc, &g_dec[slot]) != MA_SUCCESS) { free(buf); *err = "cannot decode the line"; return false; }
    ma_uint64 frames = 0;
    ma_decoder_get_length_in_pcm_frames(&g_dec[slot], &frames);           // before the audio thread reads it
    g_len[slot] = g_dec[slot].outputSampleRate ? (double)frames / g_dec[slot].outputSampleRate : 0;
    if (ma_sound_init_from_data_source(&g_engine, &g_dec[slot], MA_SOUND_FLAG_NO_SPATIALIZATION, NULL, &g_sounds[slot]) != MA_SUCCESS) {
        ma_decoder_uninit(&g_dec[slot]); free(buf); *err = "cannot play the line"; return false;
    }
    g_buf[slot] = buf;
    return true;
}

// a whole file (loose first, else the add-on folder's archives) in a malloc'd buffer; NULL if neither has it
static void *ReadWhole(const char *rel, size_t *size)
{
    char path[MAX_PATH * 2];
    _snprintf(path, sizeof path, "%s%s", g_dir, rel);
    for (char *c = path; *c; c++) if (*c == '/') *c = '\\';
    FILE *f = fopen(path, "rb");
    if (f) {
        fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
        void *b = n > 0 ? malloc(n) : NULL;
        bool ok = b && fread(b, 1, n, f) == (size_t)n;
        fclose(f);
        if (ok) { *size = n; return b; }
        free(b);
    }
    const char *folder = rel + 17, *slash = strpbrk(folder, "\\/");
    char name[64], inner[MAX_PATH];
    if (!slash || slash - folder >= (int)sizeof name) return NULL;
    memcpy(name, folder, slash - folder); name[slash - folder] = 0;
    _snprintf(inner, sizeof inner, "%s", slash + 1);
    for (char *c = inner; *c; c++) if (*c == '/') *c = '\\';
    LvPack *p = PackFor(name);
    return p ? LvPackRead(p, inner, size) : NULL;
}

static float *DecodeFile(const char *rel, ma_uint64 *frames)
{
    size_t size = 0;
    void *b = SafeRelative(rel) ? ReadWhole(rel, &size) : NULL;
    if (!b) return NULL;
    float *pcm = LvDecodeAll(b, size, frames);
    free(b);
    return pcm;
}

// ---------------------------------------------------------------- Lua functions
static int __cdecl L_PlaySpliced(lua_State *L);

static int __cdecl L_Play(lua_State *L)
{
    const char *rel = luaL_checklstring(L, 1, NULL);
    if (!SafeRelative(rel)) { lua_pushnil(L); lua_pushstring(L, "path must be inside Interface\\AddOns\\"); return 2; }
    if (!EnsureEngine()) { lua_pushnil(L); lua_pushstring(L, "audio engine failed to start"); return 2; }
    Reap();
    StopCurrent(60);
    int slot = -1;
    for (int i = 0; i < MAX_SOUNDS; i++) if (!g_used[i]) { slot = i; break; }
    if (slot < 0) {                                                       // all busy fading: drop the oldest at once
        for (int i = 0; i < MAX_SOUNDS; i++) FreeSlot(i);
        slot = 0;
    }
    char path[MAX_PATH * 2];
    _snprintf(path, sizeof path, "%s%s", g_dir, rel);
    for (char *c = path; *c; c++) if (*c == '/') *c = '\\';
    if (GetFileAttributesA(path) != INVALID_FILE_ATTRIBUTES) {            // a loose file wins over the archives
        ma_result r = ma_sound_init_from_file(&g_engine, path, MA_SOUND_FLAG_STREAM | MA_SOUND_FLAG_NO_SPATIALIZATION, NULL, NULL, &g_sounds[slot]);
        if (r != MA_SUCCESS) { lua_pushnil(L); lua_pushstring(L, "cannot open file"); return 2; }
    } else {
        const char *err = NULL;
        if (!OpenFromPack(rel, slot, &err)) { lua_pushnil(L); lua_pushstring(L, err); return 2; }
    }
    g_used[slot] = true;
    if (lua_gettop(L) >= 2 && lua_type(L, 2) == LUA_TNUMBER) ma_sound_set_volume(&g_sounds[slot], (float)luaL_checknumber(L, 2));
    ma_sound_start(&g_sounds[slot]);
    g_current = slot;
    lua_pushnumber(L, 1);
    return 1;
}

// (0.4) PlaySpliced(path, from1, to1, clip1, from2, to2, clip2, ...): the take and each clip decoded whole, the clips
// put in place of take[from:to] (ms), played from memory. A clip that cannot be read leaves its sentence as it was;
// a take that cannot be read is an error, as in Play. Flat arguments: the engine has no Lua table access bound.
#define MAX_PIECES 8
static int __cdecl L_PlaySpliced(lua_State *L)
{
    const char *rel = luaL_checklstring(L, 1, NULL);
    if (!SafeRelative(rel)) { lua_pushnil(L); lua_pushstring(L, "path must be inside Interface\\AddOns\\"); return 2; }
    if (!EnsureEngine()) { lua_pushnil(L); lua_pushstring(L, "audio engine failed to start"); return 2; }
    ma_uint64 n = 0;
    float *take = DecodeFile(rel, &n);
    if (!take) { lua_pushnil(L); lua_pushstring(L, "cannot open file (not on disk or in the add-on's archives)"); return 2; }
    LvPiece pieces[MAX_PIECES]; float *clips[MAX_PIECES]; int np = 0;
    int top = lua_gettop(L);
    for (int a = 2; a + 2 <= top && np < MAX_PIECES; a += 3) {
        if (lua_type(L, a) != LUA_TNUMBER || lua_type(L, a + 1) != LUA_TNUMBER) break;
        double f = luaL_checknumber(L, a), t = luaL_checknumber(L, a + 1);
        const char *crel = luaL_checklstring(L, a + 2, NULL);
        ma_uint64 cn = 0;
        float *clip = DecodeFile(crel, &cn);
        if (!clip || f < 0 || t < f) { free(clip); continue; }
        clips[np] = clip;
        pieces[np].from = (ma_uint64)(f * LV_RATE / 1000.0); pieces[np].to = (ma_uint64)(t * LV_RATE / 1000.0);
        if (pieces[np].to > n) pieces[np].to = n;
        if (pieces[np].from > pieces[np].to) pieces[np].from = pieces[np].to;
        pieces[np].clip = clip; pieces[np].clipN = cn; np++;
    }
    ma_uint64 outN = 0;
    float *pcm = LvSplice(take, n, pieces, np, &outN);
    free(take);
    for (int i = 0; i < np; i++) free(clips[i]);
    if (!pcm) { lua_pushnil(L); lua_pushstring(L, "out of memory"); return 2; }
    Reap();
    StopCurrent(60);
    int slot = -1;
    for (int i = 0; i < MAX_SOUNDS; i++) if (!g_used[i]) { slot = i; break; }
    if (slot < 0) { for (int i = 0; i < MAX_SOUNDS; i++) FreeSlot(i); slot = 0; }
    ma_audio_buffer_config bc = ma_audio_buffer_config_init(ma_format_f32, 1, outN, pcm, NULL);
    bc.sampleRate = LV_RATE;
    if (ma_audio_buffer_init(&bc, &g_ab[slot]) != MA_SUCCESS) { free(pcm); lua_pushnil(L); lua_pushstring(L, "cannot play the line"); return 2; }
    if (ma_sound_init_from_data_source(&g_engine, &g_ab[slot], MA_SOUND_FLAG_NO_SPATIALIZATION, NULL, &g_sounds[slot]) != MA_SUCCESS) {
        ma_audio_buffer_uninit(&g_ab[slot]); free(pcm); lua_pushnil(L); lua_pushstring(L, "cannot play the line"); return 2;
    }
    g_pcm[slot] = pcm; g_len[slot] = (double)outN / LV_RATE;
    g_used[slot] = true;
    ma_sound_start(&g_sounds[slot]);
    g_current = slot;
    lua_pushnumber(L, np);                                                // how many sentences went in
    return 1;
}

static int __cdecl L_Stop(lua_State *L)
{
    unsigned fade = 120;
    if (lua_gettop(L) >= 1 && lua_type(L, 1) == LUA_TNUMBER) { double v = luaL_checknumber(L, 1); fade = v < 0 ? 0 : (unsigned)v; }
    if (g_engineOk) { StopCurrent(fade); Reap(); }
    return 0;
}

static int __cdecl L_SetVolume(lua_State *L)
{
    double v = luaL_checknumber(L, 1);
    g_volume = (float)(v < 0 ? 0 : v > 1 ? 1 : v);
    if (g_engineOk) ma_engine_set_volume(&g_engine, g_volume);
    return 0;
}

static int __cdecl L_IsPlaying(lua_State *L)
{
    if (!g_engineOk || g_current < 0) { lua_pushnil(L); return 1; }
    Reap();
    if (g_current < 0) { lua_pushnil(L); return 1; }
    float pos = 0, len = 0;
    if (g_buf[g_current] || g_pcm[g_current]) {     // from memory: its data belongs to the audio thread now
        pos = (float)((double)ma_sound_get_time_in_pcm_frames(&g_sounds[g_current]) / ma_engine_get_sample_rate(&g_engine));
        len = (float)g_len[g_current];
    } else {
        ma_sound_get_cursor_in_seconds(&g_sounds[g_current], &pos);
        ma_sound_get_length_in_seconds(&g_sounds[g_current], &len);
    }
    lua_pushnumber(L, 1); lua_pushnumber(L, pos); lua_pushnumber(L, len);
    return 3;
}

static int __cdecl L_IsForeground(lua_State *L)
{
    DWORD pid = 0;
    HWND w = GetForegroundWindow();
    if (w) GetWindowThreadProcessId(w, &pid);
    if (pid == GetCurrentProcessId()) lua_pushnumber(L, 1); else lua_pushnil(L);   // no pushboolean bound: 1 | nil
    return 1;
}

// ---------------------------------------------------------------- registration
extern "C" void __cdecl LivingVoices_OpenLib()
{
    lua_State *L = GetLuaState();
    if (!L) return;
    lua_createtable(L, 0, 8);
    lua_pushcclosure(L, L_Play, 0);      lua_setfield(L, -2, "Play");
    lua_pushcclosure(L, L_PlaySpliced, 0); lua_setfield(L, -2, "PlaySpliced");
    lua_pushcclosure(L, L_Stop, 0);      lua_setfield(L, -2, "Stop");
    lua_pushcclosure(L, L_SetVolume, 0); lua_setfield(L, -2, "SetVolume");
    lua_pushcclosure(L, L_IsPlaying, 0); lua_setfield(L, -2, "IsPlaying");
    lua_pushcclosure(L, L_IsForeground, 0); lua_setfield(L, -2, "IsForeground");
    lua_pushstring(L, "0.4");            lua_setfield(L, -2, "Version");
    lua_setfield(L, LUA_GLOBALSINDEX, "LivingVoices");
    if (g_engineOk) StopCurrent(0);                                       // a /reload cuts any line still playing
}

// Replaces the `ret` at the end of Lua_OpenFrameXMLApi: keep every register, open our library, return as before.
extern "C" __attribute__((naked)) void LivingVoices_Hook()
{
    __asm__ volatile(
        "pushal\n\t"
        "pushfl\n\t"
        "call _LivingVoices_OpenLib\n\t"
        "popfl\n\t"
        "popal\n\t"
        "ret\n\t");
}

static bool Install()
{
    unsigned char *site = (unsigned char *)HOOK_LUA_OPEN_FRAMEXML_TAIL;
    if (memcmp(site, HOOK_EXPECTED, sizeof HOOK_EXPECTED) != 0) {
        logf("NOT installed: unexpected bytes at %08lx (%02x %02x %02x %02x %02x) -- not the stock 3.3.5a 12340 client, "
             "or another DLL hooks the same place", HOOK_LUA_OPEN_FRAMEXML_TAIL, site[0], site[1], site[2], site[3], site[4]);
        return false;
    }
    DWORD old;
    // the engine only accepts Lua C functions inside Wow.exe's .text; widen the range so ours are accepted
    if (!VirtualProtect((void *)VAR_VALID_FUNCPTR_LO, 8, PAGE_READWRITE, &old)) { logf("NOT installed: VirtualProtect (range) failed"); return false; }
    *(DWORD *)VAR_VALID_FUNCPTR_LO = 1;
    *(DWORD *)VAR_VALID_FUNCPTR_HI = 0x7FFFFFFF;
    VirtualProtect((void *)VAR_VALID_FUNCPTR_LO, 8, old, &old);
    if (!VirtualProtect(site, 5, PAGE_EXECUTE_READWRITE, &old)) { logf("NOT installed: VirtualProtect (hook) failed"); return false; }
    site[0] = 0xE9;
    *(DWORD *)(site + 1) = (DWORD)(void *)&LivingVoices_Hook - (HOOK_LUA_OPEN_FRAMEXML_TAIL + 5);
    VirtualProtect(site, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), site, 5);
    logf("installed (LivingVoices 0.4, miniaudio %s, StormLib %s)", MA_VERSION_STRING, STORMLIB_VERSION_STRING);
    return true;
}

extern "C" BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH) {
        GetModuleFileNameA(NULL, g_dir, MAX_PATH);
        char *slash = strrchr(g_dir, '\\');
        if (slash) slash[1] = 0; else g_dir[0] = 0;
        Install();
    }
    return TRUE;                                                          // no teardown: the client exits with the process
}
