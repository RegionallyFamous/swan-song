// SPDX-License-Identifier: CC0-1.0
//
// SPDX-FileContributor: Adrian "asie" Siekierka, 2025
// SPDX-FileContributor: Swan Song contributors, 2026
#include <stdio.h>
#include <stdbool.h>
#include <wonderful.h>
#include <ws.h>
#include <wse/memory.h>
#include <wsx/console.h>

WSE_RESERVE_TILES(512, 0);

volatile uint16_t initialized_word = 0x5AA5;
volatile uint16_t zero_word;

const char __far ok_message[] = "MEDIUM-SRAM OK";
const char __far fail_message[] = "MEDIUM-SRAM FAIL";

void main(void) {
	bool valid = ws_system_set_mode(WS_MODE_COLOR);
	valid = valid && initialized_word == 0x5AA5 && zero_word == 0;
	initialized_word = 0xA55A;
	zero_word = 0xC33C;
	valid = valid && initialized_word == 0xA55A && zero_word == 0xC33C;

	wsx_console_init_default(&wse_screen1);
	printf(valid ? ok_message : fail_message);
	ws_display_set_control(WS_DISPLAY_CTRL_SCR1_ENABLE);

	while(1) {
		ia16_halt();
	}
}
