/*
 * FreyaBIOS/FreyaOS constants for GNU as in Intel syntax.
 *
 * Derived from Wonder Witch Technical Manual (2001/2002), its legacy MASM
 * includes, Wonderful libww, and AthenaBIOS. Disputed manual values follow the
 * open implementation and are called out below.
 */

/* Software interrupt vectors. */
.equ WW_INT_EXIT,   0x10
.equ WW_INT_KEY,    0x11
.equ WW_INT_DISP,   0x12
.equ WW_INT_TEXT,   0x13
.equ WW_INT_COMM,   0x14
.equ WW_INT_SOUND,  0x15
.equ WW_INT_TIMER,  0x16
.equ WW_INT_SYSTEM, 0x17
.equ WW_INT_BANK,   0x18

/* Hardware interrupt vectors. */
.equ WW_HWINT_SEND_READY,     0x28
.equ WW_HWINT_KEY,            0x29
.equ WW_HWINT_CARTRIDGE,      0x2A
.equ WW_HWINT_RECEIVE_READY,  0x2B
.equ WW_HWINT_DISPLAY_LINE,   0x2C
.equ WW_HWINT_VBLANK_TIMER,   0x2D
.equ WW_HWINT_VBLANK,         0x2E
.equ WW_HWINT_HBLANK_TIMER,   0x2F

/* INT 11h - key services. */
.equ WW_KEY_PRESS_CHECK,           0x00
.equ WW_KEY_HIT_CHECK,             0x01
.equ WW_KEY_WAIT,                  0x02
.equ WW_KEY_SET_REPEAT,            0x03
.equ WW_KEY_GET_REPEAT,            0x04
.equ WW_KEY_HIT_CHECK_WITH_REPEAT, 0x05

.equ WW_KEY_START, 0x0002
.equ WW_KEY_A,     0x0004
.equ WW_KEY_B,     0x0008
.equ WW_KEY_X1,    0x0010
.equ WW_KEY_X2,    0x0020
.equ WW_KEY_X3,    0x0040
.equ WW_KEY_X4,    0x0080
.equ WW_KEY_Y1,    0x0100
.equ WW_KEY_Y2,    0x0200
.equ WW_KEY_Y3,    0x0400
.equ WW_KEY_Y4,    0x0800

/* INT 12h - display services. */
.equ WW_DISPLAY_CONTROL,          0x00
.equ WW_DISPLAY_STATUS,           0x01
.equ WW_FONT_SET_MONODATA,        0x02
.equ WW_FONT_SET_COLORDATA,       0x03
.equ WW_FONT_GET_DATA,            0x04
.equ WW_FONT_SET_COLOR,           0x05
.equ WW_FONT_GET_COLOR,           0x06
.equ WW_SCREEN_SET_CHAR,          0x07
.equ WW_SCREEN_GET_CHAR,          0x08
.equ WW_SCREEN_FILL_CHAR,         0x09
.equ WW_SCREEN_FILL_ATTR,         0x0A
.equ WW_SPRITE_SET_RANGE,         0x0B
.equ WW_SPRITE_SET_CHAR,          0x0C
.equ WW_SPRITE_GET_CHAR,          0x0D
.equ WW_SPRITE_SET_LOCATION,      0x0E
.equ WW_SPRITE_GET_LOCATION,      0x0F
.equ WW_SPRITE_SET_CHAR_LOCATION, 0x10
.equ WW_SPRITE_GET_CHAR_LOCATION, 0x11
.equ WW_SPRITE_SET_DATA,          0x12
.equ WW_SCREEN_SET_SCROLL,        0x13
.equ WW_SCREEN_GET_SCROLL,        0x14
.equ WW_SCREEN2_SET_WINDOW,       0x15
.equ WW_SCREEN2_GET_WINDOW,       0x16
.equ WW_SPRITE_SET_WINDOW,        0x17
.equ WW_SPRITE_GET_WINDOW,        0x18
.equ WW_PALETTE_SET_COLOR,        0x19
.equ WW_PALETTE_GET_COLOR,        0x1A
.equ WW_LCD_SET_COLOR,            0x1B
.equ WW_LCD_GET_COLOR,            0x1C
.equ WW_LCD_SET_SEGMENTS,         0x1D
.equ WW_LCD_GET_SEGMENTS,         0x1E
.equ WW_LCD_SET_SLEEP,            0x1F
.equ WW_LCD_GET_SLEEP,            0x20
.equ WW_SCREEN_SET_VRAM,          0x21
.equ WW_SPRITE_SET_VRAM,          0x22

.equ WW_DCM_SCREEN1,            0x0001
.equ WW_DCM_SCREEN2,            0x0002
.equ WW_DCM_SPRITES,            0x0004
.equ WW_DCM_SPRITE_WINDOW,      0x0008
.equ WW_DCM_SCREEN2_WIN_INSIDE, 0x0020
.equ WW_DCM_SCREEN2_WIN_OUTSIDE,0x0030
.equ WW_DCM_MONO_BORDER_MASK,   0x0700

.equ WW_TILE_INDEX_LOW_MASK, 0x01FF
.equ WW_TILE_PALETTE_SHIFT,  9
.equ WW_TILE_SCREEN_PALETTE, 0x1E00
.equ WW_TILE_SPRITE_PALETTE, 0x0E00
.equ WW_TILE_SPRITE_OUTSIDE, 0x1000
.equ WW_TILE_SPRITE_ABOVE_S2,0x2000
.equ WW_TILE_FLIP_H,         0x4000
.equ WW_TILE_FLIP_V,         0x8000

/* The legacy DISP.INC agrees with hardware/Athena: V is bit 1, H is bit 2. */
.equ WW_LCDSEG_SLEEP,     0x01
.equ WW_LCDSEG_VERTICAL,  0x02
.equ WW_LCDSEG_HORIZONTAL,0x04
.equ WW_LCDSEG_AUX1,      0x08
.equ WW_LCDSEG_AUX2,      0x10
.equ WW_LCDSEG_AUX3,      0x20

/* INT 12h/AH=1Fh bit 0: zero displays, one disables/sleeps. */
.equ WW_LCD_SLEEP_OFF, 0
.equ WW_LCD_SLEEP_ON,  1

.equ WW_LCD_PIXEL_WIDTH,    224
.equ WW_LCD_PIXEL_HEIGHT,   144
.equ WW_SCREEN_PIXEL_WIDTH, 256
.equ WW_SCREEN_PIXEL_HEIGHT,256
.equ WW_SCREEN_TILE_WIDTH,  32
.equ WW_SCREEN_TILE_HEIGHT, 32

/* INT 13h - text services and flags. */
.equ WW_TEXT_SCREEN_INIT,       0x00
.equ WW_TEXT_WINDOW_INIT,       0x01
.equ WW_TEXT_SET_MODE,          0x02
.equ WW_TEXT_GET_MODE,          0x03
.equ WW_TEXT_PUT_CHAR,          0x04
.equ WW_TEXT_PUT_STRING,        0x05
.equ WW_TEXT_PUT_SUBSTRING,     0x06
.equ WW_TEXT_PUT_NUMERIC,       0x07
.equ WW_TEXT_FILL_CHAR,         0x08
.equ WW_TEXT_SET_PALETTE,       0x09
.equ WW_TEXT_GET_PALETTE,       0x0A
.equ WW_TEXT_SET_ANK_FONT,      0x0B
.equ WW_TEXT_SET_SJIS_FONT,     0x0C
.equ WW_TEXT_GET_FONTDATA,      0x0D
.equ WW_TEXT_SET_SCREEN,        0x0E
.equ WW_TEXT_GET_SCREEN,        0x0F
.equ WW_CURSOR_DISPLAY,         0x10
.equ WW_CURSOR_STATUS,          0x11
.equ WW_CURSOR_SET_LOCATION,    0x12
.equ WW_CURSOR_GET_LOCATION,    0x13
.equ WW_CURSOR_SET_TYPE,        0x14
.equ WW_CURSOR_GET_TYPE,        0x15

.equ WW_NUM_HEX,         0x01
.equ WW_NUM_PAD_ZERO,    0x02
.equ WW_NUM_ALIGN_LEFT,  0x04
.equ WW_NUM_SIGNED,      0x08
.equ WW_NUM_STORE,       0x80
.equ WW_TEXT_MODE_ANK,      0
.equ WW_TEXT_MODE_ANK_SJIS, 1
.equ WW_TEXT_MODE_SJIS,     2
.equ WW_TEXT_SCREEN_WIDTH,  28
.equ WW_TEXT_SCREEN_HEIGHT, 18

/* INT 14h - serial services. */
.equ WW_COMM_OPEN,                 0x00
.equ WW_COMM_CLOSE,                0x01
.equ WW_COMM_SEND_CHAR,            0x02
.equ WW_COMM_RECEIVE_CHAR,         0x03
.equ WW_COMM_RECEIVE_WITH_TIMEOUT, 0x04
.equ WW_COMM_SEND_STRING,          0x05
.equ WW_COMM_SEND_BLOCK,           0x06
.equ WW_COMM_RECEIVE_BLOCK,        0x07
.equ WW_COMM_SET_TIMEOUT,          0x08
.equ WW_COMM_SET_BAUDRATE,         0x09
.equ WW_COMM_GET_BAUDRATE,         0x0A
.equ WW_COMM_SET_CANCEL_KEY,       0x0B
.equ WW_COMM_GET_CANCEL_KEY,       0x0C
.equ WW_COMM_XMODEM,               0x0D
.equ WW_COMM_SPEED_9600,  0
.equ WW_COMM_SPEED_38400, 1
.equ WW_ERR_SIO_OK,       0x0000
.equ WW_ERR_SIO_BUSY,     0x8100
.equ WW_ERR_SIO_TIMEOUT,  0x8101
.equ WW_ERR_SIO_OVERRUN,  0x8102
.equ WW_ERR_SIO_CANCEL,   0x8103

/* INT 15h - sound services. */
.equ WW_SOUND_INIT,        0x00
.equ WW_SOUND_SET_CHANNEL, 0x01
.equ WW_SOUND_GET_CHANNEL, 0x02
.equ WW_SOUND_SET_OUTPUT,  0x03
.equ WW_SOUND_GET_OUTPUT,  0x04
.equ WW_SOUND_SET_WAVE,    0x05
.equ WW_SOUND_SET_PITCH,   0x06
.equ WW_SOUND_GET_PITCH,   0x07
.equ WW_SOUND_SET_VOLUME,  0x08
.equ WW_SOUND_GET_VOLUME,  0x09
.equ WW_SOUND_SET_SWEEP,   0x0A
.equ WW_SOUND_GET_SWEEP,   0x0B
.equ WW_SOUND_SET_NOISE,   0x0C
.equ WW_SOUND_GET_NOISE,   0x0D
.equ WW_SOUND_GET_RANDOM,  0x0E

/* INT 16h - RTC/timer services. Athena/libww use set=01h, get=02h. */
.equ WW_RTC_RESET,               0x00
.equ WW_RTC_SET_DATETIME,        0x01
.equ WW_RTC_GET_DATETIME,        0x02
.equ WW_RTC_SET_DATETIME_STRUCT, 0x03
.equ WW_RTC_GET_DATETIME_STRUCT, 0x04
.equ WW_RTC_ENABLE_ALARM,        0x05
.equ WW_RTC_DISABLE_ALARM,       0x06
.equ WW_TIMER_ENABLE,            0x07
.equ WW_TIMER_DISABLE,           0x08
.equ WW_TIMER_GET_COUNT,         0x09
.equ WW_RTC_YEAR,        0
.equ WW_RTC_MONTH,       1
.equ WW_RTC_DATE,        2
.equ WW_RTC_DAY_OF_WEEK, 3
.equ WW_RTC_HOUR,        4
.equ WW_RTC_MINUTE,      5
.equ WW_RTC_SECOND,      6
.equ WW_TIMER_HBLANK,    0
.equ WW_TIMER_VBLANK,    1
.equ WW_TIMER_ONESHOT,   0
.equ WW_TIMER_AUTO,      1

/* INT 17h - system services. */
.equ WW_SYS_INTERRUPT_SET_HOOK,   0x00
.equ WW_SYS_INTERRUPT_RESET_HOOK, 0x01
.equ WW_SYS_WAIT,                 0x02
.equ WW_SYS_GET_TICK_COUNT,       0x03
.equ WW_SYS_SLEEP,                0x04
.equ WW_SYS_SET_SLEEP_TIME,       0x05
.equ WW_SYS_GET_SLEEP_TIME,       0x06
.equ WW_SYS_SET_AWAKE_KEY,        0x07
.equ WW_SYS_GET_AWAKE_KEY,        0x08
.equ WW_SYS_SET_KEEPALIVE_INT,    0x09
.equ WW_SYS_GET_OWNERINFO,        0x0A
.equ WW_SYS_SUSPEND,              0x0B
.equ WW_SYS_RESUME,               0x0C
.equ WW_SYS_SET_REMOTE,           0x0D
.equ WW_SYS_GET_REMOTE,           0x0E
.equ WW_SYS_ALLOC_IRAM,           0x0F
.equ WW_SYS_FREE_IRAM,            0x10
.equ WW_SYS_GET_MY_IRAM,          0x11
.equ WW_SYS_GET_VERSION,          0x12
.equ WW_SYS_SWAP,                 0x13
.equ WW_SYS_SET_RESUME,           0x14
.equ WW_SYS_GET_RESUME,           0x15

/* INT 18h - bank services. */
.equ WW_BANK_SET_MAP,     0x00
.equ WW_BANK_GET_MAP,     0x01
.equ WW_BANK_READ_BYTE,   0x02
.equ WW_BANK_WRITE_BYTE,  0x03
.equ WW_BANK_READ_WORD,   0x04
.equ WW_BANK_WRITE_WORD,  0x05
.equ WW_BANK_READ_BLOCK,  0x06
.equ WW_BANK_WRITE_BLOCK, 0x07
.equ WW_BANK_FILL_BLOCK,  0x08
.equ WW_BANK_ERASE_FLASH, 0x09
.equ WW_BANK_SRAM, 0
.equ WW_BANK_ROM0, 1
.equ WW_BANK_ROM1, 2
.equ WW_SEG_SRAM, 0x1000
.equ WW_SEG_ROM0, 0x2000
.equ WW_SEG_ROM1, 0x3000
.equ WW_BANK_SOFTFS, 0
.equ WW_BANK_USER1,  1
.equ WW_BANK_USER0,  2
.equ WW_BANK_OSWORK, 3
