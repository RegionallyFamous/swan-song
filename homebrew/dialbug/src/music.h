// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Regionally Famous contributors

#ifndef HUMMING_CAT_REFRAIN_MUSIC_H
#define HUMMING_CAT_REFRAIN_MUSIC_H

#include <stdbool.h>
#include <stdint.h>
#include <wonderful.h>

#define DIALBUG_CHANNEL_COUNT 4
#define DIALBUG_PATTERN_ROWS 16
#define DIALBUG_MAX_ORDER 8

#define DIALBUG_NOTE_NONE 0
#define DIALBUG_NOTE_OFF 255

#define DIALBUG_NOTE(octave, semitone) \
	((uint8_t)((((octave) - 2) * 12) + (semitone) + 1))
#define C(octave)  DIALBUG_NOTE((octave), 0)
#define CS(octave) DIALBUG_NOTE((octave), 1)
#define D(octave)  DIALBUG_NOTE((octave), 2)
#define DS(octave) DIALBUG_NOTE((octave), 3)
#define E(octave)  DIALBUG_NOTE((octave), 4)
#define F(octave)  DIALBUG_NOTE((octave), 5)
#define FS(octave) DIALBUG_NOTE((octave), 6)
#define G(octave)  DIALBUG_NOTE((octave), 7)
#define GS(octave) DIALBUG_NOTE((octave), 8)
#define A(octave)  DIALBUG_NOTE((octave), 9)
#define AS(octave) DIALBUG_NOTE((octave), 10)
#define B(octave)  DIALBUG_NOTE((octave), 11)

typedef enum {
	DIALBUG_INST_LEAD = 0,
	DIALBUG_INST_PULSE,
	DIALBUG_INST_BASS,
	DIALBUG_INST_ARP_MINOR,
	DIALBUG_INST_ARP_MAJOR,
	DIALBUG_INST_BELL,
	DIALBUG_INST_PAD,
	DIALBUG_INST_KICK,
	DIALBUG_INST_SNARE,
	DIALBUG_INST_HAT,
	DIALBUG_INST_SAW,
	DIALBUG_INST_PLUCK,
	DIALBUG_INST_SWEEP,
	DIALBUG_INSTRUMENT_COUNT
} dialbug_instrument_id_t;

typedef struct {
	uint8_t note;
	uint8_t instrument;
	uint8_t volume;
	uint8_t gate_rows;
} dialbug_event_t;

typedef struct {
	dialbug_event_t row[DIALBUG_PATTERN_ROWS][DIALBUG_CHANNEL_COUNT];
} dialbug_pattern_t;

typedef struct {
	char title[24];
	char subtitle[27];
	uint16_t bpm;
	uint8_t order_length;
	uint8_t order[DIALBUG_MAX_ORDER];
} dialbug_song_t;

extern const dialbug_pattern_t __far dialbug_patterns[];
extern const dialbug_song_t __far dialbug_songs[];
extern const uint8_t dialbug_song_count;

void dialbug_music_init(void);
void dialbug_music_update(void);
void dialbug_music_select(uint8_t song_index);
void dialbug_music_restart(void);
void dialbug_music_toggle_pause(void);
void dialbug_music_set_master_volume(uint8_t volume);
void dialbug_music_set_speed_index(uint8_t speed_index);
void dialbug_music_toggle_mute(uint8_t channel);

uint8_t dialbug_music_song_index(void);
uint8_t dialbug_music_master_volume(void);
uint8_t dialbug_music_speed_index(void);
uint8_t dialbug_music_speed_percent(void);
bool dialbug_music_is_paused(void);
bool dialbug_music_is_muted(uint8_t channel);
uint8_t dialbug_music_channel_note(uint8_t channel);
uint8_t dialbug_music_channel_level(uint8_t channel);
uint8_t dialbug_music_channel_instrument(uint8_t channel);
uint16_t dialbug_music_step(void);
uint16_t dialbug_music_total_steps(void);
const dialbug_song_t __far *dialbug_music_song(void);
const char __far *dialbug_music_instrument_name(uint8_t instrument);

#endif
