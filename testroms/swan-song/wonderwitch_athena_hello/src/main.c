// SPDX-License-Identifier: CC0-1.0
//
// SPDX-FileContributor: Adrian "asie" Siekierka, 2023
#include <wonderful.h>
#include <sys/bios.h>

void main(int argc, char** argv) {
	text_screen_init();
	text_put_string(0, 0, "Hello, World!");
	while (key_wait() != KEY_START);
}
