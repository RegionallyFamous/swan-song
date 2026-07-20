// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Regionally Famous contributors

#ifndef SWANFRAME_MUSIC_H
#define SWANFRAME_MUSIC_H

#include <stdbool.h>
#include <stdint.h>
#include <wonderful.h>

#define SWANFRAME_CHANNEL_COUNT 4
#define SWANFRAME_PATTERN_ROWS 16
#define SWANFRAME_MAX_ORDER 8

#define SWANFRAME_NOTE_NONE 0
#define SWANFRAME_NOTE_OFF 255

#define SWANFRAME_NOTE(octave, semitone) \
	((uint8_t)((((octave) - 2) * 12) + (semitone) + 1))
#define C(octave)  SWANFRAME_NOTE((octave), 0)
#define CS(octave) SWANFRAME_NOTE((octave), 1)
#define D(octave)  SWANFRAME_NOTE((octave), 2)
#define DS(octave) SWANFRAME_NOTE((octave), 3)
#define E(octave)  SWANFRAME_NOTE((octave), 4)
#define F(octave)  SWANFRAME_NOTE((octave), 5)
#define FS(octave) SWANFRAME_NOTE((octave), 6)
#define G(octave)  SWANFRAME_NOTE((octave), 7)
#define GS(octave) SWANFRAME_NOTE((octave), 8)
#define A(octave)  SWANFRAME_NOTE((octave), 9)
#define AS(octave) SWANFRAME_NOTE((octave), 10)
#define B(octave)  SWANFRAME_NOTE((octave), 11)

typedef enum {
	SWANFRAME_INST_LEAD = 0,
	SWANFRAME_INST_PULSE,
	SWANFRAME_INST_BASS,
	SWANFRAME_INST_ARP_MINOR,
	SWANFRAME_INST_ARP_MAJOR,
	SWANFRAME_INST_BELL,
	SWANFRAME_INST_PAD,
	SWANFRAME_INST_KICK,
	SWANFRAME_INST_SNARE,
	SWANFRAME_INST_HAT,
	SWANFRAME_INST_SAW,
	SWANFRAME_INST_PLUCK,
	SWANFRAME_INST_SWEEP,
	SWANFRAME_INSTRUMENT_COUNT
} swanframe_instrument_id_t;

typedef struct {
	uint8_t note;
	uint8_t instrument;
	uint8_t volume;
	uint8_t gate_rows;
} swanframe_event_t;

typedef struct {
	swanframe_event_t row[SWANFRAME_PATTERN_ROWS][SWANFRAME_CHANNEL_COUNT];
} swanframe_pattern_t;

typedef struct {
	char title[24];
	char subtitle[27];
	uint16_t bpm;
	uint8_t order_length;
	uint8_t order[SWANFRAME_MAX_ORDER];
} swanframe_song_t;

extern const swanframe_pattern_t __far swanframe_patterns[];
extern const swanframe_song_t __far swanframe_songs[];
extern const uint8_t swanframe_song_count;

void swanframe_music_init(void);
void swanframe_music_update(void);
void swanframe_music_select(uint8_t song_index);
void swanframe_music_restart(void);
void swanframe_music_toggle_pause(void);
void swanframe_music_set_master_volume(uint8_t volume);
void swanframe_music_set_speed_index(uint8_t speed_index);
void swanframe_music_toggle_mute(uint8_t channel);

uint8_t swanframe_music_song_index(void);
uint8_t swanframe_music_master_volume(void);
uint8_t swanframe_music_speed_index(void);
uint8_t swanframe_music_speed_percent(void);
bool swanframe_music_is_paused(void);
bool swanframe_music_is_muted(uint8_t channel);
uint8_t swanframe_music_channel_note(uint8_t channel);
uint8_t swanframe_music_channel_level(uint8_t channel);
uint8_t swanframe_music_channel_instrument(uint8_t channel);
uint16_t swanframe_music_step(void);
uint16_t swanframe_music_total_steps(void);
const swanframe_song_t __far *swanframe_music_song(void);
const char __far *swanframe_music_instrument_name(uint8_t instrument);

#endif
