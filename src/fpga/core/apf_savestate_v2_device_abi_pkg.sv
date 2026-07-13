`default_nettype none

// Executable wire contract for the RTC and EEPROM controller images in the
// future Memories v2 payload.  This package is deliberately absent from the
// Quartus project.  Production VHDL must map native state into these explicit
// bits; no compiler-selected enumeration or record layout enters the ABI.
package apf_savestate_v2_device_abi_pkg;
  import apf_savestate_v2_layout_pkg::*;

  localparam logic [31:0] V2_DEVICE_BLOCK_BYTES = 32'h0000_0100;

  // -------------------------------------------------------------------------
  // RTC image: exactly 32 active bytes at payload 0x000900, followed by zero
  // through the end of the fixed 0x100-byte RTC section.  Byte +00 is
  // state_data[255:248] and byte +1f is [7:0].  Four consecutive bytes are
  // already a normalized APF word: the lowest offset occupies bits [31:24].
  // -------------------------------------------------------------------------
  localparam logic [31:0] RTC_ACTIVE_BYTES        = 32'h20;
  localparam logic [31:0] RTC_O_COMMAND           = 32'h00; // u8
  localparam logic [31:0] RTC_O_READ              = 32'h01; // u8
  localparam logic [31:0] RTC_O_INDEX             = 32'h02; // low 3 bits
  localparam logic [31:0] RTC_O_FLAGS             = 32'h03; // low 5 bits
  localparam logic [31:0] RTC_O_TIMESTAMP         = 32'h04; // u32 BE
  localparam logic [31:0] RTC_O_DIFF_SECONDS      = 32'h08; // u32 BE
  localparam logic [31:0] RTC_O_SECONDCOUNT       = 32'h0c; // u32 BE
  localparam logic [31:0] RTC_O_LIVE_YEAR         = 32'h10;
  localparam logic [31:0] RTC_O_LIVE_MONTH        = 32'h11;
  localparam logic [31:0] RTC_O_LIVE_MDAY         = 32'h12;
  localparam logic [31:0] RTC_O_LIVE_WDAY         = 32'h13;
  localparam logic [31:0] RTC_O_LIVE_HOUR         = 32'h14;
  localparam logic [31:0] RTC_O_LIVE_MINUTE       = 32'h15;
  localparam logic [31:0] RTC_O_LIVE_SECOND       = 32'h16;
  localparam logic [31:0] RTC_O_BUFFER_YEAR       = 32'h17;
  localparam logic [31:0] RTC_O_BUFFER_MONTH      = 32'h18;
  localparam logic [31:0] RTC_O_BUFFER_MDAY       = 32'h19;
  localparam logic [31:0] RTC_O_BUFFER_WDAY       = 32'h1a;
  localparam logic [31:0] RTC_O_BUFFER_HOUR       = 32'h1b;
  localparam logic [31:0] RTC_O_BUFFER_MINUTE     = 32'h1c;
  localparam logic [31:0] RTC_O_BUFFER_SECOND     = 32'h1d;
  localparam logic [31:0] RTC_O_RESERVED          = 32'h1e;

  localparam logic [7:0] RTC_FLAG_REGBUS_WREN_HISTORY = 8'h01;
  localparam logic [7:0] RTC_FLAG_REGBUS_RDEN_HISTORY = 8'h02;
  localparam logic [7:0] RTC_FLAG_TIMESTAMP_NEW_HISTORY = 8'h04;
  localparam logic [7:0] RTC_FLAG_CHANGE         = 8'h08;
  localparam logic [7:0] RTC_FLAG_SAVE_LOADED_HISTORY = 8'h10;
  localparam logic [7:0] RTC_FLAGS_ALLOWED       = 8'h1f;
  localparam logic [31:0] RTC_SECONDCOUNT_MAX    = 32'd36_863_999;

  function automatic logic [7:0] v2_rtc_image_byte(
      input logic [255:0] image,
      input logic [5:0] byte_offset
  );
    v2_rtc_image_byte = image[255 - byte_offset * 8 -: 8];
  endfunction

  function automatic logic [31:0] v2_rtc_image_word(
      input logic [255:0] image,
      input logic [7:0] block_offset
  );
    if (block_offset[1:0] != 0 || block_offset >= RTC_ACTIVE_BYTES)
      v2_rtc_image_word = 32'd0;
    else
      v2_rtc_image_word = image[255 - block_offset * 8 -: 32];
  endfunction

  // Allowed-bit masks for each normalized 32-bit word of the RTC section.
  function automatic logic [31:0] v2_rtc_word_allowed_mask(
      input logic [7:0] block_offset
  );
    case (block_offset)
      8'h00: v2_rtc_word_allowed_mask = 32'hffff_071f;
      8'h04,
      8'h08: v2_rtc_word_allowed_mask = 32'hffff_ffff;
      8'h0c: v2_rtc_word_allowed_mask = 32'h03ff_ffff;
      8'h10: v2_rtc_word_allowed_mask = 32'hff1f_3f07;
      8'h14: v2_rtc_word_allowed_mask = 32'h3f7f_7fff;
      8'h18: v2_rtc_word_allowed_mask = 32'h1f3f_073f;
      8'h1c: v2_rtc_word_allowed_mask = 32'h7f7f_0000;
      default: v2_rtc_word_allowed_mask = 32'h0000_0000;
    endcase
  endfunction

  function automatic logic v2_rtc_word_reserved_zero_valid(
      input logic [7:0] block_offset,
      input logic [31:0] value
  );
    logic [31:0] allowed;
    begin
      allowed = v2_rtc_word_allowed_mask(block_offset);
      v2_rtc_word_reserved_zero_valid =
          block_offset[1:0] == 0 &&
          (value & ~allowed) == 0;
    end
  endfunction

  function automatic logic v2_bcd8_valid(input logic [7:0] value);
    v2_bcd8_valid = value[7:4] <= 4'd9 && value[3:0] <= 4'd9;
  endfunction

  function automatic logic [7:0] v2_bcd8_to_binary(input logic [7:0] value);
    v2_bcd8_to_binary = {4'd0, value[7:4]} * 8'd10 +
                        {4'd0, value[3:0]};
  endfunction

  // This is intentionally the translated RTL's fixed 28-day February, not a
  // claim that its inherited calendar implements Gregorian leap years.
  function automatic logic [7:0] v2_rtc_days_in_month(
      input logic [7:0] month_binary
  );
    case (month_binary)
      8'd2: v2_rtc_days_in_month = 8'd28;
      8'd4, 8'd6, 8'd9, 8'd11: v2_rtc_days_in_month = 8'd30;
      8'd1, 8'd3, 8'd5, 8'd7, 8'd8, 8'd10, 8'd12:
          v2_rtc_days_in_month = 8'd31;
      default: v2_rtc_days_in_month = 8'd0;
    endcase
  endfunction

  // Exact restore accepts every value representable by the translated RTC's
  // signal widths. Software command 0x14 can expose non-BCD values at a legal
  // freeze cut, so semantic calendar validity must not be a loader gate.
  function automatic logic v2_rtc_calendar_width_valid(
      input logic [7:0] year,
      input logic [7:0] month,
      input logic [7:0] mday,
      input logic [7:0] wday,
      input logic [7:0] hour,
      input logic [7:0] minute,
      input logic [7:0] second
  );
    v2_rtc_calendar_width_valid =
        (month & 8'he0) == 0 && (mday & 8'hc0) == 0 &&
        (wday & 8'hf8) == 0 && (hour & 8'hc0) == 0 &&
        (minute & 8'h80) == 0 && (second & 8'h80) == 0;
  endfunction

  // Diagnostic-only semantic helper. This describes normalized calendar
  // values (including the current RTL's fixed February), but is intentionally
  // not called by v2_rtc_state_valid.
  function automatic logic v2_rtc_calendar_semantic_valid(
      input logic [7:0] year,
      input logic [7:0] month_bcd,
      input logic [7:0] mday_bcd,
      input logic [7:0] wday,
      input logic [7:0] hour_bcd,
      input logic [7:0] minute_bcd,
      input logic [7:0] second_bcd
  );
    logic [7:0] month;
    logic [7:0] mday;
    begin
      month = v2_bcd8_to_binary(month_bcd);
      mday = v2_bcd8_to_binary(mday_bcd);
      v2_rtc_calendar_semantic_valid =
          v2_bcd8_valid(year) &&
          (month_bcd & 8'he0) == 0 && v2_bcd8_valid(month_bcd) &&
          (mday_bcd & 8'hc0) == 0 && v2_bcd8_valid(mday_bcd) &&
          (wday & 8'hf8) == 0 && wday <= 6 &&
          (hour_bcd & 8'hc0) == 0 && v2_bcd8_valid(hour_bcd) &&
          (minute_bcd & 8'h80) == 0 && v2_bcd8_valid(minute_bcd) &&
          (second_bcd & 8'h80) == 0 && v2_bcd8_valid(second_bcd) &&
          month >= 1 && month <= 12 && mday >= 1 &&
          mday <= v2_rtc_days_in_month(month) &&
          v2_bcd8_to_binary(hour_bcd) <= 23 &&
          v2_bcd8_to_binary(minute_bcd) <= 59 &&
          v2_bcd8_to_binary(second_bcd) <= 59;
    end
  endfunction

  function automatic logic v2_rtc_state_valid(input logic [255:0] image);
    logic [7:0] index_byte;
    logic [7:0] flags;
    logic [31:0] secondcount;
    begin
      index_byte = v2_rtc_image_byte(image, RTC_O_INDEX[5:0]);
      flags = v2_rtc_image_byte(image, RTC_O_FLAGS[5:0]);
      secondcount = v2_rtc_image_word(image, RTC_O_SECONDCOUNT[7:0]);
      v2_rtc_state_valid =
          (index_byte & 8'hf8) == 0 && index_byte <= 6 &&
          (flags & ~RTC_FLAGS_ALLOWED) == 0 &&
          secondcount <= RTC_SECONDCOUNT_MAX &&
          v2_rtc_calendar_width_valid(
              v2_rtc_image_byte(image, RTC_O_LIVE_YEAR[5:0]),
              v2_rtc_image_byte(image, RTC_O_LIVE_MONTH[5:0]),
              v2_rtc_image_byte(image, RTC_O_LIVE_MDAY[5:0]),
              v2_rtc_image_byte(image, RTC_O_LIVE_WDAY[5:0]),
              v2_rtc_image_byte(image, RTC_O_LIVE_HOUR[5:0]),
              v2_rtc_image_byte(image, RTC_O_LIVE_MINUTE[5:0]),
              v2_rtc_image_byte(image, RTC_O_LIVE_SECOND[5:0])) &&
          v2_rtc_calendar_width_valid(
              v2_rtc_image_byte(image, RTC_O_BUFFER_YEAR[5:0]),
              v2_rtc_image_byte(image, RTC_O_BUFFER_MONTH[5:0]),
              v2_rtc_image_byte(image, RTC_O_BUFFER_MDAY[5:0]),
              v2_rtc_image_byte(image, RTC_O_BUFFER_WDAY[5:0]),
              v2_rtc_image_byte(image, RTC_O_BUFFER_HOUR[5:0]),
              v2_rtc_image_byte(image, RTC_O_BUFFER_MINUTE[5:0]),
              v2_rtc_image_byte(image, RTC_O_BUFFER_SECOND[5:0])) &&
          v2_rtc_image_byte(image, 6'h1e) == 0 &&
          v2_rtc_image_byte(image, 6'h1f) == 0;
    end
  endfunction

  // -------------------------------------------------------------------------
  // EEPROM native controller image: exactly 128 bits.  These bit positions
  // are shared verbatim with eeprom.vhd's state_data port.  The remainder of
  // each fixed 0x100-byte controller section is zero.
  // -------------------------------------------------------------------------
  localparam logic [31:0] EEPROM_ACTIVE_BYTES = 32'h10;
  localparam integer EEPROM_B_WRITE_DATA      = 0;   // [15:0]
  localparam integer EEPROM_B_READ_DATA       = 16;  // [31:16]
  localparam integer EEPROM_B_ADDR            = 32;  // [47:32]
  localparam integer EEPROM_B_CMD             = 48;  // [55:48]
  localparam integer EEPROM_B_STATE           = 56;  // [58:56]
  localparam integer EEPROM_B_WRITE_ENABLE    = 59;
  localparam integer EEPROM_B_WRITE_PROTECT   = 60;
  localparam integer EEPROM_B_READ_DONE       = 61;
  localparam integer EEPROM_B_READ_DELAY      = 62;  // [65:62]
  localparam integer EEPROM_B_SIZE            = 66;  // [76:66]
  localparam integer EEPROM_B_CLEAR_COUNTER   = 77;  // [87:77]
  localparam integer EEPROM_B_ADDR_COUNTER    = 88;  // [98:88]
  localparam integer EEPROM_B_WRITE_VALUE     = 99;  // [114:99]
  localparam integer EEPROM_B_SS_LOADED       = 115;
  localparam integer EEPROM_B_RAM_WREN        = 116;
  localparam integer EEPROM_B_WRITTEN         = 117;
  localparam integer EEPROM_B_RESERVED        = 118; // [127:118]

  localparam logic [2:0] EEPROM_STATE_OFF       = 3'd0;
  localparam logic [2:0] EEPROM_STATE_IDLE      = 3'd1;
  localparam logic [2:0] EEPROM_STATE_EVALCMD   = 3'd2;
  localparam logic [2:0] EEPROM_STATE_CLEAR     = 3'd3;
  localparam logic [2:0] EEPROM_STATE_OVERWRITE = 3'd4;
  localparam logic [2:0] EEPROM_STATE_WRITEWAIT = 3'd5;
  localparam logic [2:0] EEPROM_STATE_READWAIT  = 3'd6;
  localparam logic [2:0] EEPROM_STATE_READONE   = 3'd7;

  // The native image is little-bit/byte indexed for convenient VHDL ports.
  // This helper exposes that implementation detail for adapter tests only;
  // structured payload words below are semantic big-endian per the v2 ABI.
  function automatic logic [7:0] v2_eeprom_image_byte(
      input logic [127:0] image,
      input logic [4:0] byte_offset
  );
    v2_eeprom_image_byte = image[byte_offset * 8 +: 8];
  endfunction

  function automatic logic [31:0] v2_eeprom_image_word(
      input logic [127:0] image,
      input logic [7:0] block_offset
  );
    case (block_offset)
      // W0: WriteData, ReadData.
      8'h00: v2_eeprom_image_word = {image[15:0], image[31:16]};
      // W1: Addr, Cmd, FSM, writeEnable, writeProtect, readDone, zero[1:0].
      8'h04: v2_eeprom_image_word = {
          image[47:32], image[55:48], image[58:56],
          image[59], image[60], image[61], 2'b00
      };
      // W2: readDelay, size, clearCounter, zero[5:0].
      8'h08: v2_eeprom_image_word = {
          image[65:62], image[76:66], image[87:77], 6'b00_0000
      };
      // W3: addrCounter, writevalue, ssLoaded, RAMWrEn, written, zero[1:0].
      8'h0c: v2_eeprom_image_word = {
          image[98:88], image[114:99], image[115], image[116],
          image[117], 2'b00
      };
      default: v2_eeprom_image_word = 32'd0;
    endcase
  endfunction

  function automatic logic [31:0] v2_eeprom_word_allowed_mask(
      input logic [7:0] block_offset
  );
    case (block_offset)
      8'h00: v2_eeprom_word_allowed_mask = 32'hffff_ffff;
      8'h04: v2_eeprom_word_allowed_mask = 32'hffff_fffc;
      8'h08: v2_eeprom_word_allowed_mask = 32'hffff_ffc0;
      // ssLoaded and RAMWrEn are drained zero; written remains exact.
      8'h0c: v2_eeprom_word_allowed_mask = 32'hffff_ffe4;
      default: v2_eeprom_word_allowed_mask = 32'h0000_0000;
    endcase
  endfunction

  function automatic logic v2_eeprom_word_reserved_zero_valid(
      input logic [7:0] block_offset,
      input logic [31:0] value
  );
    logic [31:0] allowed;
    begin
      allowed = v2_eeprom_word_allowed_mask(block_offset);
      v2_eeprom_word_reserved_zero_valid =
          block_offset[1:0] == 0 && (value & ~allowed) == 0;
    end
  endfunction

  function automatic logic [127:0] v2_eeprom_image_from_words(
      input logic [31:0] word0,
      input logic [31:0] word1,
      input logic [31:0] word2,
      input logic [31:0] word3
  );
    logic [127:0] image;
    begin
      image = '0;
      image[15:0]   = word0[31:16];
      image[31:16]  = word0[15:0];
      image[47:32]  = word1[31:16];
      image[55:48]  = word1[15:8];
      image[58:56]  = word1[7:5];
      image[59]     = word1[4];
      image[60]     = word1[3];
      image[61]     = word1[2];
      image[65:62]  = word2[31:28];
      image[76:66]  = word2[27:17];
      image[87:77]  = word2[16:6];
      image[98:88]  = word3[31:21];
      image[114:99] = word3[20:5];
      image[115]    = word3[4];
      image[116]    = word3[3];
      image[117]    = word3[2];
      v2_eeprom_image_from_words = image;
    end
  endfunction

  function automatic logic v2_known_ramtype(input logic [7:0] ramtype);
    v2_known_ramtype = ramtype == V2_RAM_NONE ||
        v2_expected_sram_bytes(ramtype) != 0 ||
        v2_expected_cart_eeprom_bytes(ramtype) != 0;
  endfunction

  function automatic logic [10:0] v2_expected_eeprom_words(
      input logic is_external,
      input logic [7:0] model,
      input logic [7:0] ramtype
  );
    logic [31:0] bytes;
    begin
      bytes = v2_expected_cart_eeprom_bytes(ramtype);
      if (!is_external)
        v2_expected_eeprom_words = model == V2_MODEL_COLOR ? 11'd1024 :
                                    model == V2_MODEL_MONO ? 11'd64 : 11'd0;
      else
        v2_expected_eeprom_words = bytes[11:1];
    end
  endfunction

  function automatic logic v2_eeprom_state_code_valid(
      input logic [2:0] state_code
  );
    case (state_code)
      EEPROM_STATE_OFF, EEPROM_STATE_IDLE, EEPROM_STATE_EVALCMD,
      EEPROM_STATE_CLEAR, EEPROM_STATE_OVERWRITE, EEPROM_STATE_WRITEWAIT,
      EEPROM_STATE_READWAIT, EEPROM_STATE_READONE:
          v2_eeprom_state_code_valid = 1'b1;
      default: v2_eeprom_state_code_valid = 1'b0;
    endcase
  endfunction

  function automatic logic v2_eeprom_state_valid(
      input logic is_external,
      input logic [7:0] model,
      input logic [7:0] ramtype,
      input logic [127:0] image
  );
    logic [2:0] state_code;
    logic [3:0] read_delay;
    logic [10:0] size_words;
    logic [10:0] clear_counter;
    logic [10:0] addr_counter;
    logic [10:0] expected_words;
    logic identity_valid;
    logic clear_counter_reachable;
    logic addr_counter_reachable;
    logic state_history_valid;
    logic read_done;
    logic write_enable;
    logic write_protect;
    logic written_history;
    logic [15:0] write_value;
    begin
      state_code = image[EEPROM_B_STATE +: 3];
      read_delay = image[EEPROM_B_READ_DELAY +: 4];
      size_words = image[EEPROM_B_SIZE +: 11];
      clear_counter = image[EEPROM_B_CLEAR_COUNTER +: 11];
      addr_counter = image[EEPROM_B_ADDR_COUNTER +: 11];
      read_done = image[EEPROM_B_READ_DONE];
      write_enable = image[EEPROM_B_WRITE_ENABLE];
      write_protect = image[EEPROM_B_WRITE_PROTECT];
      written_history = image[EEPROM_B_WRITTEN];
      write_value = image[EEPROM_B_WRITE_VALUE +: 16];
      expected_words = v2_expected_eeprom_words(is_external, model, ramtype);
      identity_valid =
          (model == V2_MODEL_MONO || model == V2_MODEL_COLOR) &&
          v2_known_ramtype(ramtype);
      if (is_external)
        clear_counter_reachable = clear_counter == 0;
      else if (state_code == EEPROM_STATE_CLEAR)
        clear_counter_reachable =
            (clear_counter == 0 && addr_counter == 0) ||
            (clear_counter >= 1 && clear_counter <= 67 &&
             addr_counter == clear_counter - 1'b1);
      else
        clear_counter_reachable = clear_counter == 0 || clear_counter == 67;
      if (is_external)
        addr_counter_reachable = expected_words == 0 ? addr_counter == 0 :
                                                       addr_counter < expected_words;
      else if (model == V2_MODEL_MONO)
        // Factory CLEAR touches words 0..66 before the 64-word runtime view
        // resumes. Only the first IDLE cut after completion can retain the
        // terminal address 66; 64/65 never survive a state transition, and
        // every command-bearing state has already re-applied the 6-bit Addr.
        addr_counter_reachable = state_code == EEPROM_STATE_CLEAR ?
            addr_counter <= 66 :
            (state_code == EEPROM_STATE_IDLE && clear_counter == 67) ?
                (addr_counter <= 63 || addr_counter == 66) :
                addr_counter <= 63;
      else
        addr_counter_reachable = addr_counter <= 1023;

      case (state_code)
        EEPROM_STATE_OFF:
          state_history_valid = read_done && read_delay == 0 &&
              write_value == 16'hffff && !written_history;
        EEPROM_STATE_IDLE,
        EEPROM_STATE_EVALCMD:
          state_history_valid = !written_history;
        EEPROM_STATE_CLEAR:
          state_history_valid = read_done && !write_protect &&
              read_delay == 0 &&
              written_history == (clear_counter != 0);
        EEPROM_STATE_WRITEWAIT:
          // A single-word write only enters WRITEWAIT after asserting RAMWrEn.
          // Internal protection suppresses the transition at addresses 0x30+.
          state_history_valid = write_enable && written_history &&
              !(!is_external && write_protect && addr_counter >= 11'h030);
        EEPROM_STATE_READWAIT:
          state_history_valid = !read_done && !written_history;
        EEPROM_STATE_READONE:
          state_history_valid = !read_done && read_delay == 9 &&
              !written_history;
        default: begin
          // A disabled write-all/erase-all stalls at its initial address and
          // never emits a write pulse.  Enabled internal protected sweeps
          // write 0x00..0x2f, then retain no pulse while skipping 0x30+.
          if (!write_enable)
            state_history_valid = addr_counter == 0 && !written_history;
          else if (!is_external && write_protect && addr_counter >= 11'h030)
            state_history_valid = !written_history;
          else
            state_history_valid = written_history;
        end
      endcase

      v2_eeprom_state_valid = identity_valid &&
          image[127:EEPROM_B_RESERVED] == 0 &&
          image[EEPROM_B_SS_LOADED] == 0 &&
          image[EEPROM_B_RAM_WREN] == 0 &&
          v2_eeprom_state_code_valid(state_code) &&
          read_delay <= 9 && clear_counter_reachable &&
          addr_counter_reachable && state_history_valid &&
          size_words == expected_words &&
          (!is_external || !image[EEPROM_B_WRITE_PROTECT]) &&
          (state_code != EEPROM_STATE_CLEAR ||
           !is_external) &&
          ((expected_words == 0) == (state_code == EEPROM_STATE_OFF));
    end
  endfunction

  // Backing bytes are independent from the controller image.  Both current
  // data ports and pinned emulator sources store the low half of each EEPROM
  // word at the even byte address, then the high half at the odd address.
  function automatic logic [7:0] v2_eeprom_backing_byte(
      input logic [15:0] backing_word,
      input logic byte_in_word
  );
    v2_eeprom_backing_byte = byte_in_word ? backing_word[15:8] :
                                              backing_word[7:0];
  endfunction

  function automatic logic [31:0] v2_eeprom_pack_backing_words(
      input logic [15:0] first_word,
      input logic [15:0] second_word
  );
    v2_eeprom_pack_backing_words = {
        first_word[7:0], first_word[15:8],
        second_word[7:0], second_word[15:8]
    };
  endfunction

  function automatic logic [15:0] v2_eeprom_unpack_first_word(
      input logic [31:0] normalized_word
  );
    v2_eeprom_unpack_first_word = {normalized_word[23:16],
                                   normalized_word[31:24]};
  endfunction

  function automatic logic [15:0] v2_eeprom_unpack_second_word(
      input logic [31:0] normalized_word
  );
    v2_eeprom_unpack_second_word = {normalized_word[7:0],
                                    normalized_word[15:8]};
  endfunction
endpackage

`default_nettype wire
