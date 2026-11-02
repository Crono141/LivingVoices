// LivingVoicesPatcher.exe: makes Wow.exe (3.3.5a 12340) load LivingVoices.dll at startup, or undoes it. The same 82
// bytes as patch_wowexe.py (the awesome_wotlk patch, GPL-3.0, github.com/FrostAtom/awesome_wotlk), for players
// without Python. Double-click it in the WoW folder, or drop Wow.exe on it.
//   stock Wow.exe   -> keeps Wow.exe.stock, patches, checks the result
//   patched Wow.exe -> asks, then puts the stock bytes back
//   anything else   -> refuses (another build, or already changed by something else)
// Built by build.sh (i686-w64-mingw32-g++).
#include <windows.h>
#include <wincrypt.h>
#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>
#include "patch_bytes.h"

static const char *STOCK_SHA1 = "178f78380affd260cb775d44397ba6b33ac05fdb";
static const char *PATCHED_SHA1 = "bb9da1e1aec944cf8dafb880c113f325155a8884";
static const size_t N = sizeof(PATCH) / sizeof(PATCH[0]);

static std::string sha1(const std::vector<unsigned char> &d) {
    HCRYPTPROV prov = 0; HCRYPTHASH h = 0; BYTE out[20]; DWORD len = 20; std::string s;
    if (!CryptAcquireContextA(&prov, NULL, NULL, PROV_RSA_FULL, CRYPT_VERIFYCONTEXT)) return s;
    if (CryptCreateHash(prov, CALG_SHA1, 0, 0, &h)) {
        if (CryptHashData(h, d.data(), (DWORD)d.size(), 0) && CryptGetHashParam(h, HP_HASHVAL, out, &len, 0)) {
            char hex[41];
            for (int i = 0; i < 20; i++) sprintf(hex + 2 * i, "%02x", out[i]);
            s = hex;
        }
        CryptDestroyHash(h);
    }
    CryptReleaseContext(prov, 0);
    return s;
}

static bool readAll(const std::string &p, std::vector<unsigned char> &d) {
    FILE *f = fopen(p.c_str(), "rb"); if (!f) return false;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    d.resize(n > 0 ? n : 0);
    bool ok = n > 0 && fread(d.data(), 1, n, f) == (size_t)n; fclose(f); return ok;
}

// write beside the target, then swap it in: a failed write never leaves a half-written Wow.exe
static bool writeAll(const std::string &p, const std::vector<unsigned char> &d) {
    std::string t = p + ".new";
    FILE *f = fopen(t.c_str(), "wb"); if (!f) return false;
    bool ok = fwrite(d.data(), 1, d.size(), f) == d.size(); ok = (fclose(f) == 0) && ok;
    if (!ok) { DeleteFileA(t.c_str()); return false; }
    return MoveFileExA(t.c_str(), p.c_str(), MOVEFILE_REPLACE_EXISTING) != 0;
}

static int finish(int code) {
    printf("\nPress Enter to close.");
    getchar();
    return code;
}

int main(int argc, char **argv) {
    printf("Living Voices patcher -- lets Wow.exe (3.3.5a) load LivingVoices.dll\n\n");
    std::string exe;
    if (argc > 1) exe = argv[1];
    else {
        char me[MAX_PATH]; GetModuleFileNameA(NULL, me, MAX_PATH);
        std::string dir(me); dir = dir.substr(0, dir.find_last_of("\\/") + 1);
        exe = dir + "Wow.exe";
    }
    std::vector<unsigned char> img;
    if (!readAll(exe, img)) {
        printf("Cannot read %s.\nPut this patcher in the World of Warcraft folder (beside Wow.exe) and run it there,\n"
               "or drop Wow.exe onto it. Close the game first.\n", exe.c_str());
        return finish(1);
    }
    std::string h = sha1(img);
    if (h.empty()) { printf("Could not compute the file's checksum (Windows CryptoAPI failed).\n"); return finish(1); }
    for (size_t i = 0; i < N; i++)
        if (PATCH[i].off >= img.size()) { printf("%s is too small to be the 3.3.5a client.\n", exe.c_str()); return finish(1); }

    if (h == STOCK_SHA1) {
        std::string backup = exe + ".stock";
        bool ok = CopyFileA(exe.c_str(), backup.c_str(), FALSE) != 0;
        if (!ok) { printf("Could not write the backup %s.\n", backup.c_str()); return finish(1); }
        for (size_t i = 0; i < N; i++) img[PATCH[i].off] = PATCH[i].patched;
        if (sha1(img) != PATCHED_SHA1) { printf("Internal check failed; Wow.exe was NOT changed.\n"); return finish(1); }
        if (!writeAll(exe, img)) { printf("Could not write %s (is the game running?). It was NOT changed.\n", exe.c_str()); return finish(1); }
        printf("Done: Wow.exe now loads LivingVoices.dll.\nThe original is kept as Wow.exe.stock; run this patcher again to undo.\n");
        if (GetFileAttributesA((exe.substr(0, exe.find_last_of("\\/") + 1) + "LivingVoices.dll").c_str()) == INVALID_FILE_ATTRIBUTES)
            printf("\nNOTE: LivingVoices.dll is not next to Wow.exe yet -- copy it there too.\n");
        return finish(0);
    }
    if (h == PATCHED_SHA1) {
        printf("Wow.exe is already patched for Living Voices.\nUndo it and put the original back? [y/N] ");
        int c = getchar(); if (c != '\n') while (getchar() != '\n') {}
        if (c != 'y' && c != 'Y') { printf("Left as it is.\n"); return finish(0); }
        for (size_t i = 0; i < N; i++) img[PATCH[i].off] = PATCH[i].stock;
        if (sha1(img) != STOCK_SHA1) { printf("Internal check failed; Wow.exe was NOT changed.\n"); return finish(1); }
        if (!writeAll(exe, img)) { printf("Could not write %s (is the game running?). It was NOT changed.\n", exe.c_str()); return finish(1); }
        printf("Done: Wow.exe is the original again.\n");
        return finish(0);
    }
    printf("Refusing: %s is not the stock 3.3.5a (12340) Wow.exe this patch is made for\n(sha1 %s).\n"
           "If another tool patched it, restore its original first.\n", exe.c_str(), h.c_str());
    return finish(1);
}
