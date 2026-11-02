// lv_pack.h -- the add-on's MPQ archives, read with StormLib (shared by LivingVoices.cpp and test_pack.cpp).
//
// (1.1.0) The lines ship in one MPQ in the add-on's folder (Interface\AddOns\LivingVoices\LivingVoices.MPQ, names
// inside "vo\<line>.mp3") instead of 24,000 loose mp3s: one file unzips and copies at disk speed, and antivirus scans
// one file, not 24,000. Every *.MPQ in the folder is mounted; a later name (by plain byte order) wins, so a fix ships
// as a small LivingVoices.patch.MPQ beside the base ('.p' sorts after '.M'; a "LivingVoices-..." name would sort
// BEFORE the base and lose). Not in Data\: the client would load it into its own chain.
#pragma once
#include <stdlib.h>
#include <string.h>
#include "third_party/StormLib/src/StormLib.h"

#define LV_MAX_ARCHIVES 16
struct LvPack {
    HANDLE mpq[LV_MAX_ARCHIVES];                  // in mount order: the last one wins
    int n;
};

// open one archive read-only; false if it is not an MPQ or the slots are full
static bool LvPackMount(LvPack *p, const char *path)
{
    if (p->n >= LV_MAX_ARCHIVES) return false;
    HANDLE h = NULL;
    if (!SFileOpenArchive(path, 0, MPQ_OPEN_READ_ONLY | STREAM_FLAG_READ_ONLY, &h)) return false;
    p->mpq[p->n++] = h;
    return true;
}

// the whole file (an mp3 is ~100 KB) in a malloc'd buffer the caller frees; NULL if no archive has it
static void *LvPackRead(const LvPack *p, const char *name, size_t *size)
{
    for (int i = p->n - 1; i >= 0; i--) {
        HANDLE f = NULL;
        if (!SFileOpenFileEx(p->mpq[i], name, SFILE_OPEN_FROM_MPQ, &f)) continue;
        DWORD hi = 0, lo = SFileGetFileSize(f, &hi);
        void *buf = (lo != SFILE_INVALID_SIZE && !hi && lo) ? malloc(lo) : NULL;
        DWORD got = 0;
        bool ok = buf && SFileReadFile(f, buf, lo, &got, NULL) && got == lo;
        SFileCloseFile(f);
        if (ok) { *size = lo; return buf; }
        free(buf);
    }
    return NULL;
}
