#ifndef SWAN_SONG_WWTM_SYS_DISP_OVERLAY_H
#define SWAN_SONG_WWTM_SYS_DISP_OVERLAY_H

#include_next <sys/disp.h>

/*
 * INT 12h/AH=1Fh uses bit 0 as "LCD disabled". The stock symbolic values are
 * reversed, which makes lcd_on() turn the panel off and lcd_off() turn it on.
 * Keep the public helper names and correct the values they expand through.
 */
#undef LCD_SLEEP_ON
#undef LCD_SLEEP_OFF
#define LCD_SLEEP_OFF 0
#define LCD_SLEEP_ON 1

#endif /* SWAN_SONG_WWTM_SYS_DISP_OVERLAY_H */
