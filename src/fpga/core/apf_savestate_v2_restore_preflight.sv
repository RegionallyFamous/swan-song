`timescale 1ns/1ps
`default_nettype none

// Full-image structural, integrity, profile-padding, and RTC/EEPROM-device
// preflight for a future Memories-v2 A4 image.
//
// This module is deliberately absent from ap_core.qsf.  It does not make
// Memories available and it never drives a live device-load port.  Its only
// authority is to publish staged_image_valid/generation after an exact,
// immutable 0x120100-byte image has passed the checks implemented here.
// CPU, PPU, APU, mapper, scheduler, DMA, and live-I/O state remain opaque;
// their future per-section semantic validators are required as an additional
// gate before this signal may authorize a production live restore.
//
// copy_word_valid and copy_word_ready authorize one atomic durable commit:
// header words are retained here and a payload word must complete in the
// external staging backend on that same accepted edge. The frontend must hold
// offset/data/error until ready and must never mutate storage before accept.
// Payload storage is addressed relative to payload offset zero even though
// copy_word_offset is relative to the complete APF blob.
//
// Only one backend read may be outstanding.  A replacement offset-zero word
// is accepted during validation when image_lock is low; the old read is then
// aborted and drained before any following replacement word is accepted.
// image_lock must come from apf_savestate_v2_owner.staged_image_lock and the
// bridge frontend must use copy_word_ready to prevent writes while it is high.
module apf_savestate_v2_restore_preflight #(
    // Every backend wait is bounded independently.  Production integration
    // must derive this value from the CDC, SDRAM arbiter/refresh, and abort
    // drain bounds.  The default is intentionally unusable as a production
    // claim, matching the isolated owner's fail-closed convention.
    parameter integer MAX_BACKEND_WAIT_CYCLES = 1
) (
    input  wire         clk,
    input  wire         reset_n,

    input  wire         abort,
    input  wire         image_lock,
    // Pulse for any staging mutation not represented by copy_word_accept,
    // including the A0 capture writer. A shared physical store must connect
    // every writer here; alternatively capture and restore need separate RAM.
    input  wire         stage_content_changed,

    input  wire         copy_word_valid,
    output wire         copy_word_ready,
    input  wire [31:0]  copy_word_offset,
    input  wire [31:0]  copy_word_data,
    input  wire         copy_word_error,
    input  wire         copy_finalize,
    output wire         copy_active,

    output wire         preflight_busy,
    // done/failed are internal one-cycle terminal pulses. The future 00A4
    // command frontend must latch exactly one terminal result until Pocket's
    // polling lifecycle consumes it or a new offset-zero transaction begins;
    // these pulses must never drive APF result bits directly.
    output reg          preflight_done,
    output reg          preflight_failed,
    output reg  [3:0]   failure_reason,
    output reg          protocol_error,

    output reg          staged_image_valid,
    output reg  [31:0]  staged_image_generation,

    // Identity of the currently loaded title/machine.  Footer and ABI vectors
    // are in normalized order: the byte at the lowest offset is in the most
    // significant byte of the vector.
    input  wire [31:0]  current_rom_bytes,
    input  wire [63:0]  current_rom_crc64,
    input  wire [127:0] current_rom_footer,
    input  wire [7:0]   current_model,
    input  wire [7:0]   current_mapper,
    input  wire [7:0]   current_ramtype,
    input  wire [7:0]   current_active_bios,
    input  wire [63:0]  current_active_bios_crc64,
    input  wire [31:0]  current_settings,
    // Must remain low until a bounded MBM29DL400 controller and its exact
    // semantic state schema exist. Mapper identity alone is insufficient.
    input  wire         current_flash_supported,

    // Abstract payload-stage reader. transfer_start is a valid level, accepted
    // only with transfer_start_ready, and authoritatively clears a sticky
    // failure from the preceding reader transaction. A new failure cannot
    // belong to this transaction until after that accepted edge. Request and
    // response channels use ordinary ready/valid semantics; response
    // offset/data must remain stable until read_word_ready.
    output wire         stage_transfer_start,
    input  wire         stage_transfer_start_ready,
    output wire         stage_abort,
    // quiescent must cover every accepted request, response, and late backend
    // terminal.  It is the definitive end-of-transfer observation after the
    // final accepted response; merely receiving the last word is insufficient.
    input  wire         stage_quiescent,
    input  wire         stage_transfer_failed,
    output wire         read_request_valid,
    input  wire         read_request_ready,
    output wire [31:0]  read_request_offset,
    input  wire         read_word_valid,
    output wire         read_word_ready,
    input  wire [31:0]  read_word_offset,
    input  wire [31:0]  read_word
);
  import apf_savestate_v2_layout_pkg::*;
  import apf_savestate_v2_device_abi_pkg::*;

  localparam [3:0] FAILURE_NONE             = 4'd0;
  localparam [3:0] FAILURE_COPY_ORDER       = 4'd1;
  localparam [3:0] FAILURE_COPY_LENGTH      = 4'd2;
  localparam [3:0] FAILURE_COPY_BACKEND     = 4'd3;
  localparam [3:0] FAILURE_HEADER_FIELDS    = 4'd4;
  localparam [3:0] FAILURE_HEADER_CRC       = 4'd5;
  localparam [3:0] FAILURE_STAGE_BACKEND    = 4'd6;
  localparam [3:0] FAILURE_STAGE_ORDER      = 4'd7;
  localparam [3:0] FAILURE_PAYLOAD_ZERO     = 4'd8;
  localparam [3:0] FAILURE_PAYLOAD_CRC      = 4'd9;
  localparam [3:0] FAILURE_RTC              = 4'd10;
  localparam [3:0] FAILURE_INTERNAL_EEPROM  = 4'd11;
  localparam [3:0] FAILURE_CART_EEPROM      = 4'd12;
  localparam [3:0] FAILURE_ABORT            = 4'd13;
  localparam [3:0] FAILURE_STAGE_CHANGED    = 4'd14;

  localparam [4:0] STATE_EMPTY              = 5'd0;
  localparam [4:0] STATE_COPY               = 5'd1;
  localparam [4:0] STATE_COPY_DRAIN         = 5'd2;
  localparam [4:0] STATE_WAIT_STAGE_DRAIN   = 5'd3;
  localparam [4:0] STATE_HEADER_FIELDS      = 5'd4;
  localparam [4:0] STATE_HEADER_CRC_CLEAR   = 5'd5;
  localparam [4:0] STATE_HEADER_CRC_STREAM  = 5'd6;
  localparam [4:0] STATE_HEADER_CRC_CHECK   = 5'd7;
  localparam [4:0] STATE_STAGE_START        = 5'd8;
  localparam [4:0] STATE_PAYLOAD_CRC_CLEAR  = 5'd9;
  localparam [4:0] STATE_READ_REQUEST       = 5'd10;
  localparam [4:0] STATE_READ_RESPONSE      = 5'd11;
  localparam [4:0] STATE_PAYLOAD_CHECK      = 5'd12;
  localparam [4:0] STATE_FAIL_DRAIN         = 5'd13;
  localparam [4:0] STATE_VALID              = 5'd14;

  reg [4:0] state;
  reg [4:0] previous_state;
  reg [31:0] expected_copy_offset;
  reg [31:0] payload_offset;
  reg [5:0] header_crc_word_index;
  integer backend_wait_cycles;
  reg backend_failure_seen;
  reg [31:0] header_words [0:63];

  reg payload_zero_valid;
  reg rtc_words_valid;
  reg internal_eeprom_words_valid;
  reg cart_eeprom_words_valid;
  reg [255:0] rtc_image;
  reg [31:0] internal_eeprom_word0;
  reg [31:0] internal_eeprom_word1;
  reg [31:0] internal_eeprom_word2;
  reg [31:0] internal_eeprom_word3;
  reg [31:0] cart_eeprom_word0;
  reg [31:0] cart_eeprom_word1;
  reg [31:0] cart_eeprom_word2;
  reg [31:0] cart_eeprom_word3;

  wire copy_accept = copy_word_valid && copy_word_ready;
  wire replacement_accept = copy_accept && copy_word_offset == 32'd0;
  wire final_copy_word = copy_accept &&
                         copy_word_offset == V2_TOTAL_BYTES - 32'd4;
  wire exact_finalize = copy_finalize &&
      ((expected_copy_offset == V2_TOTAL_BYTES) || final_copy_word);

  wire validating = state >= STATE_WAIT_STAGE_DRAIN &&
                    state <= STATE_PAYLOAD_CHECK;
  wire backend_wait_state =
      state == STATE_COPY_DRAIN || state == STATE_WAIT_STAGE_DRAIN ||
      state == STATE_STAGE_START || state == STATE_READ_REQUEST ||
      state == STATE_READ_RESPONSE || state == STATE_PAYLOAD_CHECK ||
      state == STATE_FAIL_DRAIN;
  wire backend_wait_timeout = MAX_BACKEND_WAIT_CYCLES > 0 &&
      backend_wait_cycles >= MAX_BACKEND_WAIT_CYCLES - 1;
  assign copy_active = state == STATE_COPY || state == STATE_COPY_DRAIN;
  assign preflight_busy = validating || state == STATE_FAIL_DRAIN;

  // During validation only offset zero may replace the image.  It invalidates
  // the old generation immediately, then drains the outstanding backend read.
  assign copy_word_ready = !image_lock && !stage_content_changed &&
                           state != STATE_COPY_DRAIN &&
                           state != STATE_FAIL_DRAIN;

  assign stage_transfer_start = state == STATE_STAGE_START && !abort &&
                                !copy_accept &&
                                !copy_finalize &&
                                !stage_content_changed &&
                                compatibility_still_valid;
  assign stage_abort = state == STATE_COPY_DRAIN ||
                       state == STATE_FAIL_DRAIN;
  assign read_request_valid = state == STATE_READ_REQUEST && !abort &&
                              !copy_accept &&
                              !copy_finalize &&
                              !stage_content_changed &&
                              !stage_transfer_failed &&
                              !backend_failure_seen &&
                              compatibility_still_valid;
  assign read_request_offset = payload_offset;
  assign read_word_ready = state == STATE_READ_RESPONSE && !abort &&
                           !copy_accept &&
                           !copy_finalize &&
                           !stage_content_changed &&
                           !stage_transfer_failed &&
                           !backend_failure_seen &&
                           compatibility_still_valid;

  wire [31:0] header_flags = header_words[6];
  wire [31:0] header_identity = header_words[9];
  wire [7:0] header_model = header_identity[31:24];
  wire [7:0] header_ramtype = header_identity[15:8];
  wire [63:0] stored_rom_crc = {header_words[12], header_words[13]};
  wire [63:0] stored_active_bios_crc = {header_words[14], header_words[15]};
  wire [63:0] stored_mono_bios_crc = {header_words[16], header_words[17]};
  wire [63:0] stored_color_bios_crc = {header_words[18], header_words[19]};
  wire [63:0] stored_capture_epoch = {header_words[20], header_words[21]};
  wire [63:0] stored_payload_crc = {header_words[22], header_words[23]};
  wire [127:0] stored_footer = {
      header_words[29], header_words[30], header_words[31], header_words[32]
  };
  wire [127:0] stored_abi_id = {
      header_words[33], header_words[34], header_words[35], header_words[36]
  };
  wire [63:0] stored_header_crc = {header_words[62], header_words[63]};

  reg header_reserved_zero;
  integer header_reserved_index;
  always @* begin
    header_reserved_zero = header_words[7] == 32'd0;
    for (header_reserved_index = 43; header_reserved_index <= 61;
         header_reserved_index = header_reserved_index + 1)
      if (header_words[header_reserved_index] != 32'd0)
        header_reserved_zero = 1'b0;
  end

  wire rtc_policy_valid =
      (header_words[42] == V2_RTC_EXACT ||
       header_words[42] == V2_RTC_ADVANCE) &&
      (!header_flags[5] || stored_capture_epoch != 64'd0) &&
      (header_flags[5] ||
       (stored_capture_epoch == 64'd0 &&
        header_words[42] == V2_RTC_EXACT)) &&
      (header_words[42] != V2_RTC_ADVANCE || header_flags[5]) &&
      (header_flags[2] || header_words[42] == V2_RTC_EXACT);

  wire active_bios_diagnostic_consistent =
      (header_identity[7:0] == V2_BIOS_MONO &&
       stored_active_bios_crc == stored_mono_bios_crc) ||
      (header_identity[7:0] == V2_BIOS_COLOR &&
       stored_active_bios_crc == stored_color_bios_crc);

  wire header_fields_valid =
      v2_static_header_valid(
          header_words[0], header_words[1], header_words[2],
          header_words[3], header_words[4], header_words[5]) &&
      v2_feature_identity_valid(header_flags, header_identity) &&
      header_identity == {current_model, current_mapper, current_ramtype,
                          current_active_bios} &&
      v2_active_sizes_valid(
          header_flags, header_identity, header_words[24], header_words[25],
          header_words[26], header_words[27], header_words[28]) &&
      header_words[8] == current_rom_bytes &&
      stored_rom_crc == current_rom_crc64 &&
      stored_footer == current_rom_footer &&
      stored_active_bios_crc == current_active_bios_crc64 &&
      active_bios_diagnostic_consistent &&
      header_words[10] == V2_SETTINGS_HARD_MATCH &&
      (header_words[11] & ~V2_SETTINGS_ALLOWED) == 32'd0 &&
      ((header_words[11] ^ current_settings) &
       V2_SETTINGS_HARD_MATCH) == 32'd0 &&
      stored_abi_id == V2_ABI_ID &&
      (!header_flags[3] || current_flash_supported) &&
      header_words[37] == V2_CPU_SCHEMA &&
      header_words[38] == V2_PPU_SCHEMA &&
      header_words[39] == V2_APU_SCHEMA &&
      header_words[40] == V2_DEVICE_SCHEMA &&
      header_words[41] == V2_CAPTURE_POLICY &&
      rtc_policy_valid && header_reserved_zero;

  // Close the title/BIOS/settings TOCTOU window across the complete payload
  // scan and the later interval in which the owner may accept restore.  The
  // inactive BIOS CRC and soft/presentation settings remain diagnostic by the
  // fixed header/device contract; every hard compatibility input is compared
  // continuously.
  wire compatibility_still_valid =
      header_words[8] == current_rom_bytes &&
      stored_rom_crc == current_rom_crc64 &&
      stored_footer == current_rom_footer &&
      header_identity == {current_model, current_mapper, current_ramtype,
                          current_active_bios} &&
      stored_active_bios_crc == current_active_bios_crc64 &&
      ((header_words[11] ^ current_settings) &
       V2_SETTINGS_HARD_MATCH) == 32'd0 &&
      (!header_flags[3] || current_flash_supported);

  // A profile-required zero is checked byte-for-byte.  Device-controller
  // section tails are additional fixed zero padding not represented by the
  // top-level memory-tail helper.
  function automatic word_zero_padding_valid;
    input [31:0] offset;
    input [31:0] value;
    input [7:0] model;
    input [7:0] ramtype;
    input [31:0] flags;
    integer byte_index;
    reg required_zero;
    begin
      word_zero_padding_valid = 1'b1;
      for (byte_index = 0; byte_index < 4; byte_index = byte_index + 1) begin
        required_zero = v2_payload_byte_requires_zero(
            offset + byte_index, model, ramtype, flags) ||
            range_contains(offset + byte_index,
                           P_RTC + RTC_ACTIVE_BYTES,
                           P_RTC_BYTES - RTC_ACTIVE_BYTES) ||
            range_contains(offset + byte_index,
                           P_INTERNAL_EEPROM_CTRL + EEPROM_ACTIVE_BYTES,
                           P_INTERNAL_EEPROM_CTRL_BYTES -
                               EEPROM_ACTIVE_BYTES) ||
            range_contains(offset + byte_index,
                           P_CART_EEPROM_CTRL + EEPROM_ACTIVE_BYTES,
                           P_CART_EEPROM_CTRL_BYTES - EEPROM_ACTIVE_BYTES);
        if (required_zero && value[31 - byte_index * 8 -: 8] != 8'd0)
          word_zero_padding_valid = 1'b0;
      end
    end
  endfunction

  wire header_crc_clear = state == STATE_HEADER_CRC_CLEAR;
  wire header_crc_enable = state == STATE_HEADER_CRC_STREAM;
  wire [63:0] calculated_header_crc;
  apf_crc64_ecma32 header_crc_engine (
      .clk(clk),
      .reset_n(reset_n),
      .clear(header_crc_clear),
      .enable(header_crc_enable),
      .blob_word(header_words[header_crc_word_index]),
      .byte_count(3'd4),
      .crc_value(calculated_header_crc)
  );

  wire payload_crc_clear = state == STATE_PAYLOAD_CRC_CLEAR;
  wire payload_crc_enable = state == STATE_READ_RESPONSE &&
                            read_word_valid && !stage_transfer_failed &&
                            read_word_offset == payload_offset;
  wire [63:0] calculated_payload_crc;
  apf_crc64_ecma32 payload_crc_engine (
      .clk(clk),
      .reset_n(reset_n),
      .clear(payload_crc_clear),
      .enable(payload_crc_enable),
      .blob_word(read_word),
      .byte_count(3'd4),
      .crc_value(calculated_payload_crc)
  );

  wire [127:0] internal_eeprom_image = v2_eeprom_image_from_words(
      internal_eeprom_word0, internal_eeprom_word1,
      internal_eeprom_word2, internal_eeprom_word3);
  wire [127:0] cart_eeprom_image = v2_eeprom_image_from_words(
      cart_eeprom_word0, cart_eeprom_word1,
      cart_eeprom_word2, cart_eeprom_word3);

  integer reset_index;
  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      state <= STATE_EMPTY;
      previous_state <= STATE_EMPTY;
      expected_copy_offset <= 32'd0;
      payload_offset <= 32'd0;
      header_crc_word_index <= 6'd0;
      backend_wait_cycles <= 0;
      backend_failure_seen <= 1'b0;
      payload_zero_valid <= 1'b1;
      rtc_words_valid <= 1'b1;
      internal_eeprom_words_valid <= 1'b1;
      cart_eeprom_words_valid <= 1'b1;
      rtc_image <= 256'd0;
      internal_eeprom_word0 <= 32'd0;
      internal_eeprom_word1 <= 32'd0;
      internal_eeprom_word2 <= 32'd0;
      internal_eeprom_word3 <= 32'd0;
      cart_eeprom_word0 <= 32'd0;
      cart_eeprom_word1 <= 32'd0;
      cart_eeprom_word2 <= 32'd0;
      cart_eeprom_word3 <= 32'd0;
      preflight_done <= 1'b0;
      preflight_failed <= 1'b0;
      failure_reason <= FAILURE_NONE;
      protocol_error <= 1'b0;
      staged_image_valid <= 1'b0;
      staged_image_generation <= 32'd0;
      for (reset_index = 0; reset_index < 64;
           reset_index = reset_index + 1)
        header_words[reset_index] <= 32'd0;
    end else begin
      preflight_done <= 1'b0;
      preflight_failed <= 1'b0;
      previous_state <= state;
      if (backend_wait_state && state == previous_state)
        backend_wait_cycles <= backend_wait_cycles + 1;
      else
        backend_wait_cycles <= 0;
      if ((state == STATE_PAYLOAD_CRC_CLEAR ||
           state == STATE_READ_REQUEST || state == STATE_READ_RESPONSE ||
           state == STATE_PAYLOAD_CHECK) && stage_transfer_failed)
        backend_failure_seen <= 1'b1;

      if (copy_word_valid && image_lock)
        protocol_error <= 1'b1;
      if (copy_finalize && image_lock)
        protocol_error <= 1'b1;
      if (copy_finalize && !image_lock && state != STATE_COPY)
        protocol_error <= 1'b1;

      if (abort) begin
        staged_image_valid <= 1'b0;
        expected_copy_offset <= 32'd0;
        failure_reason <= FAILURE_ABORT;
        preflight_failed <= validating || state == STATE_COPY ||
                            state == STATE_COPY_DRAIN ||
                            state == STATE_WAIT_STAGE_DRAIN;
        if (stage_quiescent)
          state <= STATE_EMPTY;
        else
          state <= STATE_FAIL_DRAIN;
      end else if (stage_content_changed) begin
        staged_image_valid <= 1'b0;
        failure_reason <= FAILURE_STAGE_CHANGED;
        preflight_failed <= validating || state == STATE_VALID ||
                            state == STATE_COPY ||
                            state == STATE_COPY_DRAIN;
        if (state == STATE_FAIL_DRAIN && !stage_quiescent) begin
          state <= STATE_FAIL_DRAIN;
        end else if (state != STATE_EMPTY && state != STATE_VALID &&
                     !stage_quiescent) begin
          // Drain is monotonic for every active A4 copy/validation phase.
          state <= STATE_FAIL_DRAIN;
        end else begin
          state <= STATE_EMPTY;
        end
      end else if (replacement_accept) begin
        // Offset zero is the only legal image replacement marker.
        staged_image_valid <= 1'b0;
        failure_reason <= FAILURE_NONE;
        backend_failure_seen <= 1'b0;
        header_words[0] <= copy_word_data;
        expected_copy_offset <= 32'd4;
        if (copy_word_error) begin
          failure_reason <= FAILURE_COPY_BACKEND;
          preflight_failed <= 1'b1;
          state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
        end else if (copy_finalize) begin
          failure_reason <= FAILURE_COPY_LENGTH;
          preflight_failed <= 1'b1;
          if (!stage_quiescent)
            state <= STATE_FAIL_DRAIN;
          else
            state <= STATE_EMPTY;
        end else if (stage_quiescent) begin
          state <= STATE_COPY;
        end else begin
          state <= STATE_COPY_DRAIN;
        end
      end else if (copy_accept && state != STATE_COPY) begin
        // A4 must begin at offset zero. Accept malformed notifications so the
        // host cannot be backpressured forever, but invalidate any old image
        // because an atomic payload commit may already have changed storage.
        staged_image_valid <= 1'b0;
        failure_reason <= copy_word_error ? FAILURE_COPY_BACKEND :
                                            FAILURE_COPY_ORDER;
        preflight_failed <= 1'b1;
        if (!stage_quiescent)
          state <= STATE_FAIL_DRAIN;
        else
          state <= STATE_EMPTY;
      end else if (copy_finalize && !image_lock && state != STATE_COPY) begin
        staged_image_valid <= 1'b0;
        failure_reason <= FAILURE_COPY_LENGTH;
        preflight_failed <= 1'b1;
        if (!stage_quiescent)
          state <= STATE_FAIL_DRAIN;
        else
          state <= STATE_EMPTY;
      end else if (((validating && state != STATE_HEADER_FIELDS) ||
                    state == STATE_VALID) &&
                   !compatibility_still_valid) begin
        staged_image_valid <= 1'b0;
        failure_reason <= FAILURE_HEADER_FIELDS;
        preflight_failed <= 1'b1;
        if (stage_quiescent)
          state <= STATE_EMPTY;
        else
          state <= STATE_FAIL_DRAIN;
      end else begin
        case (state)
          STATE_EMPTY: begin
            if (copy_finalize) begin
              failure_reason <= FAILURE_COPY_LENGTH;
              preflight_failed <= 1'b1;
            end
          end

          STATE_COPY_DRAIN: begin
            if (stage_quiescent)
              state <= STATE_COPY;
            else if (backend_wait_timeout) begin
              failure_reason <= FAILURE_STAGE_BACKEND;
              preflight_failed <= 1'b1;
              protocol_error <= 1'b1;
              // An unproved drain cannot be released. Keep stage_abort high
              // until the backend eventually reports definitive quiescence.
              state <= STATE_FAIL_DRAIN;
            end
          end

          STATE_COPY: begin
            if (copy_accept) begin
              if (copy_word_error) begin
                staged_image_valid <= 1'b0;
                failure_reason <= FAILURE_COPY_BACKEND;
                preflight_failed <= 1'b1;
                state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
              end else if (copy_word_offset != expected_copy_offset ||
                           copy_word_offset >= V2_TOTAL_BYTES ||
                           copy_word_offset[1:0] != 2'b00) begin
                staged_image_valid <= 1'b0;
                failure_reason <= FAILURE_COPY_ORDER;
                preflight_failed <= 1'b1;
                state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
              end else begin
                expected_copy_offset <= expected_copy_offset + 32'd4;
                if (copy_word_offset < V2_HEADER_BYTES)
                  header_words[copy_word_offset[7:2]] <= copy_word_data;
              end
            end

            if (copy_finalize) begin
              if (exact_finalize &&
                  !(copy_accept && copy_word_error) &&
                  !(copy_accept &&
                    (copy_word_offset != expected_copy_offset ||
                     copy_word_offset >= V2_TOTAL_BYTES ||
                     copy_word_offset[1:0] != 2'b00))) begin
                state <= STATE_WAIT_STAGE_DRAIN;
              end else begin
                staged_image_valid <= 1'b0;
                failure_reason <= FAILURE_COPY_LENGTH;
                preflight_failed <= 1'b1;
                state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
              end
            end
          end

          STATE_WAIT_STAGE_DRAIN: begin
            if (copy_finalize)
              protocol_error <= 1'b1;
            if (stage_quiescent)
              state <= STATE_HEADER_FIELDS;
            else if (backend_wait_timeout) begin
              failure_reason <= FAILURE_STAGE_BACKEND;
              preflight_failed <= 1'b1;
              state <= STATE_FAIL_DRAIN;
            end
          end

          STATE_HEADER_FIELDS: begin
            if (!header_fields_valid) begin
              failure_reason <= FAILURE_HEADER_FIELDS;
              preflight_failed <= 1'b1;
              state <= STATE_EMPTY;
            end else begin
              header_crc_word_index <= 6'd0;
              state <= STATE_HEADER_CRC_CLEAR;
            end
          end

          STATE_HEADER_CRC_CLEAR: begin
            state <= STATE_HEADER_CRC_STREAM;
          end

          STATE_HEADER_CRC_STREAM: begin
            if (header_crc_word_index == 6'd61)
              state <= STATE_HEADER_CRC_CHECK;
            else
              header_crc_word_index <= header_crc_word_index + 1'b1;
          end

          STATE_HEADER_CRC_CHECK: begin
            if (calculated_header_crc != stored_header_crc) begin
              failure_reason <= FAILURE_HEADER_CRC;
              preflight_failed <= 1'b1;
              state <= STATE_EMPTY;
            end else begin
              state <= STATE_STAGE_START;
            end
          end

          STATE_STAGE_START: begin
            // transfer_start is also the reader's authoritative stale-failure
            // clear. A prior transaction may leave transfer_failed high until
            // this accepted edge; only failures observed after acceptance
            // belong to the new preflight.
            if (stage_transfer_start_ready) begin
              backend_failure_seen <= 1'b0;
              payload_offset <= 32'd0;
              payload_zero_valid <= 1'b1;
              rtc_words_valid <= 1'b1;
              internal_eeprom_words_valid <= 1'b1;
              cart_eeprom_words_valid <= 1'b1;
              rtc_image <= 256'd0;
              internal_eeprom_word0 <= 32'd0;
              internal_eeprom_word1 <= 32'd0;
              internal_eeprom_word2 <= 32'd0;
              internal_eeprom_word3 <= 32'd0;
              cart_eeprom_word0 <= 32'd0;
              cart_eeprom_word1 <= 32'd0;
              cart_eeprom_word2 <= 32'd0;
              cart_eeprom_word3 <= 32'd0;
              state <= STATE_PAYLOAD_CRC_CLEAR;
            end else if (backend_wait_timeout) begin
              failure_reason <= FAILURE_STAGE_BACKEND;
              preflight_failed <= 1'b1;
              state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
            end
          end

          STATE_PAYLOAD_CRC_CLEAR: begin
            state <= STATE_READ_REQUEST;
          end

          STATE_READ_REQUEST: begin
            if (stage_transfer_failed || backend_failure_seen) begin
              failure_reason <= FAILURE_STAGE_BACKEND;
              preflight_failed <= 1'b1;
              state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
            end else if (read_request_ready) begin
              state <= STATE_READ_RESPONSE;
            end else if (backend_wait_timeout) begin
              failure_reason <= FAILURE_STAGE_BACKEND;
              preflight_failed <= 1'b1;
              state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
            end
          end

          STATE_READ_RESPONSE: begin
            if (stage_transfer_failed || backend_failure_seen) begin
              failure_reason <= FAILURE_STAGE_BACKEND;
              preflight_failed <= 1'b1;
              state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
            end else if (read_word_valid) begin
              if (read_word_offset != payload_offset) begin
                failure_reason <= FAILURE_STAGE_ORDER;
                preflight_failed <= 1'b1;
                state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
              end else begin
                if (!word_zero_padding_valid(payload_offset, read_word,
                    header_model, header_ramtype, header_flags))
                  payload_zero_valid <= 1'b0;

                if (payload_offset >= P_RTC &&
                    payload_offset < P_RTC + RTC_ACTIVE_BYTES) begin
                  rtc_image[255 - (payload_offset - P_RTC) * 8 -: 32]
                      <= read_word;
                  if (!v2_rtc_word_reserved_zero_valid(
                          payload_offset[7:0], read_word))
                    rtc_words_valid <= 1'b0;
                end

                if (payload_offset >= P_INTERNAL_EEPROM_CTRL &&
                    payload_offset < P_INTERNAL_EEPROM_CTRL +
                                     EEPROM_ACTIVE_BYTES) begin
                  if (!v2_eeprom_word_reserved_zero_valid(
                          payload_offset[7:0], read_word))
                    internal_eeprom_words_valid <= 1'b0;
                  case (payload_offset - P_INTERNAL_EEPROM_CTRL)
                    32'h00: internal_eeprom_word0 <= read_word;
                    32'h04: internal_eeprom_word1 <= read_word;
                    32'h08: internal_eeprom_word2 <= read_word;
                    32'h0c: internal_eeprom_word3 <= read_word;
                    default: internal_eeprom_words_valid <= 1'b0;
                  endcase
                end

                if (payload_offset >= P_CART_EEPROM_CTRL &&
                    payload_offset < P_CART_EEPROM_CTRL +
                                     EEPROM_ACTIVE_BYTES) begin
                  if (!v2_eeprom_word_reserved_zero_valid(
                          payload_offset[7:0], read_word))
                    cart_eeprom_words_valid <= 1'b0;
                  case (payload_offset - P_CART_EEPROM_CTRL)
                    32'h00: cart_eeprom_word0 <= read_word;
                    32'h04: cart_eeprom_word1 <= read_word;
                    32'h08: cart_eeprom_word2 <= read_word;
                    32'h0c: cart_eeprom_word3 <= read_word;
                    default: cart_eeprom_words_valid <= 1'b0;
                  endcase
                end

                if (payload_offset == V2_PAYLOAD_BYTES - 32'd4)
                  state <= STATE_PAYLOAD_CHECK;
                else begin
                  payload_offset <= payload_offset + 32'd4;
                  state <= STATE_READ_REQUEST;
                end
              end
            end else if (backend_wait_timeout) begin
              failure_reason <= FAILURE_STAGE_BACKEND;
              preflight_failed <= 1'b1;
              state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
            end
          end

          STATE_PAYLOAD_CHECK: begin
            if (stage_transfer_failed || backend_failure_seen) begin
              failure_reason <= FAILURE_STAGE_BACKEND;
              preflight_failed <= 1'b1;
              state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
            end else if (!stage_quiescent) begin
              // The final response is not a completion barrier.  Wait until
              // the backend proves that no late terminal remains observable.
              if (backend_wait_timeout) begin
                failure_reason <= FAILURE_STAGE_BACKEND;
                preflight_failed <= 1'b1;
                state <= STATE_FAIL_DRAIN;
              end else begin
                state <= STATE_PAYLOAD_CHECK;
              end
            end else if (!payload_zero_valid) begin
              failure_reason <= FAILURE_PAYLOAD_ZERO;
              preflight_failed <= 1'b1;
              state <= STATE_EMPTY;
            end else if (calculated_payload_crc != stored_payload_crc) begin
              failure_reason <= FAILURE_PAYLOAD_CRC;
              preflight_failed <= 1'b1;
              state <= STATE_EMPTY;
            end else if (!rtc_words_valid || !v2_rtc_state_valid(rtc_image)) begin
              failure_reason <= FAILURE_RTC;
              preflight_failed <= 1'b1;
              state <= STATE_EMPTY;
            end else if (!internal_eeprom_words_valid ||
                         !v2_eeprom_state_valid(
                             1'b0, header_model, header_ramtype,
                             internal_eeprom_image)) begin
              failure_reason <= FAILURE_INTERNAL_EEPROM;
              preflight_failed <= 1'b1;
              state <= STATE_EMPTY;
            end else if (!cart_eeprom_words_valid ||
                         !v2_eeprom_state_valid(
                             1'b1, header_model, header_ramtype,
                             cart_eeprom_image)) begin
              failure_reason <= FAILURE_CART_EEPROM;
              preflight_failed <= 1'b1;
              state <= STATE_EMPTY;
            end else begin
              staged_image_valid <= 1'b1;
              staged_image_generation <= staged_image_generation + 1'b1;
              failure_reason <= FAILURE_NONE;
              preflight_done <= 1'b1;
              state <= STATE_VALID;
            end
          end

          STATE_FAIL_DRAIN: begin
            if (stage_quiescent)
              state <= STATE_EMPTY;
            else if (backend_wait_timeout)
              protocol_error <= 1'b1;
          end

          STATE_VALID: begin
            if (copy_finalize)
              protocol_error <= 1'b1;
          end

          default: begin
            staged_image_valid <= 1'b0;
            failure_reason <= FAILURE_ABORT;
            preflight_failed <= 1'b1;
            state <= stage_quiescent ? STATE_EMPTY : STATE_FAIL_DRAIN;
          end
        endcase
      end
    end
  end

`ifndef SYNTHESIS
  initial begin
    if (MAX_BACKEND_WAIT_CYCLES <= 0)
      $fatal(1, "MAX_BACKEND_WAIT_CYCLES must be positive");
    if (V2_HEADER_BYTES != 32'h100 || V2_PAYLOAD_BYTES != 32'h120000 ||
        V2_TOTAL_BYTES != 32'h120100 || V2_BRIDGE_WORDS != 32'h48040)
      $fatal(1, "restore preflight requires the exact fixed v2 image");
  end
`endif
endmodule

`default_nettype wire
