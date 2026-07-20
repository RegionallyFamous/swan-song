// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Regionally Famous contributors

#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <wonderful.h>
#include <ws.h>
#include <wse/memory.h>
#include <wsx/console.h>

#include "runtime/swanframe.h"
#include "music.h"

WSE_RESERVE_TILES(512, 0);

enum {
	PAL_BODY = 0,
	PAL_TITLE = 1,
	PAL_ACCENT = 2,
	PAL_GOOD = 3,
	PAL_WARN = 4,
	PAL_DIM = 5,
	PAL_MASCOT = 6,
	PAL_PANEL = 7,
	PAL_HEADER = 8,
	PAL_PANEL_TITLE = 9,
	PAL_PANEL_ACCENT = 10,
	PAL_PANEL_DIM = 11,
	PAL_DIGIT_BLOCK = 12,
	PAL_PROGRESS = 13,
	PAL_PROGRESS_DIM = 14,
	PAL_WARN_BLOCK = 15
};

static uint16_t previous_keys;
static uint8_t ui_frame;

enum {
	UI_TILE_BLOCK = 64,
	UI_TILE_LEAD,
	UI_TILE_BASS,
	UI_TILE_ARP,
	UI_TILE_DRUM,
	UI_TILE_PLAY,
	UI_TILE_PAUSE,
	UI_TILE_RESTART
};

static void set_palette(uint8_t index, uint16_t background, uint16_t foreground) {
	uint16_t *palette = WS_SCREEN_COLOR_MEM(index);
	palette[0] = background;
	palette[1] = foreground;
	palette[2] = foreground;
	palette[3] = foreground;
}

static void put_char(uint8_t x, uint8_t y, char value, uint8_t palette) {
	uint16_t tile;
	if (x >= 28 || y >= 18) return;
	/* wsx_console_init_default installs printable ASCII 0x20..0x7f at tiles
	 * 0x1a0..0x1ff. The console cursor is intentionally bypassed so the live
	 * player can update individual cells without scrolling. */
	if ((uint8_t)value < 0x20 || (uint8_t)value > 0x7f) value = '?';
	tile = (uint16_t)(0x1a0u + (uint8_t)value - 0x20u);
	wse_screen1.row[y].cell[x] = WS_SCREEN_ATTR_TILE(tile) |
		WS_SCREEN_ATTR_PALETTE(palette);
}

static void put_ui_tile(uint8_t x, uint8_t y, uint16_t tile, uint8_t palette) {
	if (x >= 28 || y >= 18) return;
	wse_screen1.row[y].cell[x] = WS_SCREEN_ATTR_TILE(tile) |
		WS_SCREEN_ATTR_PALETTE(palette);
}

static void put_text(uint8_t x, uint8_t y, const char *text, uint8_t palette) {
	while (*text && x < 28) put_char(x++, y, *text++, palette);
}

static void put_far_text(uint8_t x, uint8_t y, const char __far *text,
	uint8_t width, uint8_t palette) {
	uint8_t count = 0;
	while (*text && count < width && x < 28) {
		put_char(x++, y, *text++, palette);
		count++;
	}
	while (count++ < width && x < 28) put_char(x++, y, ' ', palette);
}

static void put_u8(uint8_t x, uint8_t y, uint8_t value, uint8_t width, uint8_t palette) {
	uint8_t divisor = width == 3 ? 100 : (width == 2 ? 10 : 1);
	bool started = false;
	while (divisor) {
		uint8_t digit = value / divisor;
		value = (uint8_t)(value % divisor);
		if (digit || started || divisor == 1) {
			put_char(x, y, (char)('0' + digit), palette);
			started = true;
		} else {
			put_char(x, y, ' ', palette);
		}
		x++;
		divisor = (uint8_t)(divisor / 10);
	}
}

static void fill_row(uint8_t y, char value, uint8_t palette) {
	uint8_t x;
	for (x = 0; x < 28; x++) put_char(x, y, value, palette);
}

static void fill_rect(uint8_t x, uint8_t y, uint8_t width, uint8_t height,
	char value, uint8_t palette) {
	uint8_t row;
	uint8_t column;
	for (row = 0; row < height && (uint8_t)(y + row) < 18; row++) {
		for (column = 0; column < width && (uint8_t)(x + column) < 28; column++) {
			put_char((uint8_t)(x + column), (uint8_t)(y + row), value, palette);
		}
	}
}

static void load_mascot(void) {
	uint16_t *palette = WS_SCREEN_COLOR_MEM(PAL_MASCOT);
	memcpy(WS_TILE_MEM(0), gfx_swanframe_mascot_tiles, gfx_swanframe_mascot_tiles_size);
	memcpy(palette, gfx_swanframe_mascot_palette, gfx_swanframe_mascot_palette_size);
	ws_screen_put_tiles(&wse_screen1, gfx_swanframe_mascot_map, 0, 2, 9, 8);
}

static void load_ui_tiles(void) {
	memcpy(WS_TILE_MEM(UI_TILE_BLOCK), gfx_swanframe_ui_tiles,
		gfx_swanframe_ui_tiles_size);
}

static void draw_static_ui(void) {
	uint8_t y;
	for (y = 0; y < 18; y++) fill_row(y, ' ', PAL_BODY);
	fill_row(0, ' ', PAL_HEADER);
	put_text(1, 0, "SWANFRAME", PAL_HEADER);
	put_char(22, 0, ' ', PAL_PROGRESS);
	put_char(24, 0, ' ', PAL_PROGRESS);
	put_char(26, 0, ' ', PAL_PROGRESS);
	fill_row(1, '-', PAL_DIM);
	put_text(0, 1, ">>>", PAL_ACCENT);
	put_text(24, 1, "<<<", PAL_TITLE);

	/* A single instrument panel replaces the old title/subtitle/status stack. */
	fill_rect(10, 2, 18, 8, ' ', PAL_PANEL);
	put_text(10, 7, "------------------", PAL_PANEL_DIM);

	/* Four persistent channel lanes: identity, activity strip, mute lamp. */
	for (y = 0; y < SWANFRAME_CHANNEL_COUNT; y++) {
		static const char roles[SWANFRAME_CHANNEL_COUNT] = { 'L', 'B', 'A', 'D' };
		uint8_t row = (uint8_t)(10 + y);
		fill_rect(0, row, 28, 1, ' ', PAL_PANEL);
		put_char(0, row, (char)('1' + y),
			y & 1 ? PAL_PANEL_ACCENT : PAL_PANEL_TITLE);
		put_char(1, row, roles[y], PAL_PANEL_DIM);
		put_char(2, row, '|', PAL_PANEL_DIM);
	}
	fill_row(14, '-', PAL_DIM);

	/* Icon-led button dock. The README carries the long-form instructions. */
	fill_rect(0, 15, 28, 2, ' ', PAL_PANEL);
	put_text(0, 15, "  A  ", PAL_PANEL_TITLE);
	put_text(5, 15, "  B  ", PAL_PANEL_ACCENT);
	put_text(10, 15, "  X  ", PAL_PANEL_TITLE);
	put_text(15, 15, "  Y   ", PAL_PANEL_ACCENT);
	put_text(21, 15, " START ", PAL_PANEL_TITLE);
	put_ui_tile(1, 16, UI_TILE_PLAY, PAL_PANEL_ACCENT);
	put_ui_tile(3, 16, UI_TILE_PAUSE, PAL_PANEL_ACCENT);
	put_ui_tile(7, 16, UI_TILE_RESTART, PAL_PANEL_ACCENT);
	put_text(10, 16, " <>+-", PAL_PANEL_ACCENT);
	put_text(15, 16, " 1-4  ", PAL_PANEL_ACCENT);
	put_text(21, 16, "  x   ", PAL_PANEL_ACCENT);
	fill_row(17, '-', PAL_TITLE);
	put_text(1, 17, "///", PAL_ACCENT);
	put_text(24, 17, "///", PAL_ACCENT);
}

static void draw_big_digit(uint8_t x, uint8_t y, uint8_t digit) {
	static const uint8_t rows[10][5] = {
		{ 7, 5, 5, 5, 7 }, { 2, 6, 2, 2, 7 },
		{ 7, 1, 7, 4, 7 }, { 7, 1, 7, 1, 7 },
		{ 5, 5, 7, 1, 1 }, { 7, 4, 7, 1, 7 },
		{ 7, 4, 7, 5, 7 }, { 7, 1, 1, 1, 1 },
		{ 7, 5, 7, 5, 7 }, { 7, 5, 7, 1, 7 }
	};
	uint8_t row;
	uint8_t column;
	if (digit > 9) digit = 0;
	for (row = 0; row < 5; row++) {
		for (column = 0; column < 3; column++) {
			if (rows[digit][row] & (uint8_t)(4u >> column)) {
				put_ui_tile((uint8_t)(x + column), (uint8_t)(y + row),
					UI_TILE_BLOCK, PAL_PANEL_TITLE);
			} else {
				put_char((uint8_t)(x + column), (uint8_t)(y + row), ' ', PAL_PANEL);
			}
		}
	}
}

static void draw_meter(uint8_t x, uint8_t y, uint8_t width, uint8_t level,
	bool muted, uint8_t channel) {
	uint8_t i;
	uint8_t filled = (uint8_t)(((uint16_t)level * width + 14u) / 15u);
	uint8_t active_palette = muted ? PAL_WARN :
		(channel & 1 ? PAL_PANEL_ACCENT : PAL_PANEL_TITLE);
	for (i = 0; i < width; i++) {
		put_ui_tile((uint8_t)(x + i), y, (uint16_t)(UI_TILE_LEAD + channel),
			i < filled ? active_palette : PAL_PANEL_DIM);
	}
}

static void draw_dynamic_ui(void) {
	const swanframe_song_t __far *song = swanframe_music_song();
	uint16_t step = swanframe_music_step();
	uint16_t total = swanframe_music_total_steps();
	uint8_t progress = total ? (uint8_t)((step * 18u) / total) : 0;
	uint8_t song_number = (uint8_t)(swanframe_music_song_index() + 1);
	uint8_t i;

	/* Dominant 3x5 block numerals make the current track glance-readable. */
	draw_big_digit(10, 2, (uint8_t)(song_number / 10));
	draw_big_digit(14, 2, (uint8_t)(song_number % 10));
	put_char(18, 2, '/', PAL_PANEL_DIM);
	put_u8(19, 2, swanframe_song_count, 2, PAL_PANEL_ACCENT);
	put_char(26, 2, swanframe_music_is_paused() ? '|' : '>',
		swanframe_music_is_paused() ? PAL_WARN : PAL_PANEL_ACCENT);
	put_u8(18, 3, (uint8_t)song->bpm, 3, PAL_PANEL_ACCENT);
	put_char(22, 3, '*', PAL_PANEL_DIM);
	put_char(18, 4, 'x', PAL_PANEL_DIM);
	put_u8(20, 4, swanframe_music_speed_percent(), 3, PAL_PANEL_ACCENT);
	put_char(23, 4, '%', PAL_PANEL_ACCENT);
	for (i = 0; i < 8; i++) {
		put_ui_tile((uint8_t)(18 + i), 5, UI_TILE_BLOCK,
			i < swanframe_music_master_volume() ? PAL_PANEL_ACCENT : PAL_PANEL_DIM);
	}
	for (i = 0; i < 10; i++) {
		uint8_t phase = (uint8_t)((i + (ui_frame >> 2)) % 5);
		put_char((uint8_t)(18 + i), 6, phase == 0 ? '*' : (phase == 2 ? '+' : '.'),
			phase == 0 ? PAL_PANEL_TITLE : PAL_PANEL_ACCENT);
	}
	put_far_text(10, 8, song->title, 18, PAL_PANEL_TITLE);
	for (i = 0; i < 18; i++) {
		put_char((uint8_t)(10 + i), 9, i < progress ? '=' : '.',
			i < progress ? PAL_PANEL_ACCENT : PAL_PANEL_DIM);
	}

	for (i = 0; i < SWANFRAME_CHANNEL_COUNT; i++) {
		uint8_t y = (uint8_t)(10 + i);
		bool muted = swanframe_music_is_muted(i);
		draw_meter(3, y, 22, swanframe_music_channel_level(i), muted, i);
		put_char(26, y, muted ? 'X' : 'o', muted ? PAL_WARN : PAL_PANEL_DIM);
		put_char(27, y, ' ', muted ? PAL_WARN_BLOCK : PAL_PANEL);
	}
}

static void handle_input(void) {
	uint16_t keys = ws_keypad_scan();
	uint16_t pressed = keys & (uint16_t)~previous_keys;
	uint8_t song = swanframe_music_song_index();
	uint8_t volume = swanframe_music_master_volume();

	if (pressed & WS_KEY_A) swanframe_music_toggle_pause();
	if (pressed & WS_KEY_B) swanframe_music_restart();
	if (pressed & WS_KEY_X4) {
		swanframe_music_select(song ? (uint8_t)(song - 1) : (uint8_t)(swanframe_song_count - 1));
	}
	if (pressed & WS_KEY_X2) swanframe_music_select((uint8_t)((song + 1) % swanframe_song_count));
	if ((pressed & WS_KEY_X1) && volume < 8) swanframe_music_set_master_volume((uint8_t)(volume + 1));
	if ((pressed & WS_KEY_X3) && volume > 0) swanframe_music_set_master_volume((uint8_t)(volume - 1));
	if (pressed & WS_KEY_START) {
		swanframe_music_set_speed_index((uint8_t)(swanframe_music_speed_index() + 1));
	}
	if (pressed & WS_KEY_Y1) swanframe_music_toggle_mute(0);
	if (pressed & WS_KEY_Y2) swanframe_music_toggle_mute(1);
	if (pressed & WS_KEY_Y3) swanframe_music_toggle_mute(2);
	if (pressed & WS_KEY_Y4) swanframe_music_toggle_mute(3);
	previous_keys = keys;
}

void main(void) {
	ws_display_set_control(0);
	ws_system_set_mode(WS_MODE_COLOR);
	wsx_console_init_default(&wse_screen1);
	ws_display_set_screen_addresses(&wse_screen1, &wse_screen2);
	ws_display_scroll_screen1_to(0, 0);

	set_palette(PAL_BODY,   WS_RGB(1, 0, 2), WS_RGB(6, 15, 12));
	set_palette(PAL_TITLE,  WS_RGB(1, 0, 2), WS_RGB(15, 4, 10));
	set_palette(PAL_ACCENT, WS_RGB(1, 0, 2), WS_RGB(6, 15, 12));
	set_palette(PAL_GOOD,   WS_RGB(1, 0, 2), WS_RGB(6, 15, 12));
	set_palette(PAL_WARN,   WS_RGB(1, 0, 2), WS_RGB(15, 4, 10));
	set_palette(PAL_DIM,    WS_RGB(1, 0, 2), WS_RGB(7, 6, 10));
	set_palette(PAL_PANEL,  WS_RGB(3, 2, 5), WS_RGB(6, 15, 12));
	set_palette(PAL_HEADER, WS_RGB(15, 4, 10), WS_RGB(1, 0, 2));
	set_palette(PAL_PANEL_TITLE,  WS_RGB(3, 2, 5), WS_RGB(15, 4, 10));
	set_palette(PAL_PANEL_ACCENT, WS_RGB(3, 2, 5), WS_RGB(6, 15, 12));
	set_palette(PAL_PANEL_DIM,    WS_RGB(3, 2, 5), WS_RGB(7, 6, 10));
	set_palette(PAL_DIGIT_BLOCK,  WS_RGB(15, 4, 10), WS_RGB(1, 0, 2));
	set_palette(PAL_PROGRESS,     WS_RGB(6, 15, 12), WS_RGB(1, 0, 2));
	set_palette(PAL_PROGRESS_DIM, WS_RGB(3, 2, 5), WS_RGB(1, 0, 2));
	set_palette(PAL_WARN_BLOCK,   WS_RGB(15, 4, 10), WS_RGB(1, 0, 2));

	draw_static_ui();
	load_ui_tiles();
	load_mascot();
	swanframe_music_init();
	draw_dynamic_ui();
	ws_display_set_control(WS_DISPLAY_CTRL_SCR1_ENABLE);

	ws_int_set_default_handler_vblank();
	ws_int_enable(WS_INT_ENABLE_VBLANK);
	ia16_enable_irq();

	while (1) {
		ia16_halt();
		handle_input();
		swanframe_music_update();
		if (!(++ui_frame & 3)) draw_dynamic_ui();
	}
}
