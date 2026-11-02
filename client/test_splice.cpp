// test_splice -- the engine's splice (lv_splice.h) on files from disk, as PlaySpliced does it from the archive.
//   test_splice <take.mp3> <out.wav> [<from_ms> <to_ms> <clip.mp3>]...
#include <stdio.h>
#include <stdlib.h>
#define MINIAUDIO_IMPLEMENTATION
#define MA_NO_DEVICE_IO
#define MA_NO_GENERATION
#include "third_party/miniaudio.h"
#include "lv_splice.h"

static float *decode(const char *path, ma_uint64 *n)
{
    FILE *f = fopen(path, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    void *b = malloc(sz); size_t got = fread(b, 1, sz, f); fclose(f);
    float *pcm = got == (size_t)sz ? LvDecodeAll(b, sz, n) : NULL; free(b); return pcm;
}

int main(int argc, char **argv)
{
    if (argc < 3 || (argc - 3) % 3) { fprintf(stderr, "usage: test_splice <take.mp3> <out.wav> [<from_ms> <to_ms> <clip.mp3>]...\n"); return 2; }
    ma_uint64 n = 0; float *take = decode(argv[1], &n);
    if (!take) { fprintf(stderr, "cannot decode %s\n", argv[1]); return 1; }
    LvPiece p[8]; int np = 0;
    for (int a = 3; a + 2 < argc && np < 8; a += 3) {
        ma_uint64 cn = 0; float *c = decode(argv[a + 2], &cn);
        if (!c) { fprintf(stderr, "cannot decode %s\n", argv[a + 2]); continue; }
        p[np].from = (ma_uint64)(atof(argv[a]) * LV_RATE / 1000.0); p[np].to = (ma_uint64)(atof(argv[a + 1]) * LV_RATE / 1000.0);
        p[np].clip = c; p[np].clipN = cn; np++;
    }
    ma_uint64 outN = 0; float *out = LvSplice(take, n, p, np, &outN);
    ma_encoder_config ec = ma_encoder_config_init(ma_encoding_format_wav, ma_format_f32, 1, LV_RATE); ma_encoder e;
    if (ma_encoder_init_file(argv[2], &ec, &e) != MA_SUCCESS) return 1;
    ma_encoder_write_pcm_frames(&e, out, outN, NULL); ma_encoder_uninit(&e);
    printf("take %.2f s, %d piece(s), out %.2f s\n", n / (double)LV_RATE, np, outN / (double)LV_RATE);
    return 0;
}
