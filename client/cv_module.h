// Companion Voice engine module (0.1), a separate module inside LivingVoices.dll for the CompanionVoice add-on (its
// own repo, ~/Projects/CompanionVoice). Living Voices does not use it, and it uses nothing of the quest voice-over
// but the DLL's audio engine and path check. The speech model runs in cvoice.exe, a 64-bit helper process (the
// 32-bit game cannot hold the model, and its CPU time would cost frames). This module starts the helper, sends it
// lines over a pipe, and streams the audio it sends back through miniaudio.
//
//   CompanionVoiceEngine.Speak(ref, text[, volume[, speed]]) -> id | nil, err
//                                           ref: a reference clip inside Interface\AddOns; speed 0.5-2.0 (1 = as designed)
//   CompanionVoiceEngine.Stop([fadeMs])                                 cut the current line (and cancel its generation)
//   CompanionVoiceEngine.IsSpeaking()       -> id | nil                 the line still generating or playing
//   CompanionVoiceEngine.SetVolume(v)                                   0..1, its own volume, apart from Living Voices
//   CompanionVoiceEngine.Status()           -> "off"|"starting"|"ready"|"failed"[, why]
//   CompanionVoiceEngine.Version                                        "0.1"
//
// The helper lives in Interface\AddOns\CompanionVoice\engine\ (cvoice.exe, its DLLs, model\). It starts on the first
// Speak, keeps its model loaded across /reload, and exits when the game closes its stdin, or with the game through
// a kill-on-close job object if the game crashes. Protocol: CompanionVoice DESIGN.md.
//
// Included by LivingVoices.cpp after its audio and path helpers (g_engine, EnsureEngine, SafeRelative, logf, g_dir).

#define CV_RATE 24000
#define CV_SLOTS 3                                                        // the current line + lines fading out
#define CV_MAX_STARTS 3                                                   // helper (re)starts per game session

typedef struct {
    ma_data_source_base base;                                             // first: miniaudio reads it as the source
    float *pcm;                                                           // the line's audio so far (24 kHz mono)
    ma_uint64 n, cap, pos;
    int ended;                                                            // the helper sent E (or stopped): no more audio
    unsigned id;
} CvStream;

static struct { bool used; CvStream s; ma_sound snd; } g_cv[CV_SLOTS];
static int g_cvCur = -1;
static CRITICAL_SECTION g_cvLock;                                         // the streams (pcm, n, pos, ended)
static bool g_cvLockInit = false;
static volatile LONG g_cvState = 0;                                       // 0 off, 1 starting, 2 ready, 3 failed
static char g_cvWhy[256];
static int g_cvStarts = 0;
static unsigned g_cvNextId = 1;
static float g_cvVolume = 1.0f;
static HANDLE g_cvIn = NULL;                                              // our write end of the helper's stdin
static HANDLE g_cvOut = NULL;                                             // our read end of its stdout
static HANDLE g_cvJob = NULL;
static char g_cvDirUtf8[MAX_PATH * 3];                                    // the WoW folder in UTF-8, trailing '\'

// ---------------------------------------------------------------- the streamed line as a miniaudio data source
static ma_result CvRead(ma_data_source *ds, void *out, ma_uint64 count, ma_uint64 *read)
{
    CvStream *s = (CvStream *)ds;
    float *o = (float *)out;
    EnterCriticalSection(&g_cvLock);
    ma_uint64 avail = s->n - s->pos, k = avail < count ? avail : count;
    if (k) memcpy(o, s->pcm + s->pos, (size_t)k * sizeof(float));
    s->pos += k;
    int ended = s->ended;
    LeaveCriticalSection(&g_cvLock);
    if (k < count && !ended) {                                            // still generating: silence until more comes
        memset(o + k, 0, (size_t)(count - k) * sizeof(float));
        *read = count;
        return MA_SUCCESS;
    }
    *read = k;
    return k ? MA_SUCCESS : MA_AT_END;
}
static ma_result CvSeek(ma_data_source *, ma_uint64) { return MA_NOT_IMPLEMENTED; }
static ma_result CvFormat(ma_data_source *, ma_format *f, ma_uint32 *ch, ma_uint32 *rate, ma_channel *map, size_t cap)
{
    *f = ma_format_f32; *ch = 1; *rate = CV_RATE;
    if (map) ma_channel_map_init_standard(ma_standard_channel_map_default, map, cap, 1);
    return MA_SUCCESS;
}
static ma_result CvCursor(ma_data_source *, ma_uint64 *c) { *c = 0; return MA_NOT_IMPLEMENTED; }
static ma_result CvLength(ma_data_source *, ma_uint64 *l) { *l = 0; return MA_NOT_IMPLEMENTED; }
static ma_data_source_vtable g_cvVtable = {CvRead, CvSeek, CvFormat, CvCursor, CvLength, NULL, 0};

static CvStream *CvFind(unsigned id)                                      // under g_cvLock
{
    for (int i = 0; i < CV_SLOTS; i++) if (g_cv[i].used && g_cv[i].s.id == id) return &g_cv[i].s;
    return NULL;
}

static void CvAppend(CvStream *s, const short *v, ma_uint64 k)            // under g_cvLock
{
    if (s->n + k > s->cap) {
        ma_uint64 cap = s->cap ? s->cap : CV_RATE * 8;
        while (cap < s->n + k) cap *= 2;
        float *p = (float *)realloc(s->pcm, (size_t)cap * sizeof(float));
        if (!p) { s->ended = 1; return; }                                 // out of memory: end the line here
        s->pcm = p; s->cap = cap;
    }
    for (ma_uint64 i = 0; i < k; i++) s->pcm[s->n + i] = v[i] / 32768.0f;
    s->n += k;
}

// ---------------------------------------------------------------- the helper process
static bool CvReadAll(void *buf, DWORD n)
{
    char *p = (char *)buf;
    while (n) {
        DWORD got = 0;
        if (!ReadFile(g_cvOut, p, n, &got, NULL) || !got) return false;
        p += got; n -= got;
    }
    return true;
}

static DWORD WINAPI CvReader(LPVOID)
{
    static char payload[1 << 20];
    for (;;) {
        unsigned char h[9];
        if (!CvReadAll(h, 9)) break;
        unsigned id, len;
        memcpy(&id, h + 1, 4); memcpy(&len, h + 5, 4);
        if (len > sizeof payload) { logf("companion voice: frame too long (%u bytes), engine stopped", len); break; }
        if (len && !CvReadAll(payload, len)) break;
        if (h[0] == 'R') {
            payload[len < 64 ? len : 63] = 0;
            logf("companion voice: engine ready (%s)", payload);
            InterlockedExchange(&g_cvState, 2);
        } else if (h[0] == 'A') {
            EnterCriticalSection(&g_cvLock);
            CvStream *s = CvFind(id);
            if (s && !s->ended) CvAppend(s, (const short *)payload, len / 2);
            LeaveCriticalSection(&g_cvLock);
        } else if (h[0] == 'E') {
            EnterCriticalSection(&g_cvLock);
            CvStream *s = CvFind(id);
            if (s) s->ended = 1;
            LeaveCriticalSection(&g_cvLock);
        } else if (h[0] == 'X') {
            payload[len < sizeof payload ? len : sizeof payload - 1] = 0;
            logf("companion voice: line %u: %s", id, payload);
        }
    }
    // the helper exited or broke the protocol: end every line, and let the next Speak restart it (up to CV_MAX_STARTS)
    EnterCriticalSection(&g_cvLock);
    for (int i = 0; i < CV_SLOTS; i++) if (g_cv[i].used) g_cv[i].s.ended = 1;
    LeaveCriticalSection(&g_cvLock);
    _snprintf(g_cvWhy, sizeof g_cvWhy, "the speech engine stopped (see CompanionVoice.log)");
    logf("companion voice: engine stopped");
    InterlockedExchange(&g_cvState, 3);
    return 0;
}

static bool CvStart()
{
    if (g_cvStarts >= CV_MAX_STARTS) return false;
    g_cvStarts++;
    if (g_cvIn) { CloseHandle(g_cvIn); g_cvIn = NULL; }                   // a previous helper's pipes
    if (g_cvOut) { CloseHandle(g_cvOut); g_cvOut = NULL; }
    wchar_t dir[MAX_PATH], exe[MAX_PATH + 64], model[MAX_PATH + 64], engine[MAX_PATH + 64], log[MAX_PATH + 32];
    wchar_t cmd[3 * MAX_PATH + 128];
    GetModuleFileNameW(NULL, dir, MAX_PATH);
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) slash[1] = 0; else dir[0] = 0;
    _snwprintf(engine, MAX_PATH + 64, L"%lsInterface\\AddOns\\CompanionVoice\\engine", dir);
    _snwprintf(exe, MAX_PATH + 64, L"%ls\\cvoice.exe", engine);
    _snwprintf(model, MAX_PATH + 64, L"%ls\\model", engine);
    _snwprintf(log, MAX_PATH + 32, L"%lsCompanionVoice.log", dir);
    WideCharToMultiByte(CP_UTF8, 0, dir, -1, g_cvDirUtf8, sizeof g_cvDirUtf8, NULL, NULL);
    if (GetFileAttributesW(exe) == INVALID_FILE_ATTRIBUTES) {
        g_cvStarts = CV_MAX_STARTS;                                       // not installed: do not look again
        _snprintf(g_cvWhy, sizeof g_cvWhy, "the speech engine is not installed (AddOns\\CompanionVoice\\engine)");
        return false;
    }
    SECURITY_ATTRIBUTES sa = {sizeof sa, NULL, TRUE};
    HANDLE inRd = NULL, outWr = NULL;
    if (!CreatePipe(&inRd, &g_cvIn, &sa, 0) || !CreatePipe(&g_cvOut, &outWr, &sa, 1 << 16)) {
        _snprintf(g_cvWhy, sizeof g_cvWhy, "cannot create pipes (%lu)", GetLastError()); return false;
    }
    SetHandleInformation(g_cvIn, HANDLE_FLAG_INHERIT, 0);                 // our ends stay ours
    SetHandleInformation(g_cvOut, HANDLE_FLAG_INHERIT, 0);
    HANDLE err = CreateFileW(log, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    STARTUPINFOW si; memset(&si, 0, sizeof si); si.cb = sizeof si;
    si.dwFlags = STARTF_USESTDHANDLES; si.hStdInput = inRd; si.hStdOutput = outWr;
    si.hStdError = err != INVALID_HANDLE_VALUE ? err : NULL;
    PROCESS_INFORMATION pi;
    _snwprintf(cmd, sizeof cmd / sizeof cmd[0], L"\"%ls\" --model \"%ls\" --threads 2", exe, model);
    BOOL ok = CreateProcessW(exe, cmd, NULL, NULL, TRUE, CREATE_NO_WINDOW | CREATE_SUSPENDED | BELOW_NORMAL_PRIORITY_CLASS,
                             NULL, engine, &si, &pi);
    CloseHandle(inRd); CloseHandle(outWr);                                // the helper holds its ends now
    if (err != INVALID_HANDLE_VALUE) CloseHandle(err);
    if (!ok) { _snprintf(g_cvWhy, sizeof g_cvWhy, "cannot start the speech engine (%lu)", GetLastError()); return false; }
    if (!g_cvJob) {                                                       // the helper dies with the game, even on a crash
        g_cvJob = CreateJobObjectW(NULL, NULL);
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION li; memset(&li, 0, sizeof li);
        li.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (g_cvJob) SetInformationJobObject(g_cvJob, JobObjectExtendedLimitInformation, &li, sizeof li);
    }
    if (g_cvJob && !AssignProcessToJobObject(g_cvJob, pi.hProcess)) logf("companion voice: no job object (%lu); the engine exits when the game closes its pipe", GetLastError());
    ResumeThread(pi.hThread);
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    InterlockedExchange(&g_cvState, 1);
    HANDLE t = CreateThread(NULL, 0, CvReader, NULL, 0, NULL);
    if (t) CloseHandle(t);
    logf("companion voice: engine starting (try %d)", g_cvStarts);
    return true;
}

static bool CvSend(const char *line)
{
    DWORD n = (DWORD)strlen(line), wrote = 0;
    return g_cvIn && WriteFile(g_cvIn, line, n, &wrote, NULL) && wrote == n;
}

// ---------------------------------------------------------------- slots
static void CvFree(int i)                                                 // main thread; the sound first
{
    ma_sound_uninit(&g_cv[i].snd);
    ma_data_source_uninit(&g_cv[i].s);
    EnterCriticalSection(&g_cvLock);
    float *p = g_cv[i].s.pcm;
    g_cv[i].s.pcm = NULL; g_cv[i].used = false;
    LeaveCriticalSection(&g_cvLock);
    free(p);
}

static void CvReap()
{
    for (int i = 0; i < CV_SLOTS; i++)
        if (g_cv[i].used && i != g_cvCur && !ma_sound_is_playing(&g_cv[i].snd)) CvFree(i);
    if (g_cvCur >= 0 && ma_sound_at_end(&g_cv[g_cvCur].snd)) { CvFree(g_cvCur); g_cvCur = -1; }
}

static void CvStopCurrent(unsigned fadeMs)
{
    if (g_cvCur < 0) return;
    char line[32];
    _snprintf(line, sizeof line, "CANCEL\t%u\n", g_cv[g_cvCur].s.id);
    CvSend(line);
    EnterCriticalSection(&g_cvLock);
    g_cv[g_cvCur].s.ended = 1;                                            // no more audio for it
    LeaveCriticalSection(&g_cvLock);
    if (fadeMs) ma_sound_stop_with_fade_in_milliseconds(&g_cv[g_cvCur].snd, fadeMs);
    else ma_sound_stop(&g_cv[g_cvCur].snd);
    g_cvCur = -1;                                                         // reaped once the fade has finished
}

// ---------------------------------------------------------------- Lua functions
static int __cdecl CV_Speak(lua_State *L)
{
    const char *rel = luaL_checklstring(L, 1, NULL);
    size_t tn = 0;
    const char *text = luaL_checklstring(L, 2, &tn);
    if (!SafeRelative(rel)) { lua_pushnil(L); lua_pushstring(L, "reference must be inside Interface\\AddOns\\"); return 2; }
    if (!tn) { lua_pushnil(L); lua_pushstring(L, "no text"); return 2; }
    if (!EnsureEngine()) { lua_pushnil(L); lua_pushstring(L, "audio engine failed to start"); return 2; }
    if (g_cvState == 0 || g_cvState == 3) {
        if (!CvStart()) {
            InterlockedExchange(&g_cvState, 3);
            if (!g_cvWhy[0]) _snprintf(g_cvWhy, sizeof g_cvWhy, "the speech engine failed %d times this session", CV_MAX_STARTS);
            lua_pushnil(L); lua_pushstring(L, g_cvWhy); return 2;
        }
    }
    CvReap();
    CvStopCurrent(80);
    int slot = -1;
    for (int i = 0; i < CV_SLOTS; i++) if (!g_cv[i].used) { slot = i; break; }
    if (slot < 0) { for (int i = 0; i < CV_SLOTS; i++) if (g_cv[i].used) CvFree(i); slot = 0; }
    CvStream *s = &g_cv[slot].s;
    memset(s, 0, sizeof *s);
    ma_data_source_config dc = ma_data_source_config_init();
    dc.vtable = &g_cvVtable;
    if (ma_data_source_init(&dc, s) != MA_SUCCESS) { lua_pushnil(L); lua_pushstring(L, "cannot set up the voice stream"); return 2; }
    s->id = g_cvNextId++;
    if (ma_sound_init_from_data_source(&g_engine, s, MA_SOUND_FLAG_NO_SPATIALIZATION, NULL, &g_cv[slot].snd) != MA_SUCCESS) {
        ma_data_source_uninit(s); lua_pushnil(L); lua_pushstring(L, "cannot play the voice stream"); return 2;
    }
    EnterCriticalSection(&g_cvLock);
    g_cv[slot].used = true;                                               // the reader may append from now on
    LeaveCriticalSection(&g_cvLock);
    float vol = g_cvVolume;
    if (lua_gettop(L) >= 3 && lua_type(L, 3) == LUA_TNUMBER) vol *= (float)luaL_checknumber(L, 3);
    ma_sound_set_volume(&g_cv[slot].snd, vol);
    // the request: the clip's full path in UTF-8, the text on one line with no tabs (the protocol's separators)
    static char line[MAX_PATH * 3 + 1024];
    int k = _snprintf(line, sizeof line - 2, "SPEAK\t%u\t%s", s->id, g_cvDirUtf8);
    for (const char *c = rel; *c && k < (int)sizeof line - 1100; c++) line[k++] = *c == '/' ? '\\' : *c;
    line[k++] = '\t';
    for (size_t i = 0; i < tn && i < 1000; i++) {
        char c = text[i];
        line[k++] = (c == '\t' || c == '\r' || c == '\n') ? ' ' : c;
    }
    if (lua_gettop(L) >= 4 && lua_type(L, 4) == LUA_TNUMBER) {
        double sp = luaL_checknumber(L, 4);
        if (sp >= 0.5 && sp <= 2.0) k += _snprintf(line + k, 16, "\t%.2f", sp);
    }
    line[k++] = '\n'; line[k] = 0;
    if (!CvSend(line)) {
        CvFree(slot);
        InterlockedExchange(&g_cvState, 3);
        _snprintf(g_cvWhy, sizeof g_cvWhy, "cannot reach the speech engine");
        lua_pushnil(L); lua_pushstring(L, g_cvWhy); return 2;
    }
    ma_sound_start(&g_cv[slot].snd);                                      // silence until the first audio arrives
    g_cvCur = slot;
    lua_pushnumber(L, s->id);
    return 1;
}

static int __cdecl CV_Stop(lua_State *L)
{
    unsigned fade = 120;
    if (lua_gettop(L) >= 1 && lua_type(L, 1) == LUA_TNUMBER) { double v = luaL_checknumber(L, 1); fade = v < 0 ? 0 : (unsigned)v; }
    if (g_engineOk) { CvStopCurrent(fade); CvReap(); }
    return 0;
}

static int __cdecl CV_IsSpeaking(lua_State *L)
{
    if (g_engineOk) CvReap();
    if (g_cvCur < 0) { lua_pushnil(L); return 1; }
    lua_pushnumber(L, g_cv[g_cvCur].s.id);
    return 1;
}

static int __cdecl CV_SetVolume(lua_State *L)
{
    double v = luaL_checknumber(L, 1);
    g_cvVolume = (float)(v < 0 ? 0 : v > 1 ? 1 : v);
    if (g_cvCur >= 0) ma_sound_set_volume(&g_cv[g_cvCur].snd, g_cvVolume);
    return 0;
}

static int __cdecl CV_Status(lua_State *L)
{
    static const char *names[4] = {"off", "starting", "ready", "failed"};
    LONG st = g_cvState;
    lua_pushstring(L, names[st >= 0 && st < 4 ? st : 3]);
    if (st == 3 && g_cvWhy[0]) { lua_pushstring(L, g_cvWhy); return 2; }
    return 1;
}

// called from LivingVoices_OpenLib every time the client builds its Lua state (login and every /reload)
static void CompanionVoice_OpenLib(lua_State *L)
{
    if (!g_cvLockInit) { InitializeCriticalSection(&g_cvLock); g_cvLockInit = true; }
    lua_createtable(L, 0, 6);
    lua_pushcclosure(L, CV_Speak, 0);      lua_setfield(L, -2, "Speak");
    lua_pushcclosure(L, CV_Stop, 0);       lua_setfield(L, -2, "Stop");
    lua_pushcclosure(L, CV_IsSpeaking, 0); lua_setfield(L, -2, "IsSpeaking");
    lua_pushcclosure(L, CV_SetVolume, 0);  lua_setfield(L, -2, "SetVolume");
    lua_pushcclosure(L, CV_Status, 0);     lua_setfield(L, -2, "Status");
    lua_pushstring(L, "0.1");              lua_setfield(L, -2, "Version");
    lua_setfield(L, LUA_GLOBALSINDEX, "CompanionVoiceEngine");
    if (g_engineOk) CvStopCurrent(0);                                     // a /reload cuts any line still speaking
}
