#ifndef SWAN_SONG_WWTM_SYS_BANK_OVERLAY_H
#define SWAN_SONG_WWTM_SYS_BANK_OVERLAY_H

/*
 * Compatibility overlay for Wonderful libww.
 *
 * The upstream header accidentally declares bank_read_word() as returning an
 * 8-bit value. Rename that declaration while importing the rest of the SDK,
 * then expose the BIOS's actual 16-bit AX result below.
 */
#define bank_read_word __wwtm_legacy_bank_read_word
#include_next <sys/bank.h>
#undef bank_read_word

/* These convenience macros must invoke the setter, not bank_get_map(). */
#undef sram_set_map
#undef rom0_set_map
#undef rom1_set_map
#define sram_set_map(bank_id) bank_set_map(BANK_SRAM, (bank_id))
#define rom0_set_map(bank_id) bank_set_map(BANK_ROM0, (bank_id))
#define rom1_set_map(bank_id) bank_set_map(BANK_ROM1, (bank_id))

/**
 * Read one little-endian word from a physical Freya bank.
 *
 * INT 18h/AH=04h returns the full word in AX. The stock libww declaration
 * uses uint8_t and silently truncates the high byte at C call sites.
 */
static inline uint16_t bank_read_word(uint16_t bank_id, uint16_t offset) {
	uint16_t result;
	__asm volatile (
		"int $0x18"
		: "=a" (result)
		: "b" (bank_id), "d" (offset), "Rah" ((uint8_t) 0x04)
		: "cc", "memory"
	);
	return result;
}

#endif /* SWAN_SONG_WWTM_SYS_BANK_OVERLAY_H */
