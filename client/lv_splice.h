// lv_splice.h -- a line with race/class sentences swapped in (shared by LivingVoices.cpp and test_splice.cpp; needs
// miniaudio). (0.4, pack 1.1.0, 2026-10-31) A sentence with $R/$C is rendered once per race or class and cut into the
// line's own take at playback: out = take[0:from1] + clip1 + take[to1:from2] + clip2 + ... + take[toN:]. The cuts
// fall in the pauses (tools/splices.py) and each clip carries the pause either side of it, so nothing is
// crossfaded. Everything is decoded to 24 kHz mono float in memory: a line is ~30 s, ~3 MB.
#pragma once
#include <stdlib.h>
#include <string.h>

#define LV_RATE 24000

// the whole mp3 decoded: malloc'd float frames (the caller frees) and their count; NULL if it does not decode
static float *LvDecodeAll(const void *data, size_t size, ma_uint64 *frames)
{
    ma_decoder d;
    ma_decoder_config dc = ma_decoder_config_init(ma_format_f32, 1, LV_RATE);
    if (ma_decoder_init_memory(data, size, &dc, &d) != MA_SUCCESS) return NULL;
    ma_uint64 cap = LV_RATE * 8, n = 0, got = 0;
    float *out = (float *)malloc(cap * sizeof(float));
    while (out) {
        if (n == cap) { float *o = (float *)realloc(out, (cap *= 2) * sizeof(float)); if (!o) { free(out); out = NULL; break; } out = o; }
        if (ma_decoder_read_pcm_frames(&d, out + n, cap - n, &got) != MA_SUCCESS || !got) break;
        n += got;
    }
    ma_decoder_uninit(&d);
    if (out && !n) { free(out); out = NULL; }
    *frames = n;
    return out;
}

struct LvPiece { ma_uint64 from, to; const float *clip; ma_uint64 clipN; };     // take frames [from, to) -> clip

// the take with the pieces in place (pieces in order, not overlapping; one out of range is skipped): malloc'd frames
static float *LvSplice(const float *take, ma_uint64 n, const LvPiece *p, int np, ma_uint64 *outN)
{
    ma_uint64 total = n;
    for (int i = 0; i < np; i++) if (p[i].from <= p[i].to && p[i].to <= n) total = total - (p[i].to - p[i].from) + p[i].clipN;
    float *out = (float *)malloc((total ? total : 1) * sizeof(float));
    if (!out) return NULL;
    ma_uint64 at = 0, pos = 0;
    for (int i = 0; i < np; i++) {
        if (!(p[i].from <= p[i].to && p[i].to <= n && p[i].from >= pos)) continue;
        memcpy(out + at, take + pos, (p[i].from - pos) * sizeof(float)); at += p[i].from - pos;
        memcpy(out + at, p[i].clip, p[i].clipN * sizeof(float)); at += p[i].clipN;
        pos = p[i].to;
    }
    memcpy(out + at, take + pos, (n - pos) * sizeof(float)); at += n - pos;
    *outN = at;
    return out;
}
