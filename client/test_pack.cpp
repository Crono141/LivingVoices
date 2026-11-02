// test_pack -- read every line of a built pack back through the DLL's own reader (lv_pack.h) and miniaudio's decoder.
//   test_pack <list> <archive.MPQ>...     list: as for mkpack; archives in mount order (the last wins)
// Each name must come back byte for byte as its source file and decode to a length; a name not in the list must not.
#include <stdio.h>
#include <string.h>
#include <vector>
#define MINIAUDIO_IMPLEMENTATION
#define MA_NO_DEVICE_IO
#define MA_NO_ENCODING
#define MA_NO_GENERATION
#include "third_party/miniaudio.h"
#include "lv_pack.h"

static std::vector<char> slurp(const char *p)
{
    std::vector<char> v;
    FILE *f = fopen(p, "rb");
    if (!f) return v;
    char b[65536]; size_t n;
    while ((n = fread(b, 1, sizeof b, f)) > 0) v.insert(v.end(), b, b + n);
    fclose(f);
    return v;
}

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: test_pack <list> <archive.MPQ>...\n"); return 2; }
    LvPack p = {};
    for (int i = 2; i < argc; i++) if (!LvPackMount(&p, argv[i])) { fprintf(stderr, "cannot mount %s\n", argv[i]); return 1; }
    FILE *lf = fopen(argv[1], "r");
    if (!lf) { perror(argv[1]); return 1; }
    char line[4096];
    long n = 0, bad = 0; double secs = 0;
    while (fgets(line, sizeof line, lf)) {
        line[strcspn(line, "\r\n")] = 0;
        char *tab = strchr(line, '\t');
        if (!tab) continue;
        *tab = 0; const char *src = line, *name = tab + 1;
        size_t size = 0;
        void *buf = LvPackRead(&p, name, &size);
        std::vector<char> want = slurp(src);
        n++;
        if (!buf || size != want.size() || memcmp(buf, want.data(), size)) {
            if (bad++ < 10) fprintf(stderr, "MISMATCH %s (%s): got %zu bytes, want %zu\n", name, src, buf ? size : 0, want.size());
            free(buf); continue;
        }
        ma_decoder d;
        ma_decoder_config dc = ma_decoder_config_init(ma_format_f32, 0, 0);
        ma_uint64 frames = 0;
        if (ma_decoder_init_memory(buf, size, &dc, &d) != MA_SUCCESS) { if (bad++ < 10) fprintf(stderr, "NO DECODE %s\n", name); free(buf); continue; }
        ma_decoder_get_length_in_pcm_frames(&d, &frames);
        if (!frames || !d.outputSampleRate) { if (bad++ < 10) fprintf(stderr, "NO LENGTH %s\n", name); }
        else secs += (double)frames / d.outputSampleRate;
        ma_decoder_uninit(&d);
        free(buf);
    }
    fclose(lf);
    size_t sz = 0;
    void *none = LvPackRead(&p, "vo\\no-such-line.mp3", &sz);
    if (none) { fprintf(stderr, "a missing name was found\n"); bad++; free(none); }
    printf("%ld lines read back, %ld bad, %.1f h of speech\n", n, bad, secs / 3600);
    return bad ? 1 : 0;
}
