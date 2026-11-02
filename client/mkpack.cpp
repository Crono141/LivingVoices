// mkpack -- write the pack's MPQ (StormLib). build_release.py runs it.
//   mkpack <out.MPQ> <list>     list: one "<source file>\t<name in the archive>" per line, e.g. "render64/7-accept.mp3\tvo\7-accept.mp3"
// The mp3s are stored, not compressed (they do not compress, and stored files read with one seek); the archive keeps
// a (listfile) so MPQ editors show the names. Format v2: no 4 GB edge to worry about.
#include <stdio.h>
#include <string.h>
#include <string>
#include <vector>
#include "third_party/StormLib/src/StormLib.h"

int main(int argc, char **argv)
{
    if (argc != 3) { fprintf(stderr, "usage: mkpack <out.MPQ> <list>\n"); return 2; }
    FILE *lf = fopen(argv[2], "r");
    if (!lf) { perror(argv[2]); return 1; }
    std::vector<std::pair<std::string, std::string>> files;
    char line[4096];
    while (fgets(line, sizeof line, lf)) {
        line[strcspn(line, "\r\n")] = 0;
        char *tab = strchr(line, '\t');
        if (!tab) continue;
        *tab = 0; files.emplace_back(line, tab + 1);
    }
    fclose(lf);
    DWORD slots = 16;
    while (slots < files.size() + 16) slots *= 2;                      // the hash table: a power of two, room to spare
    remove(argv[1]);
    HANDLE h = NULL;
    if (!SFileCreateArchive(argv[1], MPQ_CREATE_LISTFILE | MPQ_CREATE_ATTRIBUTES | MPQ_CREATE_ARCHIVE_V2, slots, &h)) {
        fprintf(stderr, "cannot create %s (error %u)\n", argv[1], (unsigned)SErrGetLastError()); return 1;
    }
    size_t n = 0;
    for (auto &f : files) {
        if (!SFileAddFileEx(h, f.first.c_str(), f.second.c_str(), MPQ_FILE_REPLACEEXISTING, 0, 0)) {
            fprintf(stderr, "cannot add %s as %s (error %u)\n", f.first.c_str(), f.second.c_str(), (unsigned)SErrGetLastError());
            SFileCloseArchive(h); remove(argv[1]); return 1;
        }
        if (++n % 5000 == 0) fprintf(stderr, "  %zu / %zu\n", n, files.size());
    }
    if (!SFileCloseArchive(h)) { fprintf(stderr, "cannot finish %s (error %u)\n", argv[1], (unsigned)SErrGetLastError()); return 1; }
    printf("%zu files -> %s\n", n, argv[1]);
    return 0;
}
