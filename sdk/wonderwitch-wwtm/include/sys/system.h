#ifndef SWAN_SONG_WWTM_SYS_SYSTEM_OVERLAY_H
#define SWAN_SONG_WWTM_SYS_SYSTEM_OVERLAY_H

/* Import libww while hiding its 16-bit declaration of the 32-bit tick API. */
#define sys_get_tick_count __wwtm_legacy_sys_get_tick_count
#include_next <sys/system.h>
#undef sys_get_tick_count

/**
 * Return the number of VBlank ticks elapsed since system start.
 *
 * INT 17h/AH=03h returns DX:AX. A 16-bit declaration wraps after roughly
 * 14.5 minutes at 75.47 Hz; the BIOS contract provides the full 32-bit value.
 */
static inline uint32_t sys_get_tick_count(void) {
	uint32_t result;
	__asm volatile (
		"int $0x17"
		: "=A" (result)
		: "Rah" ((uint8_t) 0x03)
		: "cc", "memory"
	);
	return result;
}

#endif /* SWAN_SONG_WWTM_SYS_SYSTEM_OVERLAY_H */
