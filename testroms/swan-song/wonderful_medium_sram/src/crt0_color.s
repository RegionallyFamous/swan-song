/**
 * Copyright (c) 2022, 2023 Adrian "asie" Siekierka
 *
 * This software is provided 'as-is', without any express or implied
 * warranty. In no event will the authors be held liable for any damages
 * arising from the use of this software.
 *
 * Permission is granted to anyone to use this software for any purpose,
 * including commercial applications, and to alter it and redistribute it
 * freely, subject to the following restrictions:
 *
 * 1. The origin of this software must not be misrepresented; you must not
 *    claim that you wrote the original software. If you use this software
 *    in a product, an acknowledgment in the product documentation would be
 *    appreciated but is not required.
 *
 * 2. Altered source versions must be plainly marked as such, and must not be
 *    misrepresented as being the original software.
 *
 * 3. This notice may not be removed or altered from any source distribution.
 *
 * Swan Song alteration, 2026: this Color-only medium-SRAM probe verifies the
 * physical Color-model bit and enables System Control 2 bit 7 before selecting
 * SP=8000h or making any stack access. Wonderful 0.2.0's stock medium-SRAM CRT
 * selects that high stack but resets the system to mono mode before its first
 * push. All other startup behavior remains pinned to upstream d7d97ce.
 */

#define SRAM 1

	.arch	i186
	.code16
	.intel_syntax noprefix

	.section .start, "ax"
	.global _start
_start:
	cli

	// This fixture requires physical Color hardware and its upper IRAM.
	in	al, 0xA0
	test	al, 0x02
	jnz	_start_enable_color
_start_requires_color:
	hlt
	jmp	_start_requires_color
_start_enable_color:
	in	al, 0x60
	and	al, 0x1F
	or	al, 0x80
	out	0x60, al

#ifdef SRAM
	mov	ax, 0x1000
	mov	es, ax
#endif
	// set DS:SI to the location of the data block
	.reloc	.+1, R_386_SEG16, "__wf_data_block!"
	mov	ax, 0
	mov	ds, ax
	mov	si, offset "__wf_data_block"

	// configure SP, ES, SS, flags
	mov	sp, offset "__wf_heap_top"
	xor	ax, ax
#ifndef SRAM
	mov	es, ax
#endif
	mov	ss, ax
	cld

_start_parse_data_block:
	lodsw
	test ax, ax
	jz _start_finish_data_block
	mov cx, ax
	lodsw
	mov	di, ax
	lodsw
#ifndef SRAM
	cmp	di, 0x4000
	jb	_start_parse_data_block_non_wsc

	// data block requests WSC mode?
	in	al, 0xA0
	test	al, 0x02
	// if the console is not color, skip the block entirely
	jz	_start_parse_data_block
	// initialize WSC mode
	in	al, 0x60
	or	al, 0x80
	out	0x60, al

_start_parse_data_block_non_wsc:
#endif
	test	ah, 0x80
	jnz	_start_data_block_clear

_start_data_block_move:
	shr	cx, 1
	rep	movsw
	jnc	_start_parse_data_block
	movsb
	jmp	_start_parse_data_block

_start_data_block_clear:
	xor	ax, ax
	shr	cx, 1
	rep	stosw
	jnc	_start_parse_data_block
	stosb
	jmp	_start_parse_data_block

_start_finish_data_block:

	// clear int enable
	out	0xB2, al

	// configure default interrupt base
	mov	al, 0x08
	out	0xB0, al

	// Color mode was enabled before selecting SP=8000h; do not clear it here.

	// initialize DS
	push	es
	pop	ds

	// run constructors
	.reloc	.+1, R_386_SEG16, "__init_array_start!"
	mov ax, 0
	mov es, ax
	mov si, offset __init_array_start
	mov di, offset __init_array_end
	call _start_run_array

#ifdef __IA16_CMODEL_IS_FAR_TEXT
	.reloc	.+3, R_386_SEG16, "main!"
	jmp 0:main
#else
	jmp main
#endif

_start_run_array:
1:
	cmp si, di
	jae 9f
#ifdef __IA16_CMODEL_IS_FAR_TEXT
	es lcall [si]
	add si, 4
#else
	es call [si]
	inc si
	inc si
#endif
	jmp 1b
9:
	ret

	// .section .fartext.exit, "ax"
	.global _exit
_exit:
	// run destructors
	.reloc	.+1, R_386_SEG16, "__fini_array_start!"
	mov ax, 0
	mov es, ax
	mov si, offset __fini_array_start
	mov di, offset __fini_array_end
	call _start_run_array

1:
	jmp 1b
