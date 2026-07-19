#include <string.h>
#include <wonderful.h>
#include <ws.h>
#include <wse/memory.h>

#include "music.h"

enum {
	WAVE_SQUARE = 0,
	WAVE_PULSE,
	WAVE_TRIANGLE,
	WAVE_SAW,
	WAVE_SINE
};

enum {
	INST_FLAG_NONE = 0,
	INST_FLAG_NOISE = 1,
	INST_FLAG_ARP_MINOR = 2,
	INST_FLAG_ARP_MAJOR = 4,
	INST_FLAG_SWEEP = 8
};

enum {
	ENV_OFF = 0,
	ENV_ATTACK,
	ENV_DECAY,
	ENV_SUSTAIN,
	ENV_RELEASE
};

typedef struct {
	char name[7];
	uint8_t wave;
	uint8_t attack_rate;
	uint8_t decay_rate;
	uint8_t sustain;
	uint8_t release_rate;
	uint8_t pan_left;
	uint8_t pan_right;
	uint8_t vibrato_depth;
	uint8_t vibrato_speed;
	int8_t pitch_slide;
	uint8_t noise_mode;
	uint8_t flags;
} dialbug_instrument_t;

typedef struct {
	uint8_t note;
	uint8_t instrument;
	uint8_t event_volume;
	uint8_t gate_rows;
	uint8_t env_stage;
	uint8_t env_level;
	uint8_t frame;
	uint8_t meter;
	uint16_t base_frequency;
} dialbug_voice_t;

static const dialbug_instrument_t __far instruments[DIALBUG_INSTRUMENT_COUNT] = {
	{ "LEAD",  WAVE_SQUARE,   96, 5, 190, 18, 15, 10, 3, 3,   0, 0, INST_FLAG_NONE },
	{ "PULSE", WAVE_PULSE,   128, 8, 155, 24,  9, 15, 2, 4,   0, 0, INST_FLAG_NONE },
	{ "BASS",  WAVE_TRIANGLE, 72, 3, 205, 12, 12, 12, 0, 0,   0, 0, INST_FLAG_NONE },
	{ "MINARP",WAVE_PULSE,   160, 9, 135, 32,  8, 15, 0, 0,   0, 0, INST_FLAG_ARP_MINOR },
	{ "MAJARP",WAVE_PULSE,   160, 9, 135, 32, 15,  8, 0, 0,   0, 0, INST_FLAG_ARP_MAJOR },
	{ "BELL",  WAVE_SINE,    255, 7,  90, 14, 15, 13, 3, 5,   0, 0, INST_FLAG_NONE },
	{ "PAD",   WAVE_TRIANGLE, 28, 2, 175,  7, 11, 15, 2, 6,   0, 0, INST_FLAG_NONE },
	{ "KICK",  WAVE_TRIANGLE,255,18,  65, 35, 15, 15, 0, 0, -11, 0, INST_FLAG_NONE },
	{ "SNARE", WAVE_SQUARE,  255,20,  55, 42, 15, 15, 0, 0,   0,
		WS_SOUND_NOISE_CTRL_LENGTH_32767 | WS_SOUND_NOISE_CTRL_TAP_14, INST_FLAG_NOISE },
	{ "HAT",   WAVE_SQUARE,  255,32,  25, 70, 11, 15, 0, 0,   0,
		WS_SOUND_NOISE_CTRL_LENGTH_73 | WS_SOUND_NOISE_CTRL_TAP_8, INST_FLAG_NOISE },
	{ "SAW",   WAVE_SAW,      88, 7, 165, 18, 15, 11, 4, 3,   0, 0, INST_FLAG_NONE },
	{ "PLUCK", WAVE_SQUARE,   255,16, 70, 30,  9, 15, 1, 4,   0, 0, INST_FLAG_NONE },
	/* On channel 3, pitch_slide is the signed hardware sweep amount and
	 * noise_mode is the 375 Hz sweep interval minus one. */
	{ "SWEEP", WAVE_SINE,     192, 9,  96, 28, 15, 12, 0, 0,   2, 23, INST_FLAG_SWEEP }
};

/* Rounded equal-tempered note frequencies from C2 through C7. */
static const uint16_t __far note_hz[] = {
	0,
	65, 69, 73, 78, 82, 87, 92, 98, 104, 110, 117, 123,
	131, 139, 147, 156, 165, 175, 185, 196, 208, 220, 233, 247,
	262, 277, 294, 311, 330, 349, 370, 392, 415, 440, 466, 494,
	523, 554, 587, 622, 659, 698, 740, 784, 831, 880, 932, 988,
	1047, 1109, 1175, 1245, 1319, 1397, 1480, 1568, 1661, 1760, 1865, 1976,
	2093
};

static const uint8_t speed_percentages[] = { 50, 75, 100, 125, 150 };
static const uint8_t freq_ports[DIALBUG_CHANNEL_COUNT] = {
	WS_SOUND_FREQ_CH1_PORT, WS_SOUND_FREQ_CH2_PORT,
	WS_SOUND_FREQ_CH3_PORT, WS_SOUND_FREQ_CH4_PORT
};
static const uint8_t volume_ports[DIALBUG_CHANNEL_COUNT] = {
	WS_SOUND_VOL_CH1_PORT, WS_SOUND_VOL_CH2_PORT,
	WS_SOUND_VOL_CH3_PORT, WS_SOUND_VOL_CH4_PORT
};

static dialbug_voice_t voices[DIALBUG_CHANNEL_COUNT];
static uint8_t current_song;
static uint8_t current_order;
static uint8_t current_row;
static uint8_t master_volume = 6;
static uint8_t speed_index = 2;
static uint8_t mute_mask;
static bool paused;
static uint32_t tempo_accumulator;

static uint16_t note_to_frequency(uint8_t note) {
	if (note == DIALBUG_NOTE_NONE || note == DIALBUG_NOTE_OFF ||
		note >= (uint8_t)(sizeof(note_hz) / sizeof(note_hz[0]))) {
		return 0;
	}
	return WS_SOUND_WAVE_HZ_TO_FREQ(note_hz[note], 32);
}

static void fill_wave(uint8_t wave, uint8_t samples[32]) {
	static const uint8_t sine[32] = {
		8, 9, 11, 12, 13, 14, 15, 15,
		15, 15, 14, 13, 12, 11, 9, 8,
		7, 5, 4, 3, 2, 1, 0, 0,
		0, 0, 1, 2, 3, 4, 5, 7
	};
	uint8_t i;

	switch (wave) {
	case WAVE_PULSE:
		for (i = 0; i < 24; i++) samples[i] = 0;
		for (; i < 32; i++) samples[i] = 15;
		break;
	case WAVE_TRIANGLE:
		for (i = 0; i < 16; i++) samples[i] = i;
		for (; i < 32; i++) samples[i] = (uint8_t)(31 - i);
		break;
	case WAVE_SAW:
		for (i = 0; i < 32; i++) samples[i] = (uint8_t)(i & 15);
		break;
	case WAVE_SINE:
		for (i = 0; i < 32; i++) samples[i] = sine[i];
		break;
	case WAVE_SQUARE:
	default:
		for (i = 0; i < 16; i++) samples[i] = 0;
		for (; i < 32; i++) samples[i] = 15;
		break;
	}
}

static void set_channel_wave(uint8_t channel, uint8_t wave) {
	uint8_t samples[32];
	uint8_t i;
	fill_wave(wave, samples);
	for (i = 0; i < 16; i++) {
		wse_wavetable1.wave[channel].data[i] =
			(uint8_t)((samples[i * 2] & 15) | ((samples[i * 2 + 1] & 15) << 4));
	}
}

static void update_channel_control(void) {
	uint8_t control = WS_SOUND_CH_CTRL_CH1_ENABLE |
		WS_SOUND_CH_CTRL_CH2_ENABLE |
		WS_SOUND_CH_CTRL_CH3_ENABLE |
		WS_SOUND_CH_CTRL_CH4_ENABLE;
	if (instruments[voices[3].instrument].flags & INST_FLAG_NOISE) {
		control |= WS_SOUND_CH_CTRL_CH4_NOISE;
	}
	if (instruments[voices[2].instrument].flags & INST_FLAG_SWEEP) {
		control |= WS_SOUND_CH_CTRL_CH3_SWEEP;
	}
	outportb(WS_SOUND_CH_CTRL_PORT, control);
}

static void release_voice(dialbug_voice_t *voice) {
	if (voice->env_stage != ENV_OFF) voice->env_stage = ENV_RELEASE;
}

static void trigger_voice(uint8_t channel, const dialbug_event_t __far *event) {
	dialbug_voice_t *voice = &voices[channel];
	const dialbug_instrument_t __far *instrument;

	if (event->note == DIALBUG_NOTE_OFF) {
		release_voice(voice);
		return;
	}
	if (event->note == DIALBUG_NOTE_NONE || event->instrument >= DIALBUG_INSTRUMENT_COUNT) return;

	voice->note = event->note;
	voice->instrument = event->instrument;
	voice->event_volume = event->volume > 15 ? 15 : event->volume;
	voice->gate_rows = event->gate_rows;
	voice->env_level = 0;
	voice->env_stage = ENV_ATTACK;
	voice->frame = 0;
	voice->base_frequency = note_to_frequency(event->note);

	instrument = &instruments[voice->instrument];
	set_channel_wave(channel, instrument->wave);
	outportw(freq_ports[channel], voice->base_frequency);
	if (channel == 2) {
		if (instrument->flags & INST_FLAG_SWEEP) {
			outportb(WS_SOUND_SWEEP_PORT, (uint8_t)instrument->pitch_slide);
			outportb(WS_SOUND_SWEEP_TIME_PORT, instrument->noise_mode);
		} else {
			outportb(WS_SOUND_SWEEP_PORT, 0);
			outportb(WS_SOUND_SWEEP_TIME_PORT, 0);
		}
		update_channel_control();
	}

	if (channel == 3) {
		if (instrument->flags & INST_FLAG_NOISE) {
			outportb(WS_SOUND_NOISE_CTRL_PORT,
				(uint8_t)(WS_SOUND_NOISE_CTRL_ENABLE |
				WS_SOUND_NOISE_CTRL_RESET | instrument->noise_mode));
		} else {
			outportb(WS_SOUND_NOISE_CTRL_PORT, 0);
		}
		update_channel_control();
	}
}

static void process_row(void) {
	const dialbug_song_t __far *song = &dialbug_songs[current_song];
	uint8_t pattern_index = song->order[current_order];
	const dialbug_pattern_t __far *pattern = &dialbug_patterns[pattern_index];
	uint8_t channel;

	for (channel = 0; channel < DIALBUG_CHANNEL_COUNT; channel++) {
		if (voices[channel].gate_rows) {
			voices[channel].gate_rows--;
			if (!voices[channel].gate_rows) release_voice(&voices[channel]);
		}
		trigger_voice(channel, &pattern->row[current_row][channel]);
	}
}

static void advance_row(void) {
	const dialbug_song_t __far *song = &dialbug_songs[current_song];
	current_row++;
	if (current_row >= DIALBUG_PATTERN_ROWS) {
		current_row = 0;
		current_order++;
		if (current_order >= song->order_length) current_order = 0;
	}
	process_row();
}

static uint16_t voice_frequency(dialbug_voice_t *voice, const dialbug_instrument_t __far *instrument) {
	uint16_t frequency = voice->base_frequency;
	uint8_t arp_offset = 0;

	if (instrument->flags & (INST_FLAG_ARP_MINOR | INST_FLAG_ARP_MAJOR)) {
		uint8_t phase = (uint8_t)((voice->frame >> 2) % 3);
		if (phase == 1) {
			arp_offset = (instrument->flags & INST_FLAG_ARP_MINOR) ? 3 : 4;
		} else if (phase == 2) {
			arp_offset = 7;
		}
		frequency = note_to_frequency((uint8_t)(voice->note + arp_offset));
	}

	if (instrument->vibrato_depth &&
		(voice->frame & ((1u << instrument->vibrato_speed) - 1u)) >=
		(1u << (instrument->vibrato_speed - 1u))) {
		frequency = (uint16_t)(frequency + instrument->vibrato_depth);
	}
	return frequency;
}

static void update_voice(uint8_t channel) {
	dialbug_voice_t *voice = &voices[channel];
	const dialbug_instrument_t __far *instrument = &instruments[voice->instrument];
	uint8_t sustain = instrument->sustain;
	uint16_t scaled;
	uint8_t level;
	uint8_t left;
	uint8_t right;

	if (voice->env_stage == ENV_OFF) {
		voice->meter = 0;
		outportb(volume_ports[channel], 0);
		return;
	}

	switch (voice->env_stage) {
	case ENV_ATTACK:
		if ((uint16_t)voice->env_level + instrument->attack_rate >= 255) {
			voice->env_level = 255;
			voice->env_stage = ENV_DECAY;
		} else {
			voice->env_level = (uint8_t)(voice->env_level + instrument->attack_rate);
		}
		break;
	case ENV_DECAY:
		if (voice->env_level <= (uint8_t)(sustain + instrument->decay_rate)) {
			voice->env_level = sustain;
			voice->env_stage = ENV_SUSTAIN;
		} else {
			voice->env_level = (uint8_t)(voice->env_level - instrument->decay_rate);
		}
		break;
	case ENV_RELEASE:
		if (voice->env_level <= instrument->release_rate) {
			voice->env_level = 0;
			voice->env_stage = ENV_OFF;
			voice->note = DIALBUG_NOTE_NONE;
		} else {
			voice->env_level = (uint8_t)(voice->env_level - instrument->release_rate);
		}
		break;
	default:
		break;
	}

	if (instrument->pitch_slide && !(instrument->flags & INST_FLAG_SWEEP)) {
		voice->base_frequency = (uint16_t)(voice->base_frequency + instrument->pitch_slide);
	}
	if (channel != 2 || !(instrument->flags & INST_FLAG_SWEEP)) {
		outportw(freq_ports[channel], voice_frequency(voice, instrument));
	}

	scaled = (uint16_t)(voice->env_level >> 4) * voice->event_volume * master_volume;
	level = (uint8_t)(scaled / 120u);
	if (level > 15) level = 15;
	voice->meter = level;
	if (paused || (mute_mask & (1u << channel))) level = 0;

	left = (uint8_t)(((uint16_t)level * instrument->pan_left + 7u) / 15u);
	right = (uint8_t)(((uint16_t)level * instrument->pan_right + 7u) / 15u);
	outportb(volume_ports[channel], (uint8_t)((left << 4) | right));
	voice->frame++;
}

void dialbug_music_init(void) {
	uint8_t channel;
	ws_sound_reset();
	ws_sound_set_wavetable_address(&wse_wavetable1);
	outportb(WS_SOUND_OUT_CTRL_PORT,
		WS_SOUND_OUT_CTRL_SPEAKER_ENABLE |
		WS_SOUND_OUT_CTRL_HEADPHONE_ENABLE |
		WS_SOUND_OUT_CTRL_SPEAKER_VOLUME_800);
	for (channel = 0; channel < DIALBUG_CHANNEL_COUNT; channel++) {
		voices[channel].instrument = DIALBUG_INST_LEAD;
		voices[channel].env_stage = ENV_OFF;
		set_channel_wave(channel, WAVE_SQUARE);
	}
	update_channel_control();
	dialbug_music_select(0);
}

void dialbug_music_update(void) {
	const dialbug_song_t __far *song = &dialbug_songs[current_song];
	uint8_t channel;

	if (paused) {
		for (channel = 0; channel < DIALBUG_CHANNEL_COUNT; channel++) {
			outportb(volume_ports[channel], 0);
		}
		return;
	}
	for (channel = 0; channel < DIALBUG_CHANNEL_COUNT; channel++) update_voice(channel);

	/* One default frame is 40,704 clocks at 3.072 MHz (~75.472 Hz).
	 * A 16th-note step uses the exact reduced accumulator from the HCAT-style
	 * VBlank sequencer, with an additional percentage speed control. */
	tempo_accumulator += (uint32_t)song->bpm * 106UL * speed_percentages[speed_index];
	while (tempo_accumulator >= 12000000UL) {
		tempo_accumulator -= 12000000UL;
		advance_row();
	}
}

void dialbug_music_select(uint8_t song_index) {
	uint8_t channel;
	if (song_index >= dialbug_song_count) song_index = 0;
	current_song = song_index;
	current_order = 0;
	current_row = 0;
	tempo_accumulator = 0;
	paused = false;
	for (channel = 0; channel < DIALBUG_CHANNEL_COUNT; channel++) {
		memset(&voices[channel], 0, sizeof(voices[channel]));
		voices[channel].instrument = DIALBUG_INST_LEAD;
		outportb(volume_ports[channel], 0);
	}
	outportb(WS_SOUND_SWEEP_PORT, 0);
	outportb(WS_SOUND_SWEEP_TIME_PORT, 0);
	update_channel_control();
	process_row();
}

void dialbug_music_restart(void) {
	dialbug_music_select(current_song);
}

void dialbug_music_toggle_pause(void) {
	paused = !paused;
}

void dialbug_music_set_master_volume(uint8_t volume) {
	master_volume = volume > 8 ? 8 : volume;
}

void dialbug_music_set_speed_index(uint8_t new_speed_index) {
	if (new_speed_index >= (uint8_t)(sizeof(speed_percentages) / sizeof(speed_percentages[0]))) {
		new_speed_index = 0;
	}
	speed_index = new_speed_index;
}

void dialbug_music_toggle_mute(uint8_t channel) {
	if (channel < DIALBUG_CHANNEL_COUNT) mute_mask ^= (uint8_t)(1u << channel);
}

uint8_t dialbug_music_song_index(void) { return current_song; }
uint8_t dialbug_music_master_volume(void) { return master_volume; }
uint8_t dialbug_music_speed_index(void) { return speed_index; }
uint8_t dialbug_music_speed_percent(void) { return speed_percentages[speed_index]; }
bool dialbug_music_is_paused(void) { return paused; }
bool dialbug_music_is_muted(uint8_t channel) {
	return channel < DIALBUG_CHANNEL_COUNT && (mute_mask & (1u << channel));
}
uint8_t dialbug_music_channel_note(uint8_t channel) {
	return channel < DIALBUG_CHANNEL_COUNT ? voices[channel].note : DIALBUG_NOTE_NONE;
}
uint8_t dialbug_music_channel_level(uint8_t channel) {
	return channel < DIALBUG_CHANNEL_COUNT ? voices[channel].meter : 0;
}
uint8_t dialbug_music_channel_instrument(uint8_t channel) {
	return channel < DIALBUG_CHANNEL_COUNT ? voices[channel].instrument : 0;
}
uint16_t dialbug_music_step(void) {
	return (uint16_t)current_order * DIALBUG_PATTERN_ROWS + current_row;
}
uint16_t dialbug_music_total_steps(void) {
	return (uint16_t)dialbug_songs[current_song].order_length * DIALBUG_PATTERN_ROWS;
}
const dialbug_song_t __far *dialbug_music_song(void) { return &dialbug_songs[current_song]; }
const char __far *dialbug_music_instrument_name(uint8_t instrument) {
	return instruments[instrument < DIALBUG_INSTRUMENT_COUNT ? instrument : 0].name;
}
