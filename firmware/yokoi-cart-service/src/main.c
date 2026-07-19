// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 Regionally Famous
//
// Yokoi Cart Service: RAM-resident WonderSwan cartridge reader/save writer.

#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <wonderful.h>
#include <ws.h>
#include <wse/memory.h>

#ifndef YOKOI_VERSION_MAJOR
#define YOKOI_VERSION_MAJOR 0
#define YOKOI_VERSION_MINOR 2
#define YOKOI_VERSION_PATCH 0
#endif

WSE_RESERVE_TILES(64, 0);

#define PROTOCOL_VERSION 1
#define FRAME_MAGIC_0 0x59
#define FRAME_MAGIC_1 0x4B
#define MAX_REQUEST_PAYLOAD 128
#define MAX_READ_LENGTH 128

#define CAP_READ_ROM    0x0001
#define CAP_READ_SRAM   0x0002
#define CAP_READ_EEPROM 0x0004
#define CAP_WRITE_SRAM  0x0100
#define CAP_WRITE_EEPROM 0x0200

typedef enum {
	CMD_HELLO = 0x01,
	CMD_GET_CART_INFO = 0x02,
	CMD_READ_ROM = 0x10,
	CMD_READ_SRAM = 0x11,
	CMD_READ_EEPROM = 0x12,
	CMD_WRITE_SRAM = 0x20,
	CMD_WRITE_EEPROM = 0x21,
	CMD_FLASH_ERASE = 0x22,
	CMD_FLASH_PROGRAM = 0x23,
	CMD_PREPARE_WRITE = 0x30,
	CMD_BEGIN_WRITE = 0x31,
	CMD_CANCEL_WRITE = 0x32
} command_t;

typedef enum {
	STATUS_OK = 0x00,
	STATUS_BAD_CRC = 0x01,
	STATUS_BAD_LENGTH = 0x02,
	STATUS_UNSUPPORTED = 0x03,
	STATUS_RANGE = 0x04,
	STATUS_WRITE_LOCKED = 0x05,
	STATUS_NO_SAVE_MEMORY = 0x06,
	STATUS_PHYSICAL_CONFIRMATION = 0x07,
	STATUS_CART_CHANGED = 0x08,
	STATUS_VERIFY_FAILED = 0x09,
	STATUS_WRITE_SEQUENCE = 0x0A,
	STATUS_IMAGE_CRC = 0x0B
} status_t;

typedef enum {
	SAVE_NONE = 0,
	SAVE_SRAM = 1,
	SAVE_EEPROM = 2,
	SAVE_UNKNOWN = 0xFF
} save_kind_t;

typedef enum {
	PARSER_MAGIC_0,
	PARSER_MAGIC_1,
	PARSER_VERSION,
	PARSER_SEQUENCE,
	PARSER_COMMAND,
	PARSER_LENGTH_0,
	PARSER_LENGTH_1,
	PARSER_PAYLOAD,
	PARSER_CRC_0,
	PARSER_CRC_1
} parser_state_t;

typedef struct {
	parser_state_t state;
	uint8_t version;
	uint8_t sequence;
	uint8_t command;
	uint16_t length;
	uint16_t position;
	uint16_t crc;
	uint16_t received_crc;
	uint8_t payload[MAX_REQUEST_PAYLOAD];
} parser_t;

typedef struct {
	uint8_t raw[16];
	uint8_t flags;
	uint8_t save_kind;
	uint8_t eeprom_address_bits;
	uint32_t rom_size;
	uint32_t save_size;
} cart_info_t;

typedef struct {
	bool prepared;
	bool active;
	uint8_t save_kind;
	uint16_t cart_fingerprint;
	uint16_t token;
	uint32_t size;
	uint32_t position;
	uint32_t expected_crc32;
	uint32_t running_crc32;
} write_session_t;

static parser_t parser;
static uint8_t response[MAX_READ_LENGTH + 6];
static bool activity_shown;
static write_session_t write_session;

/* Five-pixel-wide rows for 0-9 and A-Z. The UI stays deliberately tiny so
 * the BootFriend executable leaves nearly all internal RAM to the service. */
static const uint8_t font_rows[36][7] = {
	{0x0E,0x11,0x13,0x15,0x19,0x11,0x0E}, {0x04,0x0C,0x04,0x04,0x04,0x04,0x0E},
	{0x0E,0x11,0x01,0x02,0x04,0x08,0x1F}, {0x1E,0x01,0x01,0x0E,0x01,0x01,0x1E},
	{0x02,0x06,0x0A,0x12,0x1F,0x02,0x02}, {0x1F,0x10,0x10,0x1E,0x01,0x01,0x1E},
	{0x0E,0x10,0x10,0x1E,0x11,0x11,0x0E}, {0x1F,0x01,0x02,0x04,0x08,0x08,0x08},
	{0x0E,0x11,0x11,0x0E,0x11,0x11,0x0E}, {0x0E,0x11,0x11,0x0F,0x01,0x01,0x0E},
	{0x0E,0x11,0x11,0x1F,0x11,0x11,0x11}, {0x1E,0x11,0x11,0x1E,0x11,0x11,0x1E},
	{0x0E,0x11,0x10,0x10,0x10,0x11,0x0E}, {0x1E,0x11,0x11,0x11,0x11,0x11,0x1E},
	{0x1F,0x10,0x10,0x1E,0x10,0x10,0x1F}, {0x1F,0x10,0x10,0x1E,0x10,0x10,0x10},
	{0x0E,0x11,0x10,0x17,0x11,0x11,0x0F}, {0x11,0x11,0x11,0x1F,0x11,0x11,0x11},
	{0x0E,0x04,0x04,0x04,0x04,0x04,0x0E}, {0x07,0x02,0x02,0x02,0x12,0x12,0x0C},
	{0x11,0x12,0x14,0x18,0x14,0x12,0x11}, {0x10,0x10,0x10,0x10,0x10,0x10,0x1F},
	{0x11,0x1B,0x15,0x15,0x11,0x11,0x11}, {0x11,0x19,0x15,0x13,0x11,0x11,0x11},
	{0x0E,0x11,0x11,0x11,0x11,0x11,0x0E}, {0x1E,0x11,0x11,0x1E,0x10,0x10,0x10},
	{0x0E,0x11,0x11,0x11,0x15,0x12,0x0D}, {0x1E,0x11,0x11,0x1E,0x14,0x12,0x11},
	{0x0F,0x10,0x10,0x0E,0x01,0x01,0x1E}, {0x1F,0x04,0x04,0x04,0x04,0x04,0x04},
	{0x11,0x11,0x11,0x11,0x11,0x11,0x0E}, {0x11,0x11,0x11,0x11,0x11,0x0A,0x04},
	{0x11,0x11,0x11,0x15,0x15,0x15,0x0A}, {0x11,0x11,0x0A,0x04,0x0A,0x11,0x11},
	{0x11,0x11,0x0A,0x04,0x04,0x04,0x04}, {0x1F,0x01,0x02,0x04,0x08,0x10,0x1F}
};

static uint8_t ui_tile_for_char(char value) {
	if (value >= '0' && value <= '9') return (uint8_t)(1 + value - '0');
	if (value >= 'A' && value <= 'Z') return (uint8_t)(11 + value - 'A');
	return 0;
}

static void ui_puts(uint8_t x, uint8_t y, const char *text) {
	while (*text && x < 28) {
		ws_screen_put_tile(&wse_screen1, ui_tile_for_char(*text), x++, y);
		text++;
	}
}

static void ui_init(void) {
	uint8_t glyph;
	uint8_t row;
	ws_display_tile_t ws_iram *tile;
	uint16_t ws_iram *palette;

	ws_display_set_control(0);
	ws_system_set_mode(WS_MODE_COLOR);
	ws_display_set_screen_addresses(&wse_screen1, &wse_screen2);
	ws_display_scroll_screen1_to(0, 0);
	ws_screen_fill_tiles(&wse_screen1, 0, 0, 0, 32, 32);
	memset(WS_TILE_MEM(0), 0, sizeof(ws_display_tile_t));

	for (glyph = 0; glyph < 36; glyph++) {
		tile = WS_TILE_MEM(glyph + 1);
		for (row = 0; row < 8; row++) {
			tile->plane[row][0] = row < 7 ? (uint8_t)(font_rows[glyph][row] << 2) : 0;
			tile->plane[row][1] = 0;
		}
	}

	palette = WS_SCREEN_COLOR_MEM(0);
	palette[0] = 0x0FFF;
	palette[1] = 0x0000;
	palette[2] = 0x0000;
	palette[3] = 0x0000;

	ui_puts(1, 2, "YOKOI CART SERVICE");
	ui_puts(1, 5, "READER AND SAVE WRITER");
	ui_puts(1, 7, "UART 38400 8N1");
	ui_puts(1, 10, "WAITING FOR HOST");
	ws_display_set_control(WS_DISPLAY_CTRL_SCR1_ENABLE);
}

static uint16_t crc16_update(uint16_t crc, uint8_t value) {
	uint8_t bit;
	crc ^= (uint16_t)value << 8;
	for (bit = 0; bit < 8; bit++) {
		crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
	}
	return crc;
}

static uint16_t read_u16(const uint8_t *data) {
	return (uint16_t)data[0] | ((uint16_t)data[1] << 8);
}

static uint32_t read_u32(const uint8_t *data) {
	return (uint32_t)data[0] | ((uint32_t)data[1] << 8) |
		((uint32_t)data[2] << 16) | ((uint32_t)data[3] << 24);
}

static void write_u16(uint8_t *data, uint16_t value) {
	data[0] = (uint8_t)value;
	data[1] = (uint8_t)(value >> 8);
}

static void write_u32(uint8_t *data, uint32_t value) {
	data[0] = (uint8_t)value;
	data[1] = (uint8_t)(value >> 8);
	data[2] = (uint8_t)(value >> 16);
	data[3] = (uint8_t)(value >> 24);
}

static uint32_t crc32_update(uint32_t crc, uint8_t value) {
	uint8_t bit;
	crc ^= value;
	for (bit = 0; bit < 8; bit++) {
		crc = (crc & 1) ? (crc >> 1) ^ 0xEDB88320UL : crc >> 1;
	}
	return crc;
}

static void uart_write(uint8_t value) {
	ws_uart_putc(value);
}

static void send_frame(uint8_t sequence, uint8_t command, const uint8_t *payload, uint16_t length) {
	uint16_t crc = 0xFFFF;
	uint16_t i;
	uint8_t header[5];

	header[0] = PROTOCOL_VERSION;
	header[1] = sequence;
	header[2] = command | 0x80;
	header[3] = (uint8_t)length;
	header[4] = (uint8_t)(length >> 8);

	uart_write(FRAME_MAGIC_0);
	uart_write(FRAME_MAGIC_1);
	for (i = 0; i < sizeof(header); i++) {
		crc = crc16_update(crc, header[i]);
		uart_write(header[i]);
	}
	for (i = 0; i < length; i++) {
		crc = crc16_update(crc, payload[i]);
		uart_write(payload[i]);
	}
	uart_write((uint8_t)crc);
	uart_write((uint8_t)(crc >> 8));
}

static void send_status(uint8_t sequence, uint8_t command, status_t status) {
	response[0] = (uint8_t)status;
	send_frame(sequence, command, response, 1);
}

static uint32_t rom_size_from_code(uint8_t code) {
	static const uint8_t banks[] = {2, 4, 8, 16, 32, 48, 64, 96, 128, 0};
	if (code == 9) return 16UL * 1024UL * 1024UL;
	if (code >= sizeof(banks) || banks[code] == 0) return 0;
	return (uint32_t)banks[code] * 65536UL;
}

static void save_geometry(uint8_t code, cart_info_t *info) {
	info->save_kind = SAVE_UNKNOWN;
	info->save_size = 0;
	info->eeprom_address_bits = 0;

	switch (code) {
	case 0x00:
		info->save_kind = SAVE_NONE;
		break;
	case 0x01:
	case 0x02:
		info->save_kind = SAVE_SRAM;
		info->save_size = 32UL * 1024UL;
		break;
	case 0x03:
		info->save_kind = SAVE_SRAM;
		info->save_size = 128UL * 1024UL;
		break;
	case 0x04:
		info->save_kind = SAVE_SRAM;
		info->save_size = 256UL * 1024UL;
		break;
	case 0x05:
		info->save_kind = SAVE_SRAM;
		info->save_size = 512UL * 1024UL;
		break;
	case 0x10:
		info->save_kind = SAVE_EEPROM;
		info->save_size = 128;
		info->eeprom_address_bits = 6;
		break;
	case 0x20:
		info->save_kind = SAVE_EEPROM;
		info->save_size = 2048;
		info->eeprom_address_bits = 10;
		break;
	case 0x50:
		info->save_kind = SAVE_EEPROM;
		info->save_size = 1024;
		info->eeprom_address_bits = 10;
		break;
	default:
		break;
	}
}

static void select_rom_bank(uint16_t bank) {
	outportw(WS_CART_EXTBANK_ROM0_PORT, bank);
	outportb(WS_CART_BANK_ROM0_PORT, (uint8_t)bank);
}

static void select_sram_bank(uint16_t bank) {
	outportw(WS_CART_EXTBANK_RAM_PORT, bank);
	outportb(WS_CART_BANK_RAM_PORT, (uint8_t)bank);
}

static void read_cart_info(cart_info_t *info) {
	const uint8_t __far *footer;
	uint8_t i;

	select_rom_bank(0xFFFF);
	footer = MK_FP(0x2FFF, 0x0000);
	for (i = 0; i < sizeof(info->raw); i++) info->raw[i] = footer[i];

	info->flags = 0;
	if (inportb(WS_SYSTEM_CTRL_PORT) & WS_SYSTEM_CTRL_SELF_TEST) info->flags |= 0x01;
	if (info->raw[0] == 0xEA) info->flags |= 0x02;
	info->rom_size = rom_size_from_code(info->raw[10]);
	if (info->rom_size != 0) info->flags |= 0x04;
	save_geometry(info->raw[11], info);
	if (info->save_kind != SAVE_UNKNOWN) info->flags |= 0x08;
}

static uint16_t cart_fingerprint(const cart_info_t *info) {
	uint16_t crc = 0xFFFF;
	uint8_t i;
	for (i = 0; i < sizeof(info->raw); i++) crc = crc16_update(crc, info->raw[i]);
	crc = crc16_update(crc, info->save_kind);
	crc = crc16_update(crc, (uint8_t)info->save_size);
	crc = crc16_update(crc, (uint8_t)(info->save_size >> 8));
	crc = crc16_update(crc, (uint8_t)(info->save_size >> 16));
	crc = crc16_update(crc, (uint8_t)(info->save_size >> 24));
	return crc;
}

static void write_ui(const char *line1, const char *line2) {
	ws_screen_fill_tiles(&wse_screen1, 0, 1, 12, 26, 4);
	ui_puts(1, 12, line1);
	ui_puts(1, 14, line2);
}

static void write_session_clear(void) {
	memset(&write_session, 0, sizeof(write_session));
}

static bool write_cart_unchanged(void) {
	cart_info_t info;
	read_cart_info(&info);
	return info.save_kind == write_session.save_kind &&
		info.save_size == write_session.size &&
		cart_fingerprint(&info) == write_session.cart_fingerprint;
}

static bool valid_read_window(uint16_t offset, uint8_t length) {
	return length > 0 && length <= MAX_READ_LENGTH &&
		(uint32_t)offset + (uint32_t)length <= 65536UL;
}

static void handle_hello(uint8_t sequence, uint8_t command, uint16_t length) {
	if (length != 0) {
		send_status(sequence, command, STATUS_BAD_LENGTH);
		return;
	}
	response[0] = STATUS_OK;
	response[1] = PROTOCOL_VERSION;
	response[2] = YOKOI_VERSION_MAJOR;
	response[3] = YOKOI_VERSION_MINOR;
	response[4] = YOKOI_VERSION_PATCH;
	response[5] = (uint8_t)ws_system_get_model();
	write_u16(response + 6, CAP_READ_ROM | CAP_READ_SRAM | CAP_READ_EEPROM |
		CAP_WRITE_SRAM | CAP_WRITE_EEPROM);
	response[8] = MAX_READ_LENGTH;
	response[9] = 5;
	response[10] = 'Y';
	response[11] = 'O';
	response[12] = 'K';
	response[13] = 'O';
	response[14] = 'I';
	send_frame(sequence, command, response, 15);
}

static void handle_cart_info(uint8_t sequence, uint8_t command, uint16_t length) {
	cart_info_t info;
	uint8_t i;

	if (length != 0) {
		send_status(sequence, command, STATUS_BAD_LENGTH);
		return;
	}
	read_cart_info(&info);
	response[0] = STATUS_OK;
	response[1] = info.flags;
	response[2] = (uint8_t)ws_system_get_model();
	response[3] = inportb(WS_SYSTEM_CTRL_PORT);
	response[4] = info.save_kind;
	response[5] = info.eeprom_address_bits;
	write_u32(response + 6, info.rom_size);
	write_u32(response + 10, info.save_size);
	for (i = 0; i < sizeof(info.raw); i++) response[14 + i] = info.raw[i];
	send_frame(sequence, command, response, 30);
}

static void handle_read_rom(uint8_t sequence, uint8_t command, const uint8_t *payload, uint16_t length) {
	const uint8_t __far *source;
	uint16_t bank;
	uint16_t offset;
	uint8_t count;
	uint8_t i;

	if (length != 5) {
		send_status(sequence, command, STATUS_BAD_LENGTH);
		return;
	}
	bank = read_u16(payload);
	offset = read_u16(payload + 2);
	count = payload[4];
	if (!valid_read_window(offset, count)) {
		send_status(sequence, command, STATUS_RANGE);
		return;
	}

	select_rom_bank(bank);
	source = MK_FP(0x2000, offset);
	response[0] = STATUS_OK;
	for (i = 0; i < count; i++) response[i + 1] = source[i];
	send_frame(sequence, command, response, (uint16_t)count + 1);
}

static void handle_read_sram(uint8_t sequence, uint8_t command, const uint8_t *payload, uint16_t length) {
	const uint8_t __far *source;
	uint16_t bank;
	uint16_t offset;
	uint8_t count;
	uint8_t i;
	cart_info_t info;

	if (length != 5) {
		send_status(sequence, command, STATUS_BAD_LENGTH);
		return;
	}
	read_cart_info(&info);
	if (info.save_kind != SAVE_SRAM) {
		send_status(sequence, command, STATUS_NO_SAVE_MEMORY);
		return;
	}
	bank = read_u16(payload);
	offset = read_u16(payload + 2);
	count = payload[4];
	if (!valid_read_window(offset, count)) {
		send_status(sequence, command, STATUS_RANGE);
		return;
	}

	select_sram_bank(bank);
	source = MK_FP(0x1000, offset);
	response[0] = STATUS_OK;
	for (i = 0; i < count; i++) response[i + 1] = source[i];
	send_frame(sequence, command, response, (uint16_t)count + 1);
}

static void handle_read_eeprom(uint8_t sequence, uint8_t command, const uint8_t *payload, uint16_t length) {
	ws_eeprom_handle_t handle;
	uint16_t address;
	uint8_t count;
	uint8_t i;
	cart_info_t info;

	if (length != 3) {
		send_status(sequence, command, STATUS_BAD_LENGTH);
		return;
	}
	read_cart_info(&info);
	if (info.save_kind != SAVE_EEPROM) {
		send_status(sequence, command, STATUS_NO_SAVE_MEMORY);
		return;
	}
	address = read_u16(payload);
	count = payload[2];
	if (count == 0 || count > MAX_READ_LENGTH ||
		(uint32_t)address + (uint32_t)count > info.save_size) {
		send_status(sequence, command, STATUS_RANGE);
		return;
	}

	handle = ws_eeprom_handle_cartridge(info.eeprom_address_bits);
	response[0] = STATUS_OK;
	for (i = 0; i < count; i++) response[i + 1] = ws_eeprom_read_byte(handle, address + i);
	send_frame(sequence, command, response, (uint16_t)count + 1);
}

static void handle_prepare_write(uint8_t sequence, uint8_t command, const uint8_t *payload, uint16_t length) {
	cart_info_t info;
	uint8_t requested_kind;
	uint32_t requested_size;
	uint32_t requested_crc32;

	if (length != 9) {
		send_status(sequence, command, STATUS_BAD_LENGTH);
		return;
	}
	requested_kind = payload[0];
	requested_size = read_u32(payload + 1);
	requested_crc32 = read_u32(payload + 5);
	read_cart_info(&info);
	if (info.save_kind != SAVE_SRAM && info.save_kind != SAVE_EEPROM) {
		send_status(sequence, command, STATUS_NO_SAVE_MEMORY);
		return;
	}
	if (requested_kind != info.save_kind || requested_size != info.save_size || requested_size == 0 ||
		(info.save_kind == SAVE_EEPROM && (requested_size & 1))) {
		send_status(sequence, command, STATUS_RANGE);
		return;
	}

	write_session_clear();
	write_session.prepared = true;
	write_session.save_kind = requested_kind;
	write_session.size = requested_size;
	write_session.expected_crc32 = requested_crc32;
	write_session.cart_fingerprint = cart_fingerprint(&info);
	write_session.token = write_session.cart_fingerprint ^
		(uint16_t)requested_crc32 ^ (uint16_t)(requested_crc32 >> 16) ^
		(uint16_t)requested_size ^ (uint16_t)(requested_size >> 16) ^ 0x594B;

	write_ui("WRITE REQUEST", "HOLD A AND B");
	response[0] = STATUS_OK;
	write_u16(response + 1, write_session.token);
	send_frame(sequence, command, response, 3);
}

static void handle_begin_write(uint8_t sequence, uint8_t command, const uint8_t *payload, uint16_t length) {
	uint16_t keys;

	if (length != 2) {
		send_status(sequence, command, STATUS_BAD_LENGTH);
		return;
	}
	if (!write_session.prepared || read_u16(payload) != write_session.token) {
		send_status(sequence, command, STATUS_WRITE_SEQUENCE);
		return;
	}
	if (!write_cart_unchanged()) {
		write_session_clear();
		write_ui("CARTRIDGE CHANGED", "WRITE CANCELLED");
		send_status(sequence, command, STATUS_CART_CHANGED);
		return;
	}
	keys = ws_keypad_scan();
	if ((keys & (WS_KEY_A | WS_KEY_B)) != (WS_KEY_A | WS_KEY_B)) {
		send_status(sequence, command, STATUS_PHYSICAL_CONFIRMATION);
		return;
	}

	write_session.active = true;
	write_session.position = 0;
	write_session.running_crc32 = 0xFFFFFFFFUL;
	write_ui("WRITE ARMED", "DO NOT POWER OFF");
	response[0] = STATUS_OK;
	write_u32(response + 1, 0);
	send_frame(sequence, command, response, 5);
}

static void handle_cancel_write(uint8_t sequence, uint8_t command, uint16_t length) {
	if (length != 0) {
		send_status(sequence, command, STATUS_BAD_LENGTH);
		return;
	}
	write_session_clear();
	write_ui("WRITE CANCELLED", "CARTRIDGE SAFE");
	send_status(sequence, command, STATUS_OK);
}

static bool write_sram_chunk(const uint8_t *data, uint8_t count) {
	uint16_t bank_count = (uint16_t)((write_session.size + 0xFFFFUL) >> 16);
	uint16_t bank_index = (uint16_t)(write_session.position >> 16);
	uint16_t bank = (uint16_t)(0U - bank_count + bank_index);
	uint16_t offset = (uint16_t)write_session.position;
	uint8_t __far *destination;
	uint8_t i;

	if ((uint32_t)offset + count > 65536UL) return false;
	select_sram_bank(bank);
	destination = MK_FP(0x1000, offset);
	for (i = 0; i < count; i++) destination[i] = data[i];
	for (i = 0; i < count; i++) {
		if (destination[i] != data[i]) return false;
	}
	return true;
}

static bool write_eeprom_chunk(const uint8_t *data, uint8_t count) {
	ws_eeprom_handle_t handle;
	uint16_t address = (uint16_t)write_session.position;
	uint8_t i;
	bool ok = true;

	if ((address & 1) || (count & 1)) return false;
	handle = ws_eeprom_handle_cartridge(10);
	if (write_session.size == 128) handle = ws_eeprom_handle_cartridge(6);
	if (!ws_eeprom_write_unlock(handle)) return false;
	for (i = 0; i < count; i += 2) {
		uint16_t value = (uint16_t)data[i] | ((uint16_t)data[i + 1] << 8);
		if (!ws_eeprom_write_word(handle, address + i, value)) {
			ok = false;
			break;
		}
	}
	ws_eeprom_write_lock(handle);
	if (!ok) return false;
	for (i = 0; i < count; i++) {
		if (ws_eeprom_read_byte(handle, address + i) != data[i]) return false;
	}
	return true;
}

static void handle_write_save(uint8_t sequence, uint8_t command, const uint8_t *payload, uint16_t length) {
	uint16_t i;
	uint32_t final_crc32;
	bool ok;

	if (!write_session.active ||
		(command == CMD_WRITE_SRAM && write_session.save_kind != SAVE_SRAM) ||
		(command == CMD_WRITE_EEPROM && write_session.save_kind != SAVE_EEPROM)) {
		send_status(sequence, command, STATUS_WRITE_LOCKED);
		return;
	}
	if (length == 0 || length > MAX_REQUEST_PAYLOAD ||
		write_session.position + length > write_session.size ||
		(write_session.save_kind == SAVE_EEPROM && (length & 1))) {
		write_session_clear();
		send_status(sequence, command, STATUS_WRITE_SEQUENCE);
		return;
	}
	if (!write_cart_unchanged()) {
		write_session_clear();
		write_ui("CARTRIDGE CHANGED", "WRITE CANCELLED");
		send_status(sequence, command, STATUS_CART_CHANGED);
		return;
	}

	ok = write_session.save_kind == SAVE_SRAM ?
		write_sram_chunk(payload, (uint8_t)length) :
		write_eeprom_chunk(payload, (uint8_t)length);
	if (!ok) {
		write_session_clear();
		write_ui("VERIFY FAILED", "WRITE CANCELLED");
		send_status(sequence, command, STATUS_VERIFY_FAILED);
		return;
	}
	for (i = 0; i < length; i++) {
		write_session.running_crc32 = crc32_update(write_session.running_crc32, payload[i]);
	}
	write_session.position += length;
	response[0] = STATUS_OK;
	write_u32(response + 1, write_session.position);
	response[5] = 0;
	if (write_session.position == write_session.size) {
		final_crc32 = write_session.running_crc32 ^ 0xFFFFFFFFUL;
		if (final_crc32 != write_session.expected_crc32) {
			write_session_clear();
			write_ui("IMAGE CRC FAILED", "CHECK HOST FILE");
			send_status(sequence, command, STATUS_IMAGE_CRC);
			return;
		}
		response[5] = 1;
		write_session_clear();
		write_ui("WRITE COMPLETE", "DATA VERIFIED");
	}
	send_frame(sequence, command, response, 6);
}

static void handle_packet(void) {
	if (parser.version != PROTOCOL_VERSION) {
		send_status(parser.sequence, parser.command, STATUS_UNSUPPORTED);
		return;
	}
	if (!activity_shown) {
		ws_screen_fill_tiles(&wse_screen1, 0, 1, 10, 26, 1);
		ui_puts(1, 10, "HOST CONNECTED");
		activity_shown = true;
	}
	if (write_session.active && parser.command != CMD_WRITE_SRAM &&
		parser.command != CMD_WRITE_EEPROM && parser.command != CMD_CANCEL_WRITE) {
		write_session_clear();
		write_ui("WRITE CANCELLED", "SESSION INTERRUPTED");
	}

	switch (parser.command) {
	case CMD_HELLO:
		handle_hello(parser.sequence, parser.command, parser.length);
		break;
	case CMD_GET_CART_INFO:
		handle_cart_info(parser.sequence, parser.command, parser.length);
		break;
	case CMD_READ_ROM:
		handle_read_rom(parser.sequence, parser.command, parser.payload, parser.length);
		break;
	case CMD_READ_SRAM:
		handle_read_sram(parser.sequence, parser.command, parser.payload, parser.length);
		break;
	case CMD_READ_EEPROM:
		handle_read_eeprom(parser.sequence, parser.command, parser.payload, parser.length);
		break;
	case CMD_WRITE_SRAM:
	case CMD_WRITE_EEPROM:
		handle_write_save(parser.sequence, parser.command, parser.payload, parser.length);
		break;
	case CMD_FLASH_ERASE:
	case CMD_FLASH_PROGRAM:
		send_status(parser.sequence, parser.command, STATUS_WRITE_LOCKED);
		break;
	case CMD_PREPARE_WRITE:
		handle_prepare_write(parser.sequence, parser.command, parser.payload, parser.length);
		break;
	case CMD_BEGIN_WRITE:
		handle_begin_write(parser.sequence, parser.command, parser.payload, parser.length);
		break;
	case CMD_CANCEL_WRITE:
		handle_cancel_write(parser.sequence, parser.command, parser.length);
		break;
	default:
		send_status(parser.sequence, parser.command, STATUS_UNSUPPORTED);
		break;
	}
}

static void parser_reset(void) {
	parser.state = PARSER_MAGIC_0;
	parser.length = 0;
	parser.position = 0;
	parser.crc = 0xFFFF;
	parser.received_crc = 0;
}

static void parser_feed(uint8_t value) {
	switch (parser.state) {
	case PARSER_MAGIC_0:
		if (value == FRAME_MAGIC_0) parser.state = PARSER_MAGIC_1;
		break;
	case PARSER_MAGIC_1:
		if (value == FRAME_MAGIC_1) {
			parser.state = PARSER_VERSION;
			parser.crc = 0xFFFF;
		} else {
			parser.state = (value == FRAME_MAGIC_0) ? PARSER_MAGIC_1 : PARSER_MAGIC_0;
		}
		break;
	case PARSER_VERSION:
		parser.version = value;
		parser.crc = crc16_update(parser.crc, value);
		parser.state = PARSER_SEQUENCE;
		break;
	case PARSER_SEQUENCE:
		parser.sequence = value;
		parser.crc = crc16_update(parser.crc, value);
		parser.state = PARSER_COMMAND;
		break;
	case PARSER_COMMAND:
		parser.command = value;
		parser.crc = crc16_update(parser.crc, value);
		parser.state = PARSER_LENGTH_0;
		break;
	case PARSER_LENGTH_0:
		parser.length = value;
		parser.crc = crc16_update(parser.crc, value);
		parser.state = PARSER_LENGTH_1;
		break;
	case PARSER_LENGTH_1:
		parser.length |= (uint16_t)value << 8;
		parser.crc = crc16_update(parser.crc, value);
		parser.position = 0;
		if (parser.length > MAX_REQUEST_PAYLOAD) {
			send_status(parser.sequence, parser.command, STATUS_BAD_LENGTH);
			parser_reset();
		} else {
			parser.state = parser.length ? PARSER_PAYLOAD : PARSER_CRC_0;
		}
		break;
	case PARSER_PAYLOAD:
		parser.payload[parser.position++] = value;
		parser.crc = crc16_update(parser.crc, value);
		if (parser.position == parser.length) parser.state = PARSER_CRC_0;
		break;
	case PARSER_CRC_0:
		parser.received_crc = value;
		parser.state = PARSER_CRC_1;
		break;
	case PARSER_CRC_1:
		parser.received_crc |= (uint16_t)value << 8;
		if (parser.received_crc == parser.crc) {
			handle_packet();
		} else {
			send_status(parser.sequence, parser.command, STATUS_BAD_CRC);
		}
		parser_reset();
		break;
	}
}

void main(void) {
	int16_t value;

	ui_init();
	activity_shown = false;
	write_session_clear();
	parser_reset();
	ws_uart_open(WS_UART_BAUD_RATE_38400);

	while (1) {
		if (ws_uart_is_rx_overrun()) {
			ws_uart_ack_rx_overrun();
			parser_reset();
		}
		value = ws_uart_getc_nonblock();
		if (value >= 0) parser_feed((uint8_t)value);
	}
}
