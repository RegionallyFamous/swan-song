// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 Regionally Famous
// Yokoi Boot installer and SRAM recovery utility.

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wonderful.h>
#include <ws.h>
#include <wse/memory.h>
#include <wsx/console.h>

#include "yokoi_boot_bin.h"

WSE_RESERVE_TILES(512, 0);

#define EEPROM_SIZE 2048
#define SPLASH_OFFSET 0x80
#define BACKUP_DATA_OFFSET 16
#define SPLASH_ENABLE_WORD_MASK 0x8000

static volatile uint8_t __far *const backup_sram = (volatile uint8_t __far *)MK_FP(0x1000, 0x0000);

static uint16_t crc16_update(uint16_t crc, uint8_t value) {
	uint8_t bit;
	crc ^= (uint16_t)value << 8;
	for (bit = 0; bit < 8; bit++) {
		crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
	}
	return crc;
}

static void show(const char __far *text) {
	wsx_console_clear();
	printf(text);
}

static void wait_release(void) {
	while (ws_keypad_scan() != 0) { }
}

static bool wait_for_chord(uint16_t chord) {
	wait_release();
	while (true) {
		uint16_t keys = ws_keypad_scan();
		if ((keys & chord) == chord) {
			wait_release();
			return true;
		}
		if ((keys & WS_KEY_B) && !(chord & WS_KEY_B)) {
			wait_release();
			return false;
		}
	}
}

static uint16_t backup_crc(void) {
	uint16_t crc = 0xFFFF;
	uint16_t i;
	for (i = 0; i < EEPROM_SIZE; i++) crc = crc16_update(crc, backup_sram[BACKUP_DATA_OFFSET + i]);
	return crc;
}

static bool backup_is_valid(void) {
	uint16_t stored_crc;
	if (backup_sram[0] != 'Y' || backup_sram[1] != 'K' ||
		backup_sram[2] != 'B' || backup_sram[3] != 'K' || backup_sram[4] != 1 ||
		backup_sram[5] != (uint8_t)ws_system_get_model()) return false;
	stored_crc = (uint16_t)backup_sram[6] | ((uint16_t)backup_sram[7] << 8);
	return stored_crc == backup_crc();
}

static bool backup_internal_eeprom(void) {
	ws_eeprom_handle_t handle = ws_eeprom_handle_internal();
	uint16_t crc = 0xFFFF;
	uint16_t i;

	backup_sram[0] = 0;
	for (i = 0; i < EEPROM_SIZE; i++) {
		uint8_t value = ws_eeprom_read_byte(handle, i);
		backup_sram[BACKUP_DATA_OFFSET + i] = value;
		crc = crc16_update(crc, value);
	}
	for (i = 0; i < EEPROM_SIZE; i++) {
		if (backup_sram[BACKUP_DATA_OFFSET + i] != ws_eeprom_read_byte(handle, i)) return false;
	}
	backup_sram[4] = 1;
	backup_sram[5] = (uint8_t)ws_system_get_model();
	backup_sram[6] = (uint8_t)crc;
	backup_sram[7] = (uint8_t)(crc >> 8);
	backup_sram[1] = 'K';
	backup_sram[2] = 'B';
	backup_sram[3] = 'K';
	backup_sram[0] = 'Y';
	return backup_is_valid();
}

static bool restore_internal_eeprom(void) {
	ws_eeprom_handle_t handle = ws_eeprom_handle_internal();
	uint16_t i;
	bool ok = true;

	if (!backup_is_valid() || ws_ieep_is_protected()) return false;
	if (!ws_eeprom_write_unlock(handle)) return false;
	for (i = 0; i < EEPROM_SIZE; i += 2) {
		uint16_t value = (uint16_t)backup_sram[BACKUP_DATA_OFFSET + i] |
			((uint16_t)backup_sram[BACKUP_DATA_OFFSET + i + 1] << 8);
		if (!ws_eeprom_write_word(handle, i, value)) {
			ok = false;
			break;
		}
	}
	ws_eeprom_write_lock(handle);
	if (!ok) return false;
	for (i = 0; i < EEPROM_SIZE; i++) {
		if (ws_eeprom_read_byte(handle, i) != backup_sram[BACKUP_DATA_OFFSET + i]) return false;
	}
	return true;
}

static bool install_yokoi_boot(void) {
	ws_eeprom_handle_t handle = ws_eeprom_handle_internal();
	uint16_t settings_word;
	uint16_t i;
	bool ok = true;

	if (yokoi_boot_size != EEPROM_SIZE - SPLASH_OFFSET || ws_ieep_is_protected()) return false;
	if (!ws_eeprom_write_unlock(handle)) return false;

	settings_word = ws_eeprom_read_word(handle, 0x82);
	if (!ws_eeprom_write_word(handle, 0x82, settings_word & ~SPLASH_ENABLE_WORD_MASK)) ok = false;
	for (i = 4; ok && i < yokoi_boot_size; i += 2) {
		uint16_t value;
		if (i >= 0x2C && i < 0x36) continue;
		if (i == 4 && yokoi_boot[i] >= 0x10) continue;
		value = (uint16_t)yokoi_boot[i] | ((uint16_t)yokoi_boot[i + 1] << 8);
		if (ws_eeprom_read_word(handle, SPLASH_OFFSET + i) != value &&
			!ws_eeprom_write_word(handle, SPLASH_OFFSET + i, value)) ok = false;
	}
	for (i = 4; ok && i < yokoi_boot_size; i += 2) {
		uint16_t expected;
		if (i >= 0x2C && i < 0x36) continue;
		if (i == 4 && yokoi_boot[i] >= 0x10) continue;
		expected = (uint16_t)yokoi_boot[i] | ((uint16_t)yokoi_boot[i + 1] << 8);
		if (ws_eeprom_read_word(handle, SPLASH_OFFSET + i) != expected) ok = false;
	}
	if (ok) ok = ws_eeprom_write_word(handle, 0x82, settings_word | SPLASH_ENABLE_WORD_MASK);
	ws_eeprom_write_lock(handle);
	return ok;
}

static void show_menu(void) {
	show(
		"YOKOI BOOT INSTALLER\n\n"
		"A   BACKUP + INSTALL\n\n"
		"Y1  BACKUP ONLY\n\n"
		"Y2  RESTORE BACKUP\n\n"
		"B   DO NOTHING\n\n"
		"COLOR / SWANCRYSTAL ONLY\n"
	);
}

void main(void) {
	ws_system_model_t model;

	wsx_console_init_default(&wse_screen1);
	ws_display_set_control(WS_DISPLAY_CTRL_SCR1_ENABLE);
	model = ws_system_get_model();
	if (model != WS_MODEL_COLOR && model != WS_MODEL_CRYSTAL) {
		show("UNSUPPORTED CONSOLE\n\nUSE WONDERSWAN COLOR\nOR SWANCRYSTAL.");
		while (true) { }
	}

	while (true) {
		uint16_t keys;
		show_menu();
		wait_release();
		do { keys = ws_keypad_scan(); } while (keys == 0);
		if (keys & WS_KEY_A) {
			show("INSTALL YOKOI BOOT?\n\nHOLD A+B TO CONFIRM\n\nB ALONE CANCELS.\n\nPOWER MUST STAY ON.");
			if (!wait_for_chord(WS_KEY_A | WS_KEY_B)) continue;
			show("BACKING UP EEPROM...\n\nDO NOT POWER OFF.");
			if (!backup_internal_eeprom()) {
				show("BACKUP VERIFY FAILED.\n\nNOTHING WAS INSTALLED.\n\nPRESS B.");
				wait_for_chord(WS_KEY_B);
				continue;
			}
			show("INSTALLING YOKOI BOOT...\n\nDO NOT POWER OFF.");
			show(install_yokoi_boot() ?
				"INSTALL COMPLETE.\n\nBACKUP IS IN CART SRAM.\n\nPOWER OFF AND REMOVE CART.\n\nPRESS B FOR MENU." :
				"INSTALL VERIFY FAILED.\n\nCUSTOM SPLASH LEFT OFF.\n\nPRESS B FOR MENU.");
			wait_for_chord(WS_KEY_B);
		} else if (keys & WS_KEY_Y1) {
			show("BACKING UP EEPROM...\n\nDO NOT POWER OFF.");
			show(backup_internal_eeprom() ?
				"BACKUP SAVED AND VERIFIED.\n\nPRESS B FOR MENU." :
				"BACKUP VERIFY FAILED.\n\nPRESS B FOR MENU.");
			wait_for_chord(WS_KEY_B);
		} else if (keys & WS_KEY_Y2) {
			show("RESTORE FULL EEPROM?\n\nHOLD Y1+Y3+A TO CONFIRM\n\nB CANCELS.\n\nPOWER MUST STAY ON.");
			if (!wait_for_chord(WS_KEY_Y1 | WS_KEY_Y3 | WS_KEY_A)) continue;
			show("RESTORING EEPROM...\n\nDO NOT POWER OFF.");
			show(restore_internal_eeprom() ?
				"RESTORE COMPLETE.\n\nPOWER OFF NOW.\n\nPRESS B FOR MENU." :
				"RESTORE FAILED OR NO\nVALID SAME-CONSOLE BACKUP.\n\nPRESS B FOR MENU.");
			wait_for_chord(WS_KEY_B);
		} else {
			wait_release();
		}
	}
}
