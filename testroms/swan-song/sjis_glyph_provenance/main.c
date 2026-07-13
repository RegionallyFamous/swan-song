#include <stdint.h>
#include <string.h>
#include <wonderful.h>
#include <ws.h>
#include <ws/display.h>
#include <ws/dma.h>
#include <ws/system.h>

/*
 * Minimal Shift-JIS renderer fixture for trace provenance.
 *
 * The six canonical rasters are an unmodified subset of Misaki Gothic
 * 2021-05-05a. Their source and redistribution terms are recorded beside this
 * file; only their transport packing is WonderSwan-specific.
 */

__attribute__((section(".iramcx_1800")))
uint16_t screen_1[32 * 32];

/* Seven 2bpp tiles: blank tile 0, then six renderer-owned canvas tiles. */
__attribute__((section(".iramx_2000")))
uint16_t tile_words[7 * 8];

static const uint8_t message_sjis[] = {
    0x93, 0xFA, /* U+65E5 日 */
    0x96, 0x7B, /* U+672C 本 */
    0x8C, 0xEA, /* U+8A9E 語 */
    0x82, 0xA9, /* U+304B か */
    0x82, 0xC8, /* U+306A な */
    0x8A, 0xBF, /* U+6F22 漢 */
    0x00
};

static const uint16_t glyph_codes[] = {
    0x93FA, 0x967B, 0x8CEA, 0x82A9, 0x82C8, 0x8ABF
};

/*
 * Prepacked WonderSwan 2bpp planar tiles. Each pair is [plane 0, plane 1];
 * the canonical 1bpp Misaki row is deliberately kept in plane 1 (palette
 * index 2), so the in-memory row word is ROW << 8.
 */
static const uint8_t __wf_rom packed_glyphs[][16] __attribute__((aligned(2))) = {
    {0x00, 0x7E, 0x00, 0x42, 0x00, 0x42, 0x00, 0x7E,
     0x00, 0x42, 0x00, 0x42, 0x00, 0x7E, 0x00, 0x00}, /* 日 */
    {0x00, 0x10, 0x00, 0xFE, 0x00, 0x10, 0x00, 0x38,
     0x00, 0x54, 0x00, 0xBA, 0x00, 0x10, 0x00, 0x00}, /* 本 */
    {0x00, 0x5C, 0x00, 0xC8, 0x00, 0x3C, 0x00, 0xD4,
     0x00, 0x3E, 0x00, 0xD4, 0x00, 0xDC, 0x00, 0x00}, /* 語 */
    {0x00, 0x20, 0x00, 0x20, 0x00, 0xF4, 0x00, 0x2A,
     0x00, 0x4A, 0x00, 0x48, 0x00, 0xB0, 0x00, 0x00}, /* か */
    {0x00, 0x20, 0x00, 0xF4, 0x00, 0x22, 0x00, 0x44,
     0x00, 0x9C, 0x00, 0x26, 0x00, 0x18, 0x00, 0x00}, /* な */
    {0x00, 0x94, 0x00, 0x7E, 0x00, 0xAA, 0x00, 0x3E,
     0x00, 0xFE, 0x00, 0x88, 0x00, 0xB6, 0x00, 0x00}  /* 漢 */
};

static uint8_t find_glyph(uint16_t code) {
    for (uint8_t i = 0; i < 6; i++) {
        if (glyph_codes[i] == code) {
            return i;
        }
    }
    return 0xFF;
}

static void render_sjis(const uint8_t *text, uint8_t x, uint8_t y) {
    uint8_t tile = 1;

    while (*text != 0) {
        const uint16_t code = ((uint16_t)text[0] << 8) | text[1];
        const uint8_t glyph = find_glyph(code);
        if (glyph == 0xFF) {
            break;
        }

        ws_gdma_copy(&tile_words[tile * 8], packed_glyphs[glyph], 16);
        screen_1[((uint16_t)y * 32) + x] = tile;

        text += 2;
        x++;
        tile++;
    }
}

int main(void) {
    memset(screen_1, 0, sizeof(screen_1));
    memset(tile_words, 0, sizeof(tile_words));

    if (!ws_system_set_mode(WS_MODE_COLOR)) {
        while (1) {
            ia16_halt();
        }
    }

    WS_DISPLAY_COLOR_MEM(0)[0] = WS_RGB(15, 15, 15);
    WS_DISPLAY_COLOR_MEM(0)[1] = WS_RGB(15, 0, 0);
    WS_DISPLAY_COLOR_MEM(0)[2] = WS_RGB(0, 0, 0);
    WS_DISPLAY_COLOR_MEM(0)[3] = WS_RGB(0, 15, 0);

    render_sjis(message_sjis, 10, 8);
    ws_display_set_screen_addresses(screen_1, screen_1);
    ws_display_set_control(WS_DISPLAY_CTRL_SCR1_ENABLE);

    while (1) {
        ia16_halt();
    }
}
