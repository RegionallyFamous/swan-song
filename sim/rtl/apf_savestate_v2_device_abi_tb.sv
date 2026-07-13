`timescale 1ns/1ps
`default_nettype none

module apf_savestate_v2_device_abi_tb;
  import apf_savestate_v2_layout_pkg::*;
  import apf_savestate_v2_device_abi_pkg::*;

  integer unsigned failures;
  integer unsigned checks;
  integer offset;
  integer bit_index;
  integer state_index;
  integer clear_index;
  integer word_value;
  logic [255:0] rtc_image;
  logic [255:0] rtc_mutation;
  logic [127:0] eeprom_image;
  logic [127:0] eeprom_mutation;
  logic [31:0] expected_word;
  logic [31:0] packed_words;

  task automatic check(input logic condition, input string message);
    begin
      checks = checks + 1;
      if (!condition) begin
        $display("FAIL %s", message);
        failures = failures + 1;
      end
    end
  endtask

  task automatic rtc_set_byte(
      inout logic [255:0] image,
      input integer byte_offset,
      input logic [7:0] value
  );
    image[255 - byte_offset * 8 -: 8] = value;
  endtask

  task automatic make_valid_rtc(output logic [255:0] image);
    begin
      image = '0;
      rtc_set_byte(image, RTC_O_COMMAND, 8'h15);
      rtc_set_byte(image, RTC_O_READ, 8'h58);
      rtc_set_byte(image, RTC_O_INDEX, 8'd6);
      rtc_set_byte(image, RTC_O_FLAGS, RTC_FLAGS_ALLOWED);
      image[255 - RTC_O_TIMESTAMP * 8 -: 32] = 32'h1234_5678;
      image[255 - RTC_O_DIFF_SECONDS * 8 -: 32] = 32'h89ab_cdef;
      image[255 - RTC_O_SECONDCOUNT * 8 -: 32] = RTC_SECONDCOUNT_MAX;
      rtc_set_byte(image, RTC_O_LIVE_YEAR, 8'h24);
      rtc_set_byte(image, RTC_O_LIVE_MONTH, 8'h02);
      rtc_set_byte(image, RTC_O_LIVE_MDAY, 8'h28);
      rtc_set_byte(image, RTC_O_LIVE_WDAY, 8'd3);
      rtc_set_byte(image, RTC_O_LIVE_HOUR, 8'h23);
      rtc_set_byte(image, RTC_O_LIVE_MINUTE, 8'h59);
      rtc_set_byte(image, RTC_O_LIVE_SECOND, 8'h58);
      rtc_set_byte(image, RTC_O_BUFFER_YEAR, 8'h99);
      rtc_set_byte(image, RTC_O_BUFFER_MONTH, 8'h12);
      rtc_set_byte(image, RTC_O_BUFFER_MDAY, 8'h31);
      rtc_set_byte(image, RTC_O_BUFFER_WDAY, 8'd6);
      rtc_set_byte(image, RTC_O_BUFFER_HOUR, 8'h00);
      rtc_set_byte(image, RTC_O_BUFFER_MINUTE, 8'h00);
      rtc_set_byte(image, RTC_O_BUFFER_SECOND, 8'h00);
    end
  endtask

  task automatic make_eeprom(
      output logic [127:0] image,
      input logic is_external,
      input logic [7:0] model,
      input logic [7:0] ramtype,
      input logic [2:0] state_code
  );
    begin
      image = '0;
      image[EEPROM_B_WRITE_DATA +: 16] = 16'h1234;
      image[EEPROM_B_READ_DATA +: 16] = 16'habcd;
      image[EEPROM_B_ADDR +: 16] = 16'h5678;
      image[EEPROM_B_CMD +: 8] = 8'h9a;
      image[EEPROM_B_STATE +: 3] = state_code;
      image[EEPROM_B_WRITE_ENABLE] = 1'b1;
      image[EEPROM_B_WRITE_PROTECT] =
          !is_external && state_code != EEPROM_STATE_CLEAR;
      image[EEPROM_B_READ_DONE] =
          state_code != EEPROM_STATE_READWAIT &&
          state_code != EEPROM_STATE_READONE;
      image[EEPROM_B_READ_DELAY +: 4] =
          (state_code == EEPROM_STATE_OFF ||
           state_code == EEPROM_STATE_CLEAR) ? 4'd0 : 4'd9;
      image[EEPROM_B_SIZE +: 11] =
          v2_expected_eeprom_words(is_external, model, ramtype);
      image[EEPROM_B_CLEAR_COUNTER +: 11] = 11'd0;
      image[EEPROM_B_ADDR_COUNTER +: 11] = 11'd0;
      image[EEPROM_B_WRITE_VALUE +: 16] =
          state_code == EEPROM_STATE_OFF ? 16'hffff : 16'hcafe;
      image[EEPROM_B_WRITTEN] =
          state_code == EEPROM_STATE_OVERWRITE ||
          state_code == EEPROM_STATE_WRITEWAIT;
    end
  endtask

  initial begin
    failures = 0;
    checks = 0;

    // Exact region ownership and state-port orientation.
    check(P_RTC == 32'h900 && P_RTC_BYTES == V2_DEVICE_BLOCK_BYTES,
          "RTC owns fixed 0x100-byte section");
    check(P_INTERNAL_EEPROM_CTRL == 32'ha00 &&
          P_INTERNAL_EEPROM_CTRL_BYTES == V2_DEVICE_BLOCK_BYTES,
          "internal EEPROM owns fixed 0x100-byte section");
    check(P_CART_EEPROM_CTRL == 32'hb00 &&
          P_CART_EEPROM_CTRL_BYTES == V2_DEVICE_BLOCK_BYTES,
          "cart EEPROM owns fixed 0x100-byte section");
    check(RTC_ACTIVE_BYTES == 32 && EEPROM_ACTIVE_BYTES == 16,
          "active image lengths");
    check(RTC_O_COMMAND == 0 && RTC_O_FLAGS == 3 &&
          RTC_O_TIMESTAMP == 4 && RTC_O_SECONDCOUNT == 12 &&
          RTC_O_LIVE_YEAR == 16 && RTC_O_BUFFER_SECOND == 29 &&
          RTC_O_RESERVED == 30, "RTC byte offsets");

    // Every RTC image byte and normalized word is in exact source order.
    rtc_image = '0;
    for (offset = 0; offset < 32; offset = offset + 1)
      rtc_set_byte(rtc_image, offset, offset[7:0]);
    for (offset = 0; offset < 32; offset = offset + 1)
      check(v2_rtc_image_byte(rtc_image, offset[5:0]) == offset[7:0],
            $sformatf("RTC byte adapter offset %0d", offset));
    for (offset = 0; offset < 32; offset = offset + 4) begin
      expected_word = ((offset + 0) << 24) |
                      ((offset + 1) << 16) |
                      ((offset + 2) << 8) |
                      (offset + 3);
      check(v2_rtc_image_word(rtc_image, offset[7:0]) == expected_word,
            $sformatf("RTC normalized word offset %0d", offset));
    end
    check(v2_rtc_image_word(rtc_image, 8'h20) == 0,
          "RTC extraction outside active image is zero");
    check(v2_rtc_image_word(rtc_image, 8'h01) == 0,
          "RTC extraction rejects misaligned offset");

    // Exhaust every word/bit mask across the complete 0x100-byte RTC section.
    for (offset = 0; offset < 256; offset = offset + 4) begin
      for (bit_index = 0; bit_index < 32; bit_index = bit_index + 1) begin
        check(v2_rtc_word_reserved_zero_valid(
                  offset[7:0], 32'h1 << bit_index) ==
              v2_rtc_word_allowed_mask(offset[7:0])[bit_index],
              $sformatf("RTC allowed mask offset=%0d bit=%0d",
                        offset, bit_index));
      end
      check(v2_rtc_word_reserved_zero_valid(offset[7:0], 0),
            $sformatf("RTC zero word offset=%0d", offset));
    end
    check(!v2_rtc_word_reserved_zero_valid(8'h01, 0),
          "RTC mask rejects unaligned word");

    make_valid_rtc(rtc_image);
    check(v2_rtc_state_valid(rtc_image), "valid RTC image accepted");
    check(v2_rtc_image_word(rtc_image, 8'h04) == 32'h1234_5678,
          "RTC timestamp is big-endian");
    check(v2_rtc_image_word(rtc_image, 8'h08) == 32'h89ab_cdef,
          "RTC difference is big-endian");
    check(v2_rtc_image_word(rtc_image, 8'h0c) == RTC_SECONDCOUNT_MAX,
          "RTC subsecond is big-endian");

    // Every reserved RTC bit in the active image independently fails closed.
    for (offset = 0; offset < 32; offset = offset + 4) begin
      for (bit_index = 0; bit_index < 32; bit_index = bit_index + 1) begin
        if (!v2_rtc_word_allowed_mask(offset[7:0])[bit_index]) begin
          rtc_mutation = rtc_image;
          rtc_mutation[224 - offset * 8 + bit_index] = 1'b1;
          check(!v2_rtc_state_valid(rtc_mutation),
                $sformatf("RTC reserved mutation offset=%0d bit=%0d",
                          offset, bit_index));
        end
      end
    end

    // Protocol bounds and exact 36.864 MHz subsecond terminal.
    rtc_mutation = rtc_image;
    rtc_set_byte(rtc_mutation, RTC_O_INDEX, 8'd7);
    check(!v2_rtc_state_valid(rtc_mutation), "RTC index 7 rejected");
    rtc_mutation = rtc_image;
    rtc_set_byte(rtc_mutation, RTC_O_INDEX, 8'h80);
    check(!v2_rtc_state_valid(rtc_mutation), "RTC index upper bits rejected");
    rtc_mutation = rtc_image;
    rtc_set_byte(rtc_mutation, RTC_O_FLAGS, 8'h20);
    check(!v2_rtc_state_valid(rtc_mutation), "RTC unknown flag rejected");
    rtc_mutation = rtc_image;
    rtc_mutation[255 - RTC_O_SECONDCOUNT * 8 -: 32] =
        RTC_SECONDCOUNT_MAX + 1;
    check(!v2_rtc_state_valid(rtc_mutation),
          "RTC secondcount beyond terminal rejected");
    rtc_mutation[255 - RTC_O_SECONDCOUNT * 8 -: 32] = 0;
    check(v2_rtc_state_valid(rtc_mutation), "RTC secondcount zero accepted");

    // Semantic calendar diagnostics mirror the translated implementation's
    // fixed February, but exact-state acceptance is width-only: command 0x14
    // can create arbitrary/non-BCD values at a legitimate freeze cut.
    check(v2_rtc_calendar_semantic_valid(8'h00, 8'h01, 8'h01, 8'd0,
          8'h00, 8'h00, 8'h00), "RTC minimum calendar accepted");
    check(v2_rtc_calendar_semantic_valid(8'h99, 8'h02, 8'h28, 8'd6,
          8'h23, 8'h59, 8'h59), "RTC maximum February calendar accepted");
    check(!v2_rtc_calendar_semantic_valid(8'h24, 8'h02, 8'h29, 8'd0,
          8'h00, 8'h00, 8'h00), "RTC February 29 rejected by RTL contract");
    check(!v2_rtc_calendar_semantic_valid(8'h24, 8'h04, 8'h31, 8'd0,
          8'h00, 8'h00, 8'h00), "RTC April 31 rejected");
    check(!v2_rtc_calendar_semantic_valid(8'h24, 8'h00, 8'h01, 8'd0,
          8'h00, 8'h00, 8'h00), "RTC month zero rejected");
    check(!v2_rtc_calendar_semantic_valid(8'h24, 8'h13, 8'h01, 8'd0,
          8'h00, 8'h00, 8'h00), "RTC month 13 rejected");
    check(!v2_rtc_calendar_semantic_valid(8'h24, 8'h01, 8'h00, 8'd0,
          8'h00, 8'h00, 8'h00), "RTC day zero rejected");
    check(!v2_rtc_calendar_semantic_valid(8'h24, 8'h01, 8'h01, 8'd7,
          8'h00, 8'h00, 8'h00), "RTC weekday 7 rejected");
    check(!v2_rtc_calendar_semantic_valid(8'h24, 8'h01, 8'h01, 8'd0,
          8'h24, 8'h00, 8'h00), "RTC hour 24 rejected");
    check(!v2_rtc_calendar_semantic_valid(8'h24, 8'h01, 8'h01, 8'd0,
          8'h00, 8'h60, 8'h00), "RTC minute 60 rejected");
    check(!v2_rtc_calendar_semantic_valid(8'h24, 8'h01, 8'h01, 8'd0,
          8'h00, 8'h00, 8'h60), "RTC second 60 rejected");
    check(!v2_rtc_calendar_semantic_valid(8'hfa, 8'h01, 8'h01, 8'd0,
          8'h00, 8'h00, 8'h00), "RTC non-BCD year rejected");
    check(!v2_rtc_calendar_semantic_valid(8'h24, 8'ha1, 8'h01, 8'd0,
          8'h00, 8'h00, 8'h00), "RTC month unused bits rejected");
    rtc_mutation = rtc_image;
    rtc_set_byte(rtc_mutation, RTC_O_LIVE_YEAR, 8'hff);
    rtc_set_byte(rtc_mutation, RTC_O_LIVE_MONTH, 8'h1f);
    rtc_set_byte(rtc_mutation, RTC_O_LIVE_MDAY, 8'h3f);
    rtc_set_byte(rtc_mutation, RTC_O_LIVE_WDAY, 8'h07);
    rtc_set_byte(rtc_mutation, RTC_O_LIVE_HOUR, 8'h3f);
    rtc_set_byte(rtc_mutation, RTC_O_LIVE_MINUTE, 8'h7f);
    rtc_set_byte(rtc_mutation, RTC_O_LIVE_SECOND, 8'h7f);
    rtc_set_byte(rtc_mutation, RTC_O_BUFFER_YEAR, 8'hfa);
    rtc_set_byte(rtc_mutation, RTC_O_BUFFER_MONTH, 8'h00);
    rtc_set_byte(rtc_mutation, RTC_O_BUFFER_MDAY, 8'h00);
    rtc_set_byte(rtc_mutation, RTC_O_BUFFER_WDAY, 8'h07);
    rtc_set_byte(rtc_mutation, RTC_O_BUFFER_HOUR, 8'h3f);
    rtc_set_byte(rtc_mutation, RTC_O_BUFFER_MINUTE, 8'h6a);
    rtc_set_byte(rtc_mutation, RTC_O_BUFFER_SECOND, 8'h60);
    check(v2_rtc_state_valid(rtc_mutation),
          "RTC full-width non-BCD exact cut accepted");

    // Exact EEPROM bit map, including compiler-independent FSM codes.
    check(EEPROM_B_WRITE_DATA == 0 && EEPROM_B_READ_DATA == 16 &&
          EEPROM_B_ADDR == 32 && EEPROM_B_CMD == 48 &&
          EEPROM_B_STATE == 56 && EEPROM_B_WRITE_ENABLE == 59 &&
          EEPROM_B_WRITE_PROTECT == 60 && EEPROM_B_READ_DONE == 61 &&
          EEPROM_B_READ_DELAY == 62 && EEPROM_B_SIZE == 66 &&
          EEPROM_B_CLEAR_COUNTER == 77 && EEPROM_B_ADDR_COUNTER == 88 &&
          EEPROM_B_WRITE_VALUE == 99 && EEPROM_B_SS_LOADED == 115 &&
          EEPROM_B_RAM_WREN == 116 && EEPROM_B_WRITTEN == 117 &&
          EEPROM_B_RESERVED == 118, "EEPROM native bit offsets");
    check(EEPROM_STATE_OFF == 0 && EEPROM_STATE_IDLE == 1 &&
          EEPROM_STATE_EVALCMD == 2 && EEPROM_STATE_CLEAR == 3 &&
          EEPROM_STATE_OVERWRITE == 4 && EEPROM_STATE_WRITEWAIT == 5 &&
          EEPROM_STATE_READWAIT == 6 && EEPROM_STATE_READONE == 7,
          "EEPROM stable FSM codes");

    eeprom_image = v2_eeprom_image_from_words(
        32'h0011_2233, 32'h4455_6674, 32'h8899_aa80, 32'hccdd_eee4);
    check(v2_eeprom_image_word(eeprom_image, 8'h00) == 32'h0011_2233,
          "EEPROM APF word 0 round trip");
    check(v2_eeprom_image_word(eeprom_image, 8'h04) == 32'h4455_6674,
          "EEPROM APF word 1 round trip");
    check(v2_eeprom_image_word(eeprom_image, 8'h08) == 32'h8899_aa80,
          "EEPROM APF word 2 round trip");
    check(v2_eeprom_image_word(eeprom_image, 8'h0c) == 32'hccdd_eee4,
          "EEPROM APF word 3 round trip");
    check(v2_eeprom_image_byte(eeprom_image, 0) == 8'h11 &&
          v2_eeprom_image_byte(eeprom_image, 1) == 8'h00 &&
          v2_eeprom_image_byte(eeprom_image, 15) == 8'h00,
          "EEPROM native little-byte orientation");
    check(v2_eeprom_image_word(eeprom_image, 8'h10) == 0 &&
          v2_eeprom_image_word(eeprom_image, 8'h01) == 0,
          "EEPROM extraction rejects reserve/misalignment");

    // Exhaust every word/bit mask across both identical EEPROM sections.
    for (offset = 0; offset < 256; offset = offset + 4) begin
      for (bit_index = 0; bit_index < 32; bit_index = bit_index + 1) begin
        check(v2_eeprom_word_reserved_zero_valid(
                  offset[7:0], 32'h1 << bit_index) ==
              v2_eeprom_word_allowed_mask(offset[7:0])[bit_index],
              $sformatf("EEPROM allowed mask offset=%0d bit=%0d",
                        offset, bit_index));
      end
      check(v2_eeprom_word_reserved_zero_valid(offset[7:0], 0),
            $sformatf("EEPROM zero word offset=%0d", offset));
    end
    check(!v2_eeprom_word_reserved_zero_valid(8'h01, 0),
          "EEPROM mask rejects unaligned word");

    make_eeprom(eeprom_image, 1'b0, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_IDLE);
    check(v2_eeprom_state_valid(1'b0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_image), "valid internal mono EEPROM accepted");
    check(eeprom_image[15:0] == 16'h1234 &&
          eeprom_image[31:16] == 16'habcd &&
          eeprom_image[47:32] == 16'h5678 &&
          eeprom_image[55:48] == 8'h9a &&
          eeprom_image[114:99] == 16'hcafe,
          "EEPROM semantic fields occupy exact native bits");
    check(v2_eeprom_image_word(eeprom_image, 8'h00) == 32'h1234_abcd,
          "EEPROM structured data latches are semantic big-endian");
    check(v2_eeprom_image_word(eeprom_image, 8'h04) == 32'h5678_9a3c,
          "EEPROM structured command/control word mapping");
    check(v2_eeprom_image_word(eeprom_image, 8'h08) ==
          {4'd9, 11'd64, 11'd0, 6'd0},
          "EEPROM structured delay/size/counter word mapping");
    check(v2_eeprom_image_word(eeprom_image, 8'h0c) ==
          {11'd0, 16'hcafe, 1'b0, 1'b0, 1'b0, 2'b00},
          "EEPROM structured address/pipeline/history word mapping");

    // All eight fixed FSM encodings are exercised under a legal owner. OFF is
    // the only state for an inactive cart; CLEAR is internal-only.
    for (state_index = 1; state_index <= 7; state_index = state_index + 1) begin
      make_eeprom(eeprom_image, 1'b0, V2_MODEL_COLOR, V2_RAM_NONE,
                  state_index[2:0]);
      check(v2_eeprom_state_valid(1'b0, V2_MODEL_COLOR, V2_RAM_NONE,
            eeprom_image), $sformatf("internal FSM code %0d accepted",
                                     state_index));
    end
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_OFF);
    check(v2_eeprom_state_valid(1'b1, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_image), "inactive cart EEPROM OFF accepted");
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_MONO, V2_RAM_EEPROM_128,
                EEPROM_STATE_IDLE);
    check(v2_eeprom_state_valid(1'b1, V2_MODEL_MONO, V2_RAM_EEPROM_128,
          eeprom_image), "active cart EEPROM IDLE accepted");
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_MONO, V2_RAM_EEPROM_128,
                EEPROM_STATE_CLEAR);
    check(!v2_eeprom_state_valid(1'b1, V2_MODEL_MONO, V2_RAM_EEPROM_128,
          eeprom_image), "external EEPROM CLEAR rejected");
    make_eeprom(eeprom_image, 1'b0, V2_MODEL_COLOR, V2_RAM_NONE,
                EEPROM_STATE_READWAIT);
    check(v2_eeprom_state_valid(0, V2_MODEL_COLOR, V2_RAM_NONE,
          eeprom_image), "READWAIT with readDone zero accepted");
    eeprom_image[EEPROM_B_READ_DONE] = 1'b1;
    check(!v2_eeprom_state_valid(0, V2_MODEL_COLOR, V2_RAM_NONE,
          eeprom_image), "READWAIT with readDone one rejected");
    make_eeprom(eeprom_image, 1'b0, V2_MODEL_COLOR, V2_RAM_NONE,
                EEPROM_STATE_READONE);
    check(v2_eeprom_state_valid(0, V2_MODEL_COLOR, V2_RAM_NONE,
          eeprom_image), "READONE with readDone zero/delay nine accepted");
    eeprom_image[EEPROM_B_READ_DONE] = 1'b1;
    check(!v2_eeprom_state_valid(0, V2_MODEL_COLOR, V2_RAM_NONE,
          eeprom_image), "READONE with readDone one rejected");
    eeprom_image[EEPROM_B_READ_DONE] = 1'b0;
    eeprom_image[EEPROM_B_READ_DELAY +: 4] = 4'd8;
    check(!v2_eeprom_state_valid(0, V2_MODEL_COLOR, V2_RAM_NONE,
          eeprom_image), "READONE with delay eight rejected");

    // Exact model/footer-dependent active word counts.
    check(v2_expected_eeprom_words(0, V2_MODEL_MONO, V2_RAM_NONE) == 64,
          "mono internal EEPROM is 64 words");
    check(v2_expected_eeprom_words(0, V2_MODEL_COLOR, V2_RAM_NONE) == 1024,
          "Color internal EEPROM is 1024 words");
    check(v2_expected_eeprom_words(1, V2_MODEL_COLOR, V2_RAM_NONE) == 0,
          "cart with no EEPROM has zero words");
    check(v2_expected_eeprom_words(1, V2_MODEL_COLOR,
          V2_RAM_EEPROM_128) == 64, "cart type 10 is 64 words");
    check(v2_expected_eeprom_words(1, V2_MODEL_COLOR,
          V2_RAM_EEPROM_2K) == 1024, "cart type 20 is 1024 words");
    check(v2_expected_eeprom_words(1, V2_MODEL_COLOR,
          V2_RAM_EEPROM_1K) == 512, "cart type 50 is 512 words");
    check(v2_expected_eeprom_words(1, V2_MODEL_COLOR,
          V2_RAM_SRAM_512K) == 0, "SRAM cart has no EEPROM words");

    // Counter, delay, size, ownership, drain, and reserve validators.
    make_eeprom(eeprom_image, 1'b0, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_IDLE);
    eeprom_mutation = eeprom_image;
    eeprom_mutation[EEPROM_B_READ_DELAY +: 4] = 4'd10;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "EEPROM readDelay 10 rejected");
    make_eeprom(eeprom_image, 1'b0, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_IDLE);
    eeprom_mutation = eeprom_image;
    eeprom_mutation[EEPROM_B_CLEAR_COUNTER +: 11] = 11'd67;
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "internal retained clearCounter 67 accepted");
    eeprom_mutation[EEPROM_B_CLEAR_COUNTER +: 11] = 11'd68;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "internal unreachable clearCounter 68 rejected");
    eeprom_mutation[EEPROM_B_CLEAR_COUNTER +: 11] = 11'd1;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "non-CLEAR intermediate clearCounter rejected");
    eeprom_mutation = eeprom_image;
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'd63;
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "mono runtime addrCounter 63 accepted");
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'd64;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "mono addrCounter 64 without completed clear rejected");
    eeprom_mutation[EEPROM_B_CLEAR_COUNTER +: 11] = 11'd67;
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'd64;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "mono completed-clear addrCounter 64 rejected");
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'd65;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "mono completed-clear addrCounter 65 rejected");
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'd66;
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "mono completed-clear addrCounter 66 accepted");
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'd67;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "mono unreachable addrCounter 67 rejected");
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'd66;
    eeprom_mutation[EEPROM_B_STATE +: 3] = EEPROM_STATE_EVALCMD;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "mono non-IDLE command state cannot retain factory address 66");
    eeprom_mutation = eeprom_image;
    eeprom_mutation[EEPROM_B_SIZE +: 11] = 11'd1024;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "EEPROM wrong model size rejected");
    eeprom_mutation = eeprom_image;
    eeprom_mutation[EEPROM_B_SS_LOADED] = 1'b1;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "EEPROM undrained ssLoaded rejected");
    eeprom_mutation = eeprom_image;
    eeprom_mutation[EEPROM_B_RAM_WREN] = 1'b1;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "EEPROM undrained RAMWrEn rejected");
    eeprom_mutation = eeprom_image;
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "IDLE written history zero accepted");
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b1;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "IDLE written history one rejected");
    make_eeprom(eeprom_mutation, 1'b0, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_OVERWRITE);
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b1;
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "protected internal OVERWRITE low address write accepted");
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b0;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "protected internal OVERWRITE low address without write rejected");
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'h02f;
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b1;
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "protected internal OVERWRITE address 0x2f write accepted");
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'h030;
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b0;
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "protected internal OVERWRITE address 0x30 skip accepted");
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b1;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "protected internal OVERWRITE address 0x30 write rejected");
    eeprom_mutation[EEPROM_B_WRITE_PROTECT] = 1'b0;
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "unprotected internal OVERWRITE address 0x30 write accepted");
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b0;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "unprotected internal OVERWRITE address 0x30 without write rejected");
    make_eeprom(eeprom_mutation, 1'b1, V2_MODEL_COLOR, V2_RAM_EEPROM_128,
                EEPROM_STATE_OVERWRITE);
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'd1;
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b1;
    check(v2_eeprom_state_valid(1, V2_MODEL_COLOR, V2_RAM_EEPROM_128,
          eeprom_mutation), "external enabled OVERWRITE write accepted");
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b0;
    check(!v2_eeprom_state_valid(1, V2_MODEL_COLOR, V2_RAM_EEPROM_128,
          eeprom_mutation),
          "external enabled OVERWRITE without write rejected");
    make_eeprom(eeprom_mutation, 1'b0, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_OVERWRITE);
    eeprom_mutation[EEPROM_B_WRITE_ENABLE] = 1'b0;
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b0;
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "disabled OVERWRITE initial idle cut accepted");
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b1;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "disabled OVERWRITE write history rejected");
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b0;
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'd1;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "disabled OVERWRITE advanced address rejected");
    make_eeprom(eeprom_mutation, 1'b0, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_WRITEWAIT);
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "WRITEWAIT written history one accepted");
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b0;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "WRITEWAIT written history zero rejected");
    eeprom_mutation[EEPROM_B_WRITTEN] = 1'b1;
    eeprom_mutation[EEPROM_B_WRITE_ENABLE] = 1'b0;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "WRITEWAIT disabled write rejected");
    eeprom_mutation[EEPROM_B_WRITE_ENABLE] = 1'b1;
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'h02f;
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "protected internal WRITEWAIT address 0x2f accepted");
    eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] = 11'h030;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "protected internal WRITEWAIT address 0x30 rejected");
    eeprom_mutation[EEPROM_B_WRITE_PROTECT] = 1'b0;
    check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation),
          "unprotected internal WRITEWAIT address 0x30 accepted");
    make_eeprom(eeprom_image, 1'b0, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_IDLE);
    for (bit_index = EEPROM_B_RESERVED; bit_index < 128;
         bit_index = bit_index + 1) begin
      eeprom_mutation = eeprom_image;
      eeprom_mutation[bit_index] = 1'b1;
      check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
            eeprom_mutation),
            $sformatf("EEPROM reserved bit %0d rejected", bit_index));
    end
    make_eeprom(eeprom_image, 1'b0, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_CLEAR);
    for (clear_index = 0; clear_index <= 67; clear_index = clear_index + 1) begin
      eeprom_image[EEPROM_B_CLEAR_COUNTER +: 11] = clear_index[10:0];
      eeprom_image[EEPROM_B_ADDR_COUNTER +: 11] =
          clear_index == 0 ? 11'd0 : clear_index[10:0] - 1'b1;
      eeprom_image[EEPROM_B_WRITTEN] = clear_index != 0;
      check(v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
            eeprom_image),
            $sformatf("internal CLEAR canonical pair %0d accepted", clear_index));
      eeprom_mutation = eeprom_image;
      eeprom_mutation[EEPROM_B_WRITTEN] = clear_index == 0;
      check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
            eeprom_mutation),
            $sformatf("internal CLEAR written mismatch %0d rejected",
                      clear_index));
      eeprom_mutation = eeprom_image;
      eeprom_mutation[EEPROM_B_ADDR_COUNTER +: 11] =
          clear_index == 0 ? 11'd1 : clear_index[10:0];
      check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
            eeprom_mutation),
            $sformatf("internal CLEAR mismatched pair %0d rejected", clear_index));
    end
    eeprom_mutation = eeprom_image;
    eeprom_mutation[EEPROM_B_WRITE_PROTECT] = 1'b1;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "CLEAR writeProtect one rejected");
    eeprom_mutation = eeprom_image;
    eeprom_mutation[EEPROM_B_READ_DONE] = 1'b0;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "CLEAR readDone zero rejected");
    eeprom_mutation = eeprom_image;
    eeprom_mutation[EEPROM_B_READ_DELAY +: 4] = 4'd1;
    check(!v2_eeprom_state_valid(0, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_mutation), "CLEAR nonzero readDelay rejected");
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_COLOR, V2_RAM_EEPROM_2K,
                EEPROM_STATE_IDLE);
    eeprom_image[EEPROM_B_WRITE_PROTECT] = 1'b1;
    check(!v2_eeprom_state_valid(1, V2_MODEL_COLOR, V2_RAM_EEPROM_2K,
          eeprom_image), "external writeProtect rejected");
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_OFF);
    eeprom_image[EEPROM_B_CLEAR_COUNTER +: 11] = 11'd1;
    check(!v2_eeprom_state_valid(1, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_image), "external nonzero clearCounter rejected");
    eeprom_image[EEPROM_B_CLEAR_COUNTER +: 11] = 11'd0;
    eeprom_image[EEPROM_B_ADDR_COUNTER +: 11] = 11'd1;
    check(!v2_eeprom_state_valid(1, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_image), "inactive cart nonzero addrCounter rejected");
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_OFF);
    eeprom_image[EEPROM_B_READ_DONE] = 1'b0;
    check(!v2_eeprom_state_valid(1, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_image), "inactive cart readDone zero rejected");
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_OFF);
    eeprom_image[EEPROM_B_READ_DELAY +: 4] = 4'd1;
    check(!v2_eeprom_state_valid(1, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_image), "inactive cart nonzero readDelay rejected");
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_OFF);
    eeprom_image[EEPROM_B_WRITE_VALUE +: 16] = 16'h0000;
    check(!v2_eeprom_state_valid(1, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_image), "inactive cart non-FFFF writevalue rejected");
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_MONO, V2_RAM_NONE,
                EEPROM_STATE_OFF);
    eeprom_image[EEPROM_B_WRITTEN] = 1'b1;
    check(!v2_eeprom_state_valid(1, V2_MODEL_MONO, V2_RAM_NONE,
          eeprom_image), "inactive cart written history one rejected");
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_COLOR, V2_RAM_EEPROM_128,
                EEPROM_STATE_IDLE);
    eeprom_image[EEPROM_B_ADDR_COUNTER +: 11] = 11'd63;
    check(v2_eeprom_state_valid(1, V2_MODEL_COLOR, V2_RAM_EEPROM_128,
          eeprom_image), "64-word cart addrCounter 63 accepted");
    eeprom_image[EEPROM_B_ADDR_COUNTER +: 11] = 11'd64;
    check(!v2_eeprom_state_valid(1, V2_MODEL_COLOR, V2_RAM_EEPROM_128,
          eeprom_image), "64-word cart addrCounter 64 rejected");
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_COLOR, V2_RAM_EEPROM_1K,
                EEPROM_STATE_IDLE);
    eeprom_image[EEPROM_B_ADDR_COUNTER +: 11] = 11'd511;
    check(v2_eeprom_state_valid(1, V2_MODEL_COLOR, V2_RAM_EEPROM_1K,
          eeprom_image), "512-word cart addrCounter 511 accepted");
    eeprom_image[EEPROM_B_ADDR_COUNTER +: 11] = 11'd512;
    check(!v2_eeprom_state_valid(1, V2_MODEL_COLOR, V2_RAM_EEPROM_1K,
          eeprom_image), "512-word cart addrCounter 512 rejected");
    make_eeprom(eeprom_image, 1'b0, V2_MODEL_COLOR, V2_RAM_NONE,
                EEPROM_STATE_IDLE);
    eeprom_image[EEPROM_B_ADDR_COUNTER +: 11] = 11'd1023;
    check(v2_eeprom_state_valid(0, V2_MODEL_COLOR, V2_RAM_NONE,
          eeprom_image), "Color internal addrCounter 1023 accepted");
    eeprom_image[EEPROM_B_ADDR_COUNTER +: 11] = 11'd1024;
    check(!v2_eeprom_state_valid(0, V2_MODEL_COLOR, V2_RAM_NONE,
          eeprom_image), "Color internal addrCounter 1024 rejected");
    make_eeprom(eeprom_image, 1'b1, V2_MODEL_COLOR, 8'hff,
                EEPROM_STATE_OFF);
    check(!v2_eeprom_state_valid(1, V2_MODEL_COLOR, 8'hff,
          eeprom_image), "unknown RAM type rejected");

    // Canonical EEPROM backing byte order is exhaustively reversible for every
    // possible 16-bit first word (with its complement as the second word).
    check(v2_eeprom_pack_backing_words(16'h1234, 16'habcd) ==
          32'h3412_cdab, "EEPROM canonical byte-order sentinel");
    check(v2_eeprom_backing_byte(16'h1234, 0) == 8'h34 &&
          v2_eeprom_backing_byte(16'h1234, 1) == 8'h12,
          "EEPROM even-low odd-high bytes");
    for (word_value = 0; word_value < 65536; word_value = word_value + 1) begin
      packed_words = v2_eeprom_pack_backing_words(
          word_value[15:0], ~word_value[15:0]);
      check(v2_eeprom_unpack_first_word(packed_words) == word_value[15:0] &&
            v2_eeprom_unpack_second_word(packed_words) == ~word_value[15:0],
            $sformatf("EEPROM backing round trip word=%0d", word_value));
    end

    if (failures != 0)
      $fatal(1, "APF v2 device ABI failures=%0d checks=%0d", failures, checks);

    $display("PASS APF savestate v2 device ABI checks=%0d rtc-bytes=32 eeprom-bytes=16 backing-words=65536",
             checks);
    $finish;
  end
endmodule

`default_nettype wire
