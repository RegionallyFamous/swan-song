#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <wonderful.h>
#include <ws.h>
#include <wse/memory.h>
#include <wsx/console.h>

#include "runtime/dialbug.h"
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
	PAL_HEADER = 8
};

static uint16_t previous_keys;
static uint8_t ui_frame;

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

static void load_mascot(void) {
	uint16_t *palette = WS_SCREEN_COLOR_MEM(PAL_MASCOT);
	memcpy(WS_TILE_MEM(0), gfx_dialbug_mascot_tiles, gfx_dialbug_mascot_tiles_size);
	memcpy(palette, gfx_dialbug_mascot_palette, gfx_dialbug_mascot_palette_size);
	ws_screen_put_tiles(&wse_screen1, gfx_dialbug_mascot_map, 0, 2, 9, 8);
}

static void draw_static_ui(void) {
	uint8_t y;
	for (y = 0; y < 18; y++) fill_row(y, ' ', PAL_BODY);
	fill_row(0, ' ', PAL_HEADER);
	put_text(1, 0, "DIALBUG // POCKET MIX", PAL_HEADER);
	put_text(23, 0, "WSC", PAL_HEADER);
	fill_row(1, '=', PAL_DIM);
	put_text(1, 1, ":: FOUR-CHANNEL MIXER ::", PAL_ACCENT);

	put_text(10, 2, "TRACK    /   ", PAL_DIM);
	put_text(10, 5, "LOOP [          ]", PAL_DIM);
	put_text(18, 6, "BPM", PAL_DIM);
	put_text(10, 7, "SPD", PAL_DIM);
	put_text(20, 7, "VOL", PAL_DIM);
	put_text(10, 8, "LIVE MIX", PAL_ACCENT);
	put_text(10, 9, "o o o o o o o o o", PAL_DIM);

	fill_row(10, '-', PAL_DIM);
	for (y = 0; y < DIALBUG_CHANNEL_COUNT; y++) {
		put_char(0, (uint8_t)(10 + y), (char)('1' + y), PAL_TITLE);
		put_char(1, (uint8_t)(10 + y), '|', PAL_DIM);
		put_char(27, (uint8_t)(10 + y), '|', PAL_DIM);
	}
	fill_row(14, '=', PAL_DIM);
	put_text(1, 15, "A PAUSE   B RESTART", PAL_BODY);
	put_text(1, 16, "X < > SONG  ^ v VOL", PAL_BODY);
	put_text(1, 17, "START SPEED  Y1-4 MUTE", PAL_DIM);
}

static void draw_note(uint8_t x, uint8_t y, uint8_t note, uint8_t palette) {
	static const char names[12][2] = {
		{ 'C', ' ' }, { 'C', '#' }, { 'D', ' ' }, { 'D', '#' },
		{ 'E', ' ' }, { 'F', ' ' }, { 'F', '#' }, { 'G', ' ' },
		{ 'G', '#' }, { 'A', ' ' }, { 'A', '#' }, { 'B', ' ' }
	};
	uint8_t index;
	uint8_t octave;
	if (note == DIALBUG_NOTE_NONE || note == DIALBUG_NOTE_OFF) {
		put_text(x, y, "---", palette);
		return;
	}
	index = (uint8_t)((note - 1) % 12);
	octave = (uint8_t)(((note - 1) / 12) + 2);
	put_char(x, y, names[index][0], palette);
	put_char((uint8_t)(x + 1), y, names[index][1], palette);
	put_char((uint8_t)(x + 2), y, (char)('0' + octave), palette);
}

static void draw_meter(uint8_t x, uint8_t y, uint8_t level, bool muted) {
	uint8_t i;
	uint8_t filled = (uint8_t)(((uint16_t)level * 12u + 14u) / 15u);
	for (i = 0; i < 12; i++) {
		put_char((uint8_t)(x + i), y, i < filled ? '#' : '.',
			muted ? PAL_WARN : PAL_GOOD);
	}
}

static void draw_dynamic_ui(void) {
	const dialbug_song_t __far *song = dialbug_music_song();
	uint16_t step = dialbug_music_step();
	uint16_t total = dialbug_music_total_steps();
	uint8_t progress = total ? (uint8_t)((step * 10u) / total) : 0;
	uint8_t i;

	put_u8(16, 2, (uint8_t)(dialbug_music_song_index() + 1), 2, PAL_ACCENT);
	put_u8(21, 2, dialbug_song_count, 2, PAL_DIM);
	put_far_text(10, 3, song->title, 18, PAL_TITLE);
	put_far_text(10, 4, song->subtitle, 18, PAL_DIM);

	for (i = 0; i < 10; i++) {
		put_char((uint8_t)(16 + i), 5, i < progress ? '=' : '-',
			i < progress ? PAL_GOOD : PAL_DIM);
	}
	put_text(10, 6, dialbug_music_is_paused() ? "PAUSED " : "PLAYING",
		dialbug_music_is_paused() ? PAL_WARN : PAL_GOOD);
	put_u8(22, 6, (uint8_t)song->bpm, 3, PAL_BODY);
	put_u8(14, 7, dialbug_music_speed_percent(), 3, PAL_BODY);
	put_char(17, 7, '%', PAL_BODY);
	put_u8(24, 7, dialbug_music_master_volume(), 1, PAL_BODY);
	put_text(10, 9, "o o o o o o o o o", PAL_DIM);
	put_char((uint8_t)(10 + ((ui_frame >> 3) & 7)), 9, '*', PAL_ACCENT);

	for (i = 0; i < DIALBUG_CHANNEL_COUNT; i++) {
		uint8_t y = (uint8_t)(10 + i);
		bool muted = dialbug_music_is_muted(i);
		put_far_text(3, y,
			dialbug_music_instrument_name(dialbug_music_channel_instrument(i)), 6,
			muted ? PAL_WARN : PAL_BODY);
		draw_note(9, y, dialbug_music_channel_note(i), muted ? PAL_WARN : PAL_BODY);
		draw_meter(13, y, dialbug_music_channel_level(i), muted);
		put_char(26, y, muted ? 'M' : ' ', muted ? PAL_WARN : PAL_BODY);
	}
}

static void handle_input(void) {
	uint16_t keys = ws_keypad_scan();
	uint16_t pressed = keys & (uint16_t)~previous_keys;
	uint8_t song = dialbug_music_song_index();
	uint8_t volume = dialbug_music_master_volume();

	if (pressed & WS_KEY_A) dialbug_music_toggle_pause();
	if (pressed & WS_KEY_B) dialbug_music_restart();
	if (pressed & WS_KEY_X4) {
		dialbug_music_select(song ? (uint8_t)(song - 1) : (uint8_t)(dialbug_song_count - 1));
	}
	if (pressed & WS_KEY_X2) dialbug_music_select((uint8_t)((song + 1) % dialbug_song_count));
	if ((pressed & WS_KEY_X1) && volume < 8) dialbug_music_set_master_volume((uint8_t)(volume + 1));
	if ((pressed & WS_KEY_X3) && volume > 0) dialbug_music_set_master_volume((uint8_t)(volume - 1));
	if (pressed & WS_KEY_START) {
		dialbug_music_set_speed_index((uint8_t)(dialbug_music_speed_index() + 1));
	}
	if (pressed & WS_KEY_Y1) dialbug_music_toggle_mute(0);
	if (pressed & WS_KEY_Y2) dialbug_music_toggle_mute(1);
	if (pressed & WS_KEY_Y3) dialbug_music_toggle_mute(2);
	if (pressed & WS_KEY_Y4) dialbug_music_toggle_mute(3);
	previous_keys = keys;
}

void main(void) {
	ws_display_set_control(0);
	ws_system_set_mode(WS_MODE_COLOR);
	wsx_console_init_default(&wse_screen1);
	ws_display_set_screen_addresses(&wse_screen1, &wse_screen2);
	ws_display_scroll_screen1_to(0, 0);

	set_palette(PAL_BODY,   WS_RGB(0, 1, 3), WS_RGB(10, 13, 15));
	set_palette(PAL_TITLE,  WS_RGB(0, 1, 3), WS_RGB(15, 10, 3));
	set_palette(PAL_ACCENT, WS_RGB(0, 1, 3), WS_RGB(3, 14, 15));
	set_palette(PAL_GOOD,   WS_RGB(0, 1, 3), WS_RGB(2, 14, 15));
	set_palette(PAL_WARN,   WS_RGB(0, 1, 3), WS_RGB(15, 4, 6));
	set_palette(PAL_DIM,    WS_RGB(0, 1, 3), WS_RGB(6, 8, 11));
	set_palette(PAL_HEADER, WS_RGB(15, 10, 2), WS_RGB(0, 1, 3));

	draw_static_ui();
	load_mascot();
	dialbug_music_init();
	draw_dynamic_ui();
	ws_display_set_control(WS_DISPLAY_CTRL_SCR1_ENABLE);

	ws_int_set_default_handler_vblank();
	ws_int_enable(WS_INT_ENABLE_VBLANK);
	ia16_enable_irq();

	while (1) {
		ia16_halt();
		handle_input();
		dialbug_music_update();
		if (!(++ui_frame & 3)) draw_dynamic_ui();
	}
}
