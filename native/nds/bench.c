/* Headless libretro probe. No display/input ownership and no commercial ROM data. */
#define _POSIX_C_SOURCE 200809L
#include <libretro.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <time.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>

static const char *save_dir, *cpu_mode = "jit";
static unsigned frames, presented, width, height;
static uint32_t last_hash;
static uint16_t image[256 * 384];
static int pad_a;

static void logger(enum retro_log_level level, const char *format, ...) {
    if (level < RETRO_LOG_WARN) return;
    va_list args; va_start(args, format); vfprintf(stderr, format, args); va_end(args);
}
static bool environment(unsigned command, void *data) {
    switch (command) {
    case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:
        ((struct retro_log_callback *)data)->log = logger; return true;
    case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
    case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
        *(const char **)data = save_dir; return true;
    case RETRO_ENVIRONMENT_GET_LANGUAGE:
        *(unsigned *)data = RETRO_LANGUAGE_ENGLISH; return true;
    case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:
        return *(enum retro_pixel_format *)data == RETRO_PIXEL_FORMAT_RGB565;
    case RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:
        *(bool *)data = false; return true;
    case RETRO_ENVIRONMENT_SET_VARIABLES:
    case RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:
    case RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL:
    case RETRO_ENVIRONMENT_SET_GEOMETRY:
        return true;
    case RETRO_ENVIRONMENT_GET_VARIABLE: {
        struct retro_variable *v = data;
        static const char *const options[][2] = {
            {"desmume_internal_resolution", "256x192"},
            {"desmume_num_cores", "1"},
            {"desmume_jit_block_size", "12"},
            {"desmume_screens_layout", "top/bottom"},
            {"desmume_pointer_type", "touch"},
            {"desmume_pointer_mouse", "enabled"},
            {"desmume_load_to_memory", "enabled"},
            {"desmume_frameskip", "0"},
            {"desmume_mic_mode", "random"},
        };
        if (!strcmp(v->key, "desmume_cpu_mode")) { v->value = cpu_mode; return true; }
        for (size_t i = 0; i < sizeof(options)/sizeof(options[0]); ++i)
            if (!strcmp(v->key, options[i][0])) { v->value = options[i][1]; return true; }
        v->value = NULL; return false;
    }
    default: return false;
    }
}
static void video(const void *data, unsigned w, unsigned h, size_t pitch) {
    if (!data || w != 256 || h != 384) return;
    width = w; height = h; presented++;
    uint32_t hash = 2166136261u;
    for (unsigned y = 0; y < h; ++y) {
        const uint16_t *row = (const uint16_t *)((const char *)data + y * pitch);
        memcpy(image + y * w, row, w * 2);
        for (unsigned x = 0; x < w; ++x) hash = (hash ^ row[x]) * 16777619u;
    }
    last_hash = hash;
}
static void audio(int16_t left, int16_t right) { (void)left; (void)right; }
static size_t audio_batch(const int16_t *data, size_t count) { (void)data; return count; }
static void poll_input(void) {}
static int16_t input(unsigned port, unsigned device, unsigned index, unsigned id) {
    (void)port; (void)index;
    return device == RETRO_DEVICE_JOYPAD && id == RETRO_DEVICE_ID_JOYPAD_A && pad_a;
}
static double now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static void dump_image(const char *directory) {
    char path[1024]; snprintf(path, sizeof(path), "%s/frame.ppm", directory);
    FILE *f = fopen(path, "wb"); if (!f) return;
    fprintf(f, "P6\n%u %u\n255\n", width, height);
    for (unsigned i = 0; i < width * height; ++i) {
        unsigned v = image[i];
        unsigned char rgb[3] = {(v >> 11) * 255 / 31, ((v >> 5) & 63) * 255 / 63, (v & 31) * 255 / 31};
        fwrite(rgb, 1, 3, f);
    }
    fclose(f);
}
int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: nds-bench ROM SAVE_DIR [seconds] [jit|interpreter] [--self-test]\n"); return 2; }
    save_dir = argv[2]; mkdir(save_dir, 0700);
    double seconds = argc > 3 ? atof(argv[3]) : 10;
    if (seconds < 1 || seconds > 60) return 2;
    if (argc > 4) cpu_mode = argv[4];
    alarm((unsigned)seconds + 30); /* Bound even a hung retro_run during probing. */
    retro_set_environment(environment); retro_set_video_refresh(video);
    retro_set_audio_sample(audio); retro_set_audio_sample_batch(audio_batch);
    retro_set_input_poll(poll_input); retro_set_input_state(input);
    retro_init();
    struct retro_game_info game = {.path = argv[1]};
    if (!retro_load_game(&game)) { fprintf(stderr, "ROM load failed\n"); retro_deinit(); return 3; }
    double start = now();
    do { retro_run(); frames++; } while (now() - start < seconds);
    double elapsed = now() - start;
    uint32_t counter_before = 0, counter_after = 0, pad = 0;
    uint8_t *ram = retro_get_memory_data(RETRO_MEMORY_SYSTEM_RAM);
    if (ram) memcpy(&counter_before, ram + 0x1000, 4);
    size_t state_size = retro_serialize_size();
    void *state = state_size && state_size <= 32 * 1024 * 1024 ? calloc(1, state_size) : NULL;
    bool saved = state && retro_serialize(state, state_size);
    pad_a = 1;
    for (int i = 0; i < 5; ++i) retro_run();
    if (ram) memcpy(&pad, ram + 0x1004, 4);
    bool restored = saved && retro_unserialize(state, state_size);
    if (ram) memcpy(&counter_after, ram + 0x1000, 4);
    free(state); dump_image(save_dir);
    struct rusage usage; getrusage(RUSAGE_SELF, &usage);
    printf("PAPEROS_NDS_BENCH {\"mode\":\"%s\",\"frames\":%u,\"seconds\":%.6f,\"emulated_fps\":%.3f,\"video_frames\":%u,\"width\":%u,\"height\":%u,\"frame_hash\":%u,\"max_rss_kib\":%ld,\"state_bytes\":%zu,\"serialized\":%s,\"restored\":%s,\"counter_before\":%u,\"counter_after\":%u,\"pad_test\":%u}\n",
           cpu_mode, frames, elapsed, frames / elapsed, presented, width, height, last_hash,
           usage.ru_maxrss, state_size, saved ? "true" : "false", restored ? "true" : "false",
           counter_before, counter_after, pad);
    retro_unload_game(); retro_deinit();
    if (argc > 5 && !strcmp(argv[5], "--self-test"))
        return !(saved && restored && width == 256 && height == 384 && counter_before > 0 &&
                 counter_before == counter_after && pad == 1022);
    return saved && restored ? 0 : 4;
}
