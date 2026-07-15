`timescale 1ns/1ps
`default_nettype none

module apf_savestate_v2_restore_preflight_tb;
  import apf_savestate_v2_layout_pkg::*;
  import apf_savestate_v2_device_abi_pkg::*;

  localparam integer PAYLOAD_WORDS = V2_PAYLOAD_BYTES / 4;
  localparam integer TOTAL_WORDS = V2_TOTAL_BYTES / 4;

  localparam [3:0] FAILURE_COPY_ORDER       = 4'd1;
  localparam [3:0] FAILURE_COPY_LENGTH      = 4'd2;
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

  reg clk = 1'b0;
  reg reset_n = 1'b0;
  always #5 clk = ~clk;

  reg abort = 1'b0;
  wire image_lock;
  wire stage_content_changed;
  reg external_stage_content_changed = 1'b0;
  reg copy_word_valid = 1'b0;
  wire copy_word_ready;
  reg [31:0] copy_word_offset = 32'd0;
  reg [31:0] copy_word_data = 32'd0;
  reg copy_word_error = 1'b0;
  reg copy_finalize = 1'b0;
  wire copy_active;
  wire preflight_busy;
  wire preflight_done;
  wire preflight_failed;
  wire [3:0] failure_reason;
  wire protocol_error;
  wire staged_image_valid;
  wire [31:0] staged_image_generation;

  reg [31:0] current_rom_bytes = 32'h0004_0000;
  reg [63:0] current_rom_crc64 = 64'h0123_4567_89ab_cdef;
  reg [127:0] current_rom_footer =
      128'h1020_3040_5060_7080_90a0_b0c0_d0e0_f000;
  reg [7:0] current_model = V2_MODEL_MONO;
  reg [7:0] current_mapper = V2_MAPPER_2001;
  reg [7:0] current_ramtype = V2_RAM_NONE;
  reg [7:0] current_active_bios = V2_BIOS_MONO;
  reg [63:0] current_active_bios_crc64 = 64'h1111_2222_3333_4444;
  reg [31:0] current_settings = 32'h0000_0400;
  reg current_flash_supported = 1'b0;

  wire stage_transfer_start;
  wire stage_transfer_start_ready;
  wire stage_abort;
  reg stage_quiescent = 1'b1;
  reg force_stage_nonquiescent = 1'b0;
  reg force_nonquiescent_on_finalize = 1'b0;
  wire stage_quiescent_to_dut = stage_quiescent &&
                                !force_stage_nonquiescent;
  reg stage_transfer_failed = 1'b0;
  reg force_stage_transfer_failed = 1'b0;
  wire stage_transfer_failed_to_dut = stage_transfer_failed |
                                      force_stage_transfer_failed;
  wire read_request_valid;
  wire read_request_ready;
  wire [31:0] read_request_offset;
  reg read_word_valid = 1'b0;
  wire read_word_ready;
  reg [31:0] read_word_offset = 32'd0;
  reg [31:0] read_word = 32'd0;

  reg [31:0] header [0:63];
  reg [31:0] payload [0:PAYLOAD_WORDS-1];
  reg inject_stage_error = 1'b0;
  reg inject_offset_error = 1'b0;
  reg inject_late_terminal_error = 1'b0;
  reg late_terminal_error_pending = 1'b0;
  reg inject_crc_clear_error = 1'b0;
  reg crc_clear_error_pulse = 1'b0;
  reg ignore_stage_abort = 1'b0;
  reg hold_stage_start = 1'b0;
  reg hold_requests = 1'b0;
  reg drop_response = 1'b0;
  reg hold_terminal_quiescent = 1'b0;
  integer stage_start_count = 0;
  integer payload_response_count = 0;

  assign stage_transfer_start_ready = !hold_stage_start &&
                                      stage_quiescent_to_dut;
  assign read_request_ready = !hold_requests && !read_word_valid;

  // One-cycle-latency abstract stage.  stage_quiescent covers an outstanding
  // request/response, while logical transfer lifetime is restarted by every
  // accepted transfer_start.
  always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
      stage_quiescent <= 1'b1;
      stage_transfer_failed <= 1'b0;
      read_word_valid <= 1'b0;
      read_word_offset <= 32'd0;
      read_word <= 32'd0;
      stage_start_count <= 0;
      payload_response_count <= 0;
      late_terminal_error_pending <= 1'b0;
      crc_clear_error_pulse <= 1'b0;
    end else if (stage_abort && !ignore_stage_abort) begin
      stage_quiescent <= 1'b1;
      stage_transfer_failed <= 1'b1;
      read_word_valid <= 1'b0;
      late_terminal_error_pending <= 1'b0;
      crc_clear_error_pulse <= 1'b0;
    end else begin
      if (crc_clear_error_pulse) begin
        stage_transfer_failed <= 1'b0;
        crc_clear_error_pulse <= 1'b0;
      end
      if (late_terminal_error_pending) begin
        stage_transfer_failed <= 1'b1;
        stage_quiescent <= 1'b1;
        late_terminal_error_pending <= 1'b0;
      end
      if (stage_transfer_start && stage_transfer_start_ready) begin
        stage_start_count <= stage_start_count + 1;
        if (inject_crc_clear_error) begin
          // Accepted start raises a one-cycle fault only while the DUT is in
          // PAYLOAD_CRC_CLEAR, then drops before its READ_REQUEST case.
          stage_transfer_failed <= 1'b1;
          crc_clear_error_pulse <= 1'b1;
        end else begin
          stage_transfer_failed <= 1'b0;
        end
      end

      if (read_request_valid && read_request_ready) begin
        stage_quiescent <= 1'b0;
        if (inject_stage_error) begin
          stage_transfer_failed <= 1'b1;
          stage_quiescent <= 1'b1;
        end else if (!drop_response) begin
          read_word_valid <= 1'b1;
          read_word_offset <= inject_offset_error ?
                              read_request_offset + 32'd4 :
                              read_request_offset;
          read_word <= payload[read_request_offset[20:2]];
        end
      end

      if (read_word_valid && read_word_ready) begin
        read_word_valid <= 1'b0;
        if (hold_terminal_quiescent &&
            read_word_offset == V2_PAYLOAD_BYTES - 32'd4)
          stage_quiescent <= 1'b0;
        else
          stage_quiescent <= 1'b1;
        if (inject_late_terminal_error &&
            read_word_offset == V2_PAYLOAD_BYTES - 32'd4) begin
          late_terminal_error_pending <= 1'b1;
          stage_quiescent <= 1'b0;
        end
        payload_response_count <= payload_response_count + 1;
      end
    end
  end

  apf_savestate_v2_restore_preflight #(
      .MAX_BACKEND_WAIT_CYCLES(64)
  ) dut (
      .clk(clk),
      .reset_n(reset_n),
      .abort(abort),
      .image_lock(image_lock),
      .stage_content_changed(stage_content_changed),
      .copy_word_valid(copy_word_valid),
      .copy_word_ready(copy_word_ready),
      .copy_word_offset(copy_word_offset),
      .copy_word_data(copy_word_data),
      .copy_word_error(copy_word_error),
      .copy_finalize(copy_finalize),
      .copy_active(copy_active),
      .preflight_busy(preflight_busy),
      .preflight_done(preflight_done),
      .preflight_failed(preflight_failed),
      .failure_reason(failure_reason),
      .protocol_error(protocol_error),
      .staged_image_valid(staged_image_valid),
      .staged_image_generation(staged_image_generation),
      .current_rom_bytes(current_rom_bytes),
      .current_rom_crc64(current_rom_crc64),
      .current_rom_footer(current_rom_footer),
      .current_model(current_model),
      .current_mapper(current_mapper),
      .current_ramtype(current_ramtype),
      .current_active_bios(current_active_bios),
      .current_active_bios_crc64(current_active_bios_crc64),
      .current_settings(current_settings),
      .current_flash_supported(current_flash_supported),
      .stage_transfer_start(stage_transfer_start),
      .stage_transfer_start_ready(stage_transfer_start_ready),
      .stage_abort(stage_abort),
      .stage_quiescent(stage_quiescent_to_dut),
      .stage_transfer_failed(stage_transfer_failed_to_dut),
      .read_request_valid(read_request_valid),
      .read_request_ready(read_request_ready),
      .read_request_offset(read_request_offset),
      .read_word_valid(read_word_valid),
      .read_word_ready(read_word_ready),
      .read_word_offset(read_word_offset),
      .read_word(read_word)
  );

  // Owner composition.  No other owner behavior is under test here; this
  // proves that only the preflight's validated generation can cross its live
  // restore-apply barrier and that its lock rejects replacement writes.
  reg capture_request = 1'b0;
  reg restore_request = 1'b0;
  reg cancel = 1'b0;
  wire capture_busy;
  wire capture_done;
  wire capture_failed;
  wire restore_busy;
  wire restore_done;
  wire restore_failed;
  wire owner_protocol_error;
  wire fatal_reset_hold;
  wire runtime_pause_request;
  reg runtime_pause_ack = 1'b0;
  reg owner_sdram_quiescent = 1'b1;
  wire device_freeze;
  reg [2:0] device_frozen = 3'b000;
  reg [2:0] device_settling = 3'b000;
  reg device_protocol_fault = 1'b0;
  wire stage_acquire;
  reg stage_granted = 1'b0;
  wire capture_start;
  reg capture_complete = 1'b0;
  reg capture_error = 1'b0;
  wire restore_apply_start;
  reg restore_apply_complete = 1'b0;
  reg restore_apply_error = 1'b0;
  wire datapath_abort;
  reg datapath_quiescent = 1'b1;
  integer restore_start_count = 0;

  assign stage_content_changed = capture_start |
                                 external_stage_content_changed;

  apf_savestate_v2_owner #(
      .DEVICE_COUNT(3),
      .MAX_PHASE_CYCLES(100)
  ) owner (
      .clk(clk),
      .lifecycle_reset_n(reset_n),
      .capture_request(capture_request),
      .restore_request(restore_request),
      .staged_image_valid(staged_image_valid),
      .staged_image_generation(staged_image_generation),
      .cancel(cancel),
      .capture_busy(capture_busy),
      .capture_done(capture_done),
      .capture_failed(capture_failed),
      .restore_busy(restore_busy),
      .restore_done(restore_done),
      .restore_failed(restore_failed),
      .protocol_error(owner_protocol_error),
      .fatal_reset_hold(fatal_reset_hold),
      .staged_image_lock(image_lock),
      .runtime_pause_request(runtime_pause_request),
      .runtime_pause_ack(runtime_pause_ack),
      .sdram_quiescent(owner_sdram_quiescent),
      .device_freeze(device_freeze),
      .device_frozen(device_frozen),
      .device_settling(device_settling),
      .device_protocol_fault(device_protocol_fault),
      .stage_acquire(stage_acquire),
      .stage_granted(stage_granted),
      .capture_start(capture_start),
      .capture_complete(capture_complete),
      .capture_error(capture_error),
      .restore_apply_start(restore_apply_start),
      .restore_apply_complete(restore_apply_complete),
      .restore_apply_error(restore_apply_error),
      .datapath_abort(datapath_abort),
      .datapath_quiescent(datapath_quiescent)
  );

  always @(posedge clk)
    if (restore_apply_start)
      restore_start_count <= restore_start_count + 1;

  function automatic [63:0] crc_update_byte;
    input [63:0] crc_in;
    input [7:0] data_byte;
    integer bit_index;
    reg [63:0] next_crc;
    begin
      next_crc = crc_in ^ {data_byte, 56'd0};
      for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1)
        if (next_crc[63])
          next_crc = {next_crc[62:0], 1'b0} ^
                     64'h42f0_e1eb_a9ea_3693;
        else
          next_crc = {next_crc[62:0], 1'b0};
      crc_update_byte = next_crc;
    end
  endfunction

  function automatic [63:0] crc_update_word;
    input [63:0] crc_in;
    input [31:0] data_word;
    reg [63:0] next_crc;
    begin
      next_crc = crc_update_byte(crc_in, data_word[31:24]);
      next_crc = crc_update_byte(next_crc, data_word[23:16]);
      next_crc = crc_update_byte(next_crc, data_word[15:8]);
      crc_update_word = crc_update_byte(next_crc, data_word[7:0]);
    end
  endfunction

  function automatic [63:0] payload_crc64;
    integer word_index;
    reg [63:0] crc;
    begin
      crc = 64'd0;
      for (word_index = 0; word_index < PAYLOAD_WORDS;
           word_index = word_index + 1)
        crc = crc_update_word(crc, payload[word_index]);
      payload_crc64 = crc;
    end
  endfunction

  function automatic [63:0] header_crc64;
    integer word_index;
    reg [63:0] crc;
    begin
      crc = 64'd0;
      for (word_index = 0; word_index < 62; word_index = word_index + 1)
        crc = crc_update_word(crc, header[word_index]);
      header_crc64 = crc;
    end
  endfunction

  task automatic expect_true(input condition, input string message);
    if (!condition)
      $fatal(1, "%s", message);
  endtask

  task automatic set_internal_eeprom_idle(input [10:0] size_words);
    begin
      payload[(P_INTERNAL_EEPROM_CTRL >> 2) + 0] = 32'd0;
      payload[(P_INTERNAL_EEPROM_CTRL >> 2) + 1] = 32'h0000_0020;
      payload[(P_INTERNAL_EEPROM_CTRL >> 2) + 2] =
          {4'd0, size_words, 11'd0, 6'd0};
      payload[(P_INTERNAL_EEPROM_CTRL >> 2) + 3] = 32'd0;
    end
  endtask

  task automatic set_cart_eeprom_off;
    begin
      payload[(P_CART_EEPROM_CTRL >> 2) + 0] = 32'd0;
      payload[(P_CART_EEPROM_CTRL >> 2) + 1] = 32'h0000_0004;
      payload[(P_CART_EEPROM_CTRL >> 2) + 2] = 32'd0;
      payload[(P_CART_EEPROM_CTRL >> 2) + 3] = 32'h001f_ffe0;
    end
  endtask

  task automatic set_cart_eeprom_idle(input [10:0] size_words);
    begin
      payload[(P_CART_EEPROM_CTRL >> 2) + 0] = 32'd0;
      payload[(P_CART_EEPROM_CTRL >> 2) + 1] = 32'h0000_0020;
      payload[(P_CART_EEPROM_CTRL >> 2) + 2] =
          {4'd0, size_words, 11'd0, 6'd0};
      payload[(P_CART_EEPROM_CTRL >> 2) + 3] = 32'd0;
    end
  endtask

  task automatic build_profile(
      input [7:0] model,
      input [7:0] mapper,
      input [7:0] ramtype
  );
    integer word_index;
    reg [31:0] flags;
    reg [63:0] crc;
    begin
      current_model = model;
      current_mapper = mapper;
      current_ramtype = ramtype;
      current_active_bios = model;
      current_active_bios_crc64 = model == V2_MODEL_COLOR ?
          64'h5555_6666_7777_8888 : 64'h1111_2222_3333_4444;
      current_rom_footer[7:0] = ramtype;

      for (word_index = 0; word_index < PAYLOAD_WORDS;
           word_index = word_index + 1)
        payload[word_index] = 32'd0;

      set_internal_eeprom_idle(model == V2_MODEL_COLOR ? 11'd1024 : 11'd64);
      if (v2_expected_cart_eeprom_bytes(ramtype) == 0)
        set_cart_eeprom_off();
      else
        set_cart_eeprom_idle(v2_expected_cart_eeprom_bytes(ramtype)[11:1]);

      flags = 32'd0;
      if (v2_expected_sram_bytes(ramtype) != 0)
        flags = flags | V2_FEATURE_SRAM;
      if (v2_expected_cart_eeprom_bytes(ramtype) != 0)
        flags = flags | V2_FEATURE_CART_EEPROM;
      if (model == V2_MODEL_COLOR)
        flags = flags | V2_FEATURE_COLOR;
      if (mapper == V2_MAPPER_2003)
        flags = flags | V2_FEATURE_CART_RTC;

      for (word_index = 0; word_index < 64; word_index = word_index + 1)
        header[word_index] = 32'd0;
      header[0] = V2_MAGIC;
      header[1] = V2_ENVELOPE_VERSION;
      header[2] = V2_HEADER_BYTES;
      header[3] = V2_PAYLOAD_BYTES;
      header[4] = V2_TOTAL_BYTES;
      header[5] = V2_FORMAT_ID;
      header[6] = flags;
      header[8] = current_rom_bytes;
      header[9] = {model, mapper, ramtype, model};
      header[10] = V2_SETTINGS_HARD_MATCH;
      header[11] = current_settings & V2_SETTINGS_ALLOWED;
      header[12] = current_rom_crc64[63:32];
      header[13] = current_rom_crc64[31:0];
      header[14] = current_active_bios_crc64[63:32];
      header[15] = current_active_bios_crc64[31:0];
      header[16] = 32'h1111_2222;
      header[17] = 32'h3333_4444;
      header[18] = 32'h5555_6666;
      header[19] = 32'h7777_8888;
      header[24] = model == V2_MODEL_COLOR ? V2_COLOR_IRAM_BYTES :
                                                   V2_MONO_IRAM_BYTES;
      header[25] = v2_expected_sram_bytes(ramtype);
      header[26] = v2_expected_cart_eeprom_bytes(ramtype);
      header[27] = model == V2_MODEL_COLOR ? V2_COLOR_INTERNAL_BYTES :
                                                   V2_MONO_INTERNAL_BYTES;
      header[28] = 32'd0;
      {header[29], header[30], header[31], header[32]} = current_rom_footer;
      {header[33], header[34], header[35], header[36]} = V2_ABI_ID;
      header[37] = V2_CPU_SCHEMA;
      header[38] = V2_PPU_SCHEMA;
      header[39] = V2_APU_SCHEMA;
      header[40] = V2_DEVICE_SCHEMA;
      header[41] = V2_CAPTURE_POLICY;
      header[42] = V2_RTC_EXACT;
      crc = payload_crc64();
      header[22] = crc[63:32];
      header[23] = crc[31:0];
      crc = header_crc64();
      header[62] = crc[63:32];
      header[63] = crc[31:0];
    end
  endtask

  task automatic refresh_crcs;
    reg [63:0] crc;
    begin
      crc = payload_crc64();
      header[22] = crc[63:32];
      header[23] = crc[31:0];
      crc = header_crc64();
      header[62] = crc[63:32];
      header[63] = crc[31:0];
    end
  endtask

  task automatic send_word(input [31:0] offset, input [31:0] value);
    integer wait_cycles;
    begin
      @(negedge clk);
      copy_word_offset = offset;
      copy_word_data = value;
      copy_word_valid = 1'b1;
      wait_cycles = 0;
      while (!copy_word_ready) begin
        @(negedge clk);
        wait_cycles = wait_cycles + 1;
        if (wait_cycles > 20)
          $fatal(1, "copy word never became ready offset=%08x", offset);
      end
      @(negedge clk);
      copy_word_valid = 1'b0;
    end
  endtask

  // Used only after wait_read_response has stopped on a negedge with a live
  // response.  Unlike send_word, this deliberately does not consume another
  // half-cycle before presenting offset zero, so replacement acceptance sees
  // the backend's pre-edge nonquiescent state and must enter COPY_DRAIN.
  task automatic send_zero_while_response_pending;
    begin
      copy_word_offset = 32'd0;
      copy_word_data = header[0];
      copy_word_valid = 1'b1;
      #1ps;
      expect_true(copy_word_ready,
                  "pending-response replacement was backpressured");
      @(negedge clk);
      copy_word_valid = 1'b0;
    end
  endtask

  task automatic send_zero_with_finalize;
    begin
      @(negedge clk);
      copy_word_offset = 32'd0;
      copy_word_data = header[0];
      copy_word_valid = 1'b1;
      copy_finalize = 1'b1;
      expect_true(copy_word_ready,
                  "offset-zero finalize was unexpectedly backpressured");
      @(negedge clk);
      copy_word_valid = 1'b0;
      copy_finalize = 1'b0;
    end
  endtask

  task automatic submit_complete_image;
    integer word_index;
    integer wait_cycles;
    begin
      @(negedge clk);
      copy_word_valid = 1'b1;
      copy_word_offset = 32'd0;
      copy_word_data = header[0];
      wait_cycles = 0;
      while (!copy_word_ready) begin
        @(negedge clk);
        wait_cycles = wait_cycles + 1;
        if (wait_cycles > 20)
          $fatal(1, "streamed image never accepted offset zero");
      end
      for (word_index = 0; word_index < 64; word_index = word_index + 1) begin
        copy_word_offset = word_index * 4;
        copy_word_data = header[word_index];
        if (!copy_word_ready)
          $fatal(1, "streamed header backpressured at word %0d", word_index);
        @(negedge clk);
      end
      for (word_index = 0; word_index < PAYLOAD_WORDS;
           word_index = word_index + 1) begin
        copy_word_offset = V2_HEADER_BYTES + word_index * 4;
        copy_word_data = payload[word_index];
        if (!copy_word_ready)
          $fatal(1, "streamed payload backpressured at word %0d", word_index);
        @(negedge clk);
      end
      copy_word_valid = 1'b0;
      if (force_nonquiescent_on_finalize)
        force_stage_nonquiescent = 1'b1;
      copy_finalize = 1'b1;
      @(negedge clk);
      copy_finalize = 1'b0;
    end
  endtask

  task automatic submit_image_except_last;
    integer word_index;
    integer wait_cycles;
    begin
      @(negedge clk);
      copy_word_valid = 1'b1;
      copy_word_offset = 32'd0;
      copy_word_data = header[0];
      wait_cycles = 0;
      while (!copy_word_ready) begin
        @(negedge clk);
        wait_cycles = wait_cycles + 1;
        if (wait_cycles > 20)
          $fatal(1, "race image never accepted offset zero");
      end
      for (word_index = 0; word_index < 64; word_index = word_index + 1) begin
        copy_word_offset = word_index * 4;
        copy_word_data = header[word_index];
        if (!copy_word_ready)
          $fatal(1, "race header backpressured at word %0d", word_index);
        @(negedge clk);
      end
      for (word_index = 0; word_index < PAYLOAD_WORDS - 1;
           word_index = word_index + 1) begin
        copy_word_offset = V2_HEADER_BYTES + word_index * 4;
        copy_word_data = payload[word_index];
        if (!copy_word_ready)
          $fatal(1, "race payload backpressured at word %0d", word_index);
        @(negedge clk);
      end
      copy_word_valid = 1'b0;
    end
  endtask

  task automatic wait_preflight_terminal(
      input bit expect_success,
      input [3:0] expected_failure,
      input string label_text
  );
    integer wait_cycles;
    begin
      wait_cycles = 0;
      while (!preflight_done && !preflight_failed) begin
        @(negedge clk);
        wait_cycles = wait_cycles + 1;
        if (wait_cycles > 1_000_000)
          $fatal(1, "%s timed out", label_text);
      end
      if (expect_success) begin
        expect_true(preflight_done && !preflight_failed,
                    {label_text, " did not succeed"});
        expect_true(staged_image_valid && failure_reason == 0,
                    {label_text, " did not publish validity"});
      end else begin
        expect_true(preflight_failed && !preflight_done,
                    {label_text, " did not fail"});
        expect_true(!staged_image_valid && failure_reason == expected_failure,
                    {label_text, " reported wrong failure"});
      end
      @(negedge clk);
    end
  endtask

  task automatic wait_stage_start(input string label_text);
    integer wait_cycles;
    begin
      wait_cycles = 0;
      while (!stage_transfer_start) begin
        @(negedge clk);
        wait_cycles = wait_cycles + 1;
        if (wait_cycles > 512)
          $fatal(1, "%s stage start wait timed out", label_text);
      end
    end
  endtask

  task automatic wait_read_request(input string label_text);
    integer wait_cycles;
    begin
      wait_cycles = 0;
      while (!read_request_valid) begin
        @(negedge clk);
        wait_cycles = wait_cycles + 1;
        if (wait_cycles > 512)
          $fatal(1, "%s read request wait timed out", label_text);
      end
    end
  endtask

  task automatic wait_read_response(input string label_text);
    integer wait_cycles;
    begin
      wait_cycles = 0;
      while (!(read_word_valid && read_word_ready)) begin
        @(negedge clk);
        wait_cycles = wait_cycles + 1;
        if (wait_cycles > 512)
          $fatal(1, "%s read response wait timed out", label_text);
      end
    end
  endtask

  task automatic pulse_restore_request;
    begin
      @(negedge clk);
      restore_request = 1'b1;
      @(negedge clk);
      restore_request = 1'b0;
    end
  endtask

  task automatic exercise_owner_success;
    integer wait_cycles;
    integer starts_before;
    begin
      starts_before = restore_start_count;
      pulse_restore_request();
      expect_true(restore_busy && runtime_pause_request,
                  "validated image did not enter owner pause");

      // A locked replacement must not be accepted or invalidate generation.
      copy_word_offset = 32'd0;
      copy_word_data = header[0];
      copy_word_valid = 1'b1;
      @(negedge clk);
      expect_true(!copy_word_ready && staged_image_valid,
                  "owner lock did not protect staged image");
      copy_word_valid = 1'b0;

      runtime_pause_ack = 1'b1;
      @(negedge clk);
      device_frozen = 3'b111;
      wait_cycles = 0;
      while (!stage_acquire) begin
        @(negedge clk);
        wait_cycles = wait_cycles + 1;
        if (wait_cycles > 20)
          $fatal(1, "owner did not acquire stage");
      end
      stage_granted = 1'b1;
      @(negedge clk);
      expect_true(restore_apply_start,
                  "validated generation did not reach restore apply");
      @(negedge clk);
      expect_true(restore_start_count == starts_before + 1,
                  "restore apply pulse count was not exact");
      restore_apply_complete = 1'b1;
      @(negedge clk);
      restore_apply_complete = 1'b0;
      @(negedge clk);
      stage_granted = 1'b0;
      @(negedge clk);
      device_frozen = 3'b000;
      @(negedge clk);
      runtime_pause_ack = 1'b0;
      @(negedge clk);
      expect_true(restore_done && !restore_failed && !fatal_reset_hold,
                  "owner did not complete validated restore cleanly");
    end
  endtask

  task automatic exercise_capture_overwrite_invalidation;
    integer wait_cycles;
    integer restores_before;
    begin
      @(negedge clk);
      capture_request = 1'b1;
      @(negedge clk);
      capture_request = 1'b0;
      expect_true(capture_busy && runtime_pause_request,
                  "owner capture did not enter pause");
      runtime_pause_ack = 1'b1;
      @(negedge clk);
      device_frozen = 3'b111;
      wait_cycles = 0;
      while (!stage_acquire) begin
        @(negedge clk);
        wait_cycles = wait_cycles + 1;
        if (wait_cycles > 20)
          $fatal(1, "capture did not acquire stage");
      end
      stage_granted = 1'b1;
      @(negedge clk);
      expect_true(capture_start,
                  "capture overwrite did not start data plane");
      @(negedge clk);
      expect_true(!staged_image_valid &&
                  failure_reason == FAILURE_STAGE_CHANGED,
                  "capture overwrite retained old preflight generation");
      capture_complete = 1'b1;
      @(negedge clk);
      capture_complete = 1'b0;
      @(negedge clk);
      stage_granted = 1'b0;
      @(negedge clk);
      device_frozen = 3'b000;
      @(negedge clk);
      runtime_pause_ack = 1'b0;
      @(negedge clk);
      expect_true(capture_done && !capture_failed,
                  "capture overwrite owner transaction failed");

      restores_before = restore_start_count;
      pulse_restore_request();
      expect_true(restore_failed && !restore_busy &&
                  restore_start_count == restores_before,
                  "capture-overwritten bytes reused old validation");
    end
  endtask

  integer generation_before;
  integer responses_before;
  integer starts_before;
  integer word_index;
  initial begin
    repeat (4) @(negedge clk);
    reset_n = 1'b1;
    repeat (2) @(negedge clk);

    // Three profile-complete golden images prove the exact fixed scan for
    // mono/no-cart, Color/max-SRAM, and Color/mapper-2003/cart-EEPROM.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    generation_before = staged_image_generation;
    responses_before = payload_response_count;
    submit_complete_image();
    wait_preflight_terminal(1'b1, 0, "mono golden");
    expect_true(staged_image_generation == generation_before + 1,
                "mono golden generation did not advance once");
    expect_true(payload_response_count - responses_before == PAYLOAD_WORDS,
                "mono golden did not scan every payload word");
    exercise_owner_success();
    send_zero_with_finalize();
    wait_preflight_terminal(1'b0, FAILURE_COPY_LENGTH,
                            "valid-state offset-zero finalize");

    build_profile(V2_MODEL_COLOR, V2_MAPPER_2001, V2_RAM_SRAM_512K);
    generation_before = staged_image_generation;
    responses_before = payload_response_count;
    submit_complete_image();
    wait_preflight_terminal(1'b1, 0, "Color SRAM golden");
    expect_true(staged_image_generation == generation_before + 1,
                "Color SRAM generation did not advance once");
    expect_true(payload_response_count - responses_before == PAYLOAD_WORDS,
                "Color SRAM did not scan every payload word");

    generation_before = staged_image_generation;
    send_word(32'd4, 32'hdead_beef);
    wait_preflight_terminal(1'b0, FAILURE_COPY_ORDER,
                            "valid-image nonzero first word");
    expect_true(staged_image_generation == generation_before,
                "malformed first word advanced generation");

    build_profile(V2_MODEL_COLOR, V2_MAPPER_2003, V2_RAM_EEPROM_2K);
    generation_before = staged_image_generation;
    submit_complete_image();
    wait_preflight_terminal(1'b1, 0, "Color EEPROM golden");
    expect_true(staged_image_generation == generation_before + 1,
                "Color EEPROM generation did not advance once");

    // The validated identity remains a live compatibility condition until the
    // owner accepts restore; a title/BIOS/turbo drift invalidates immediately.
    current_active_bios_crc64 = current_active_bios_crc64 ^ 64'd1;
    wait_preflight_terminal(1'b0, FAILURE_HEADER_FIELDS,
                            "post-valid identity drift");
    current_active_bios_crc64 = current_active_bios_crc64 ^ 64'd1;

    // Header semantics are checked independently from integrity.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    header[1] = V1_ENVELOPE_VERSION;
    begin : refresh_bad_static_header_crc
      reg [63:0] crc;
      crc = header_crc64();
      header[62] = crc[63:32];
      header[63] = crc[31:0];
    end
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_HEADER_FIELDS,
                            "v1 static mutation");

    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    header[63] = header[63] ^ 32'd1;
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_HEADER_CRC,
                            "header CRC mutation");

    send_word(32'd4, 32'h1234_5678);
    wait_preflight_terminal(1'b0, FAILURE_COPY_ORDER,
                            "empty-state nonzero first word");
    send_zero_with_finalize();
    wait_preflight_terminal(1'b0, FAILURE_COPY_LENGTH,
                            "empty-state offset-zero finalize");

    // Mapper 2003 identity alone cannot authorize mutable flash state before
    // the missing bounded controller/schema is implemented.
    build_profile(V2_MODEL_COLOR, V2_MAPPER_2003, V2_RAM_EEPROM_2K);
    header[6] = header[6] | V2_FEATURE_FLASH;
    header[28] = V2_FLASH_ACTIVE_BYTES;
    refresh_crcs();
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_HEADER_FIELDS,
                            "unsupported flash capability");

    // A valid CRC cannot authorize nonzero deterministic padding.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    payload[P_MACHINE_RESERVE >> 2] = 32'h0100_0000;
    refresh_crcs();
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_PAYLOAD_ZERO,
                            "fixed padding mutation");

    // An active (non-padding) payload mutation reaches the CRC gate.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    payload[0] = 32'h0100_0000;
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_PAYLOAD_CRC,
                            "payload CRC mutation");

    // Device schemas remain separate from byte padding and CRC integrity.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    payload[(P_RTC >> 2)] = 32'h0000_0700; // index 7 is unreachable
    refresh_crcs();
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_RTC, "RTC schema mutation");

    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    payload[(P_INTERNAL_EEPROM_CTRL >> 2) + 2] =
        {4'd0, 11'd63, 11'd0, 6'd0};
    refresh_crcs();
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_INTERNAL_EEPROM,
                            "internal EEPROM size mutation");

    build_profile(V2_MODEL_COLOR, V2_MAPPER_2003, V2_RAM_EEPROM_2K);
    payload[(P_CART_EEPROM_CTRL >> 2) + 1] = 32'h0000_0028;
    refresh_crcs();
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_CART_EEPROM,
                            "cart EEPROM protection mutation");

    // Copy structure rejects gaps and short finalize before a scan can start.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    send_word(0, header[0]);
    send_word(8, header[2]);
    wait_preflight_terminal(1'b0, FAILURE_COPY_ORDER, "copy gap");

    send_word(0, header[0]);
    send_word(4, header[1]);
    @(negedge clk);
    copy_finalize = 1'b1;
    @(negedge clk);
    copy_finalize = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_COPY_LENGTH, "short finalize");

    // WAIT_STAGE_DRAIN cannot be escaped by any new A4/writer signal while
    // the prior durable commit remains nonquiescent.
    force_nonquiescent_on_finalize = 1'b1;
    submit_complete_image();
    force_nonquiescent_on_finalize = 1'b0;
    external_stage_content_changed = 1'b1;
    @(negedge clk);
    external_stage_content_changed = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_STAGE_CHANGED,
                            "content change during final-write drain");
    expect_true(stage_abort,
                "content change escaped final-write drain");
    force_stage_nonquiescent = 1'b0;
    @(negedge clk);

    force_nonquiescent_on_finalize = 1'b1;
    submit_complete_image();
    force_nonquiescent_on_finalize = 1'b0;
    send_word(V2_HEADER_BYTES + 32'd4, 32'h1122_3344);
    wait_preflight_terminal(1'b0, FAILURE_COPY_ORDER,
                            "nonzero word during final-write drain");
    expect_true(stage_abort,
                "nonzero word escaped final-write drain");
    force_stage_nonquiescent = 1'b0;
    @(negedge clk);

    force_nonquiescent_on_finalize = 1'b1;
    submit_complete_image();
    force_nonquiescent_on_finalize = 1'b0;
    copy_finalize = 1'b1;
    @(negedge clk);
    copy_finalize = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_COPY_LENGTH,
                            "repeated finalize during final-write drain");
    expect_true(stage_abort,
                "repeated finalize escaped final-write drain");
    force_stage_nonquiescent = 1'b0;
    @(negedge clk);

    force_nonquiescent_on_finalize = 1'b1;
    submit_complete_image();
    force_nonquiescent_on_finalize = 1'b0;
    send_zero_with_finalize();
    wait_preflight_terminal(1'b0, FAILURE_COPY_LENGTH,
                            "offset-zero finalize during final-write drain");
    expect_true(stage_abort,
                "offset-zero finalize escaped final-write drain");
    force_stage_nonquiescent = 1'b0;
    @(negedge clk);

    // Copy ownership itself is terminally invalidated by abort or an external
    // writer; the host must never remain busy without a failure result.
    send_word(0, header[0]);
    external_stage_content_changed = 1'b1;
    @(negedge clk);
    external_stage_content_changed = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_STAGE_CHANGED,
                            "content change during copy");

    send_word(0, header[0]);
    abort = 1'b1;
    @(negedge clk);
    abort = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_ABORT, "abort during copy");

    submit_complete_image();
    wait_read_response("abort copy drain");
    ignore_stage_abort = 1'b1;
    send_zero_while_response_pending();
    expect_true(stage_abort && copy_active,
                "replacement did not enter copy drain");
    abort = 1'b1;
    @(negedge clk);
    abort = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_ABORT,
                            "abort during copy drain");
    ignore_stage_abort = 1'b0;
    @(negedge clk);
    expect_true(!copy_active && !staged_image_valid,
                "abort drain resurrected copy");

    submit_complete_image();
    wait_read_response("content copy drain");
    ignore_stage_abort = 1'b1;
    send_zero_while_response_pending();
    expect_true(stage_abort && copy_active,
                "replacement did not enter content copy drain");
    external_stage_content_changed = 1'b1;
    @(negedge clk);
    external_stage_content_changed = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_STAGE_CHANGED,
                            "content change during copy drain");
    expect_true(!copy_active && !staged_image_valid,
                "content change resurrected drained copy");
    ignore_stage_abort = 1'b0;
    @(negedge clk);
    expect_true(!copy_active && !staged_image_valid,
                "content-change drain resurrected copy");

    submit_complete_image();
    wait_read_response("finalize copy drain");
    ignore_stage_abort = 1'b1;
    send_zero_while_response_pending();
    expect_true(stage_abort && copy_active,
                "replacement did not enter finalize copy drain");
    copy_finalize = 1'b1;
    @(negedge clk);
    copy_finalize = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_COPY_LENGTH,
                            "finalize during copy drain");
    expect_true(!copy_active && !staged_image_valid,
                "finalize resurrected drained copy");
    ignore_stage_abort = 1'b0;
    @(negedge clk);

    // Once in the generic failure drain, later writer/finalize notifications
    // may update the diagnostic but can never revoke abort ownership.
    submit_complete_image();
    wait_read_response("held failure drain");
    ignore_stage_abort = 1'b1;
    force_stage_nonquiescent = 1'b1;
    abort = 1'b1;
    @(negedge clk);
    abort = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_ABORT,
                            "enter held failure drain");
    external_stage_content_changed = 1'b1;
    @(negedge clk);
    external_stage_content_changed = 1'b0;
    expect_true(stage_abort && !stage_quiescent_to_dut,
                "content change escaped failure drain");
    copy_finalize = 1'b1;
    @(negedge clk);
    copy_finalize = 1'b0;
    expect_true(stage_abort && !stage_quiescent_to_dut,
                "finalize escaped failure drain");
    repeat (70) begin
      @(negedge clk);
      expect_true(stage_abort && preflight_busy && !staged_image_valid,
                  "stuck failure drain released ownership after watchdog");
    end
    expect_true(protocol_error,
                "stuck failure drain did not record watchdog fault");
    ignore_stage_abort = 1'b0;
    force_stage_nonquiescent = 1'b0;
    @(negedge clk);

    // Response-address and backend faults fail before validity publication.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    inject_offset_error = 1'b1;
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_STAGE_ORDER,
                            "stage offset mutation");
    inject_offset_error = 1'b0;

    inject_stage_error = 1'b1;
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_STAGE_BACKEND,
                            "stage backend error");
    inject_stage_error = 1'b0;

    inject_crc_clear_error = 1'b1;
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_STAGE_BACKEND,
                            "CRC-clear backend error pulse");
    inject_crc_clear_error = 1'b0;

    // Identity is also continuously checked during the long payload scan.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    hold_requests = 1'b1;
    submit_complete_image();
    wait_read_request("scan identity drift");
    current_rom_crc64 = current_rom_crc64 ^ 64'd1;
    hold_requests = 1'b0;
    #1ps;
    expect_true(!read_request_valid,
                "scan-time identity drift leaked ready request");
    wait_preflight_terminal(1'b0, FAILURE_HEADER_FIELDS,
                            "scan-time identity drift");
    current_rom_crc64 = current_rom_crc64 ^ 64'd1;

    hold_requests = 1'b1;
    submit_complete_image();
    wait_read_request("validation nonzero first");
    send_word(V2_HEADER_BYTES + 32'd4, 32'hfeed_face);
    wait_preflight_terminal(1'b0, FAILURE_COPY_ORDER,
                            "validation nonzero first word");
    hold_requests = 1'b0;

    hold_requests = 1'b1;
    submit_complete_image();
    wait_read_request("validation zero finalize");
    send_zero_with_finalize();
    wait_preflight_terminal(1'b0, FAILURE_COPY_LENGTH,
                            "validation offset-zero finalize");
    hold_requests = 1'b0;

    // A terminal backend fault after the last accepted word still wins over
    // CRC/schema success, and terminal quiescence itself is bounded.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    inject_late_terminal_error = 1'b1;
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_STAGE_BACKEND,
                            "late terminal backend error");
    inject_late_terminal_error = 1'b0;

    hold_terminal_quiescent = 1'b1;
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_STAGE_BACKEND,
                            "terminal quiescence timeout");
    hold_terminal_quiescent = 1'b0;

    // Each backend wait phase has a real watchdog.  Copy input remains
    // host-paced, but start, request, response, terminal, and abort drain do
    // not leave A4 polling busy forever.
    hold_stage_start = 1'b1;
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_STAGE_BACKEND,
                            "stage start timeout");
    hold_stage_start = 1'b0;

    hold_requests = 1'b1;
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_STAGE_BACKEND,
                            "read request timeout");
    hold_requests = 1'b0;

    drop_response = 1'b1;
    submit_complete_image();
    wait_preflight_terminal(1'b0, FAILURE_STAGE_BACKEND,
                            "read response timeout");
    drop_response = 1'b0;

    // Adversarial control exactly when backend ready rises must gate the
    // handshake combinationally; no unowned start/request may escape.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    hold_stage_start = 1'b1;
    submit_complete_image();
    wait_stage_start("abort start race");
    starts_before = stage_start_count;
    hold_stage_start = 1'b0;
    abort = 1'b1;
    #1ps;
    expect_true(!stage_transfer_start,
                "abort/start-ready race leaked transfer start");
    @(negedge clk);
    abort = 1'b0;
    expect_true(stage_start_count == starts_before &&
                failure_reason == FAILURE_ABORT,
                "abort/start-ready race was not contained");

    hold_stage_start = 1'b1;
    submit_complete_image();
    wait_stage_start("replacement start race");
    starts_before = stage_start_count;
    hold_stage_start = 1'b0;
    copy_word_offset = 32'd0;
    copy_word_data = header[0];
    copy_word_valid = 1'b1;
    #1ps;
    expect_true(copy_word_ready && !stage_transfer_start,
                "replacement/start-ready race leaked transfer start");
    @(negedge clk);
    copy_word_valid = 1'b0;
    expect_true(stage_start_count == starts_before && copy_active,
                "replacement/start-ready race did not restart copy");
    abort = 1'b1;
    @(negedge clk);
    abort = 1'b0;

    hold_requests = 1'b1;
    submit_complete_image();
    wait_read_request("abort request race");
    responses_before = payload_response_count;
    hold_requests = 1'b0;
    abort = 1'b1;
    #1ps;
    expect_true(!read_request_valid,
                "abort/read-ready race leaked request");
    @(negedge clk);
    abort = 1'b0;
    expect_true(payload_response_count == responses_before &&
                failure_reason == FAILURE_ABORT,
                "abort/read-ready race was not contained");

    // A stale level from the prior reader transaction is cleared by the next
    // accepted transfer_start. New failures can arise only after that edge.
    hold_stage_start = 1'b1;
    submit_complete_image();
    wait_stage_start("stale failure restart");
    starts_before = stage_start_count;
    hold_stage_start = 1'b0;
    force_stage_transfer_failed = 1'b1;
    #1ps;
    expect_true(stage_transfer_start_ready && stage_transfer_start,
                "stale failure blocked reader restart");
    @(negedge clk);
    force_stage_transfer_failed = 1'b0;
    expect_true(stage_start_count == starts_before + 1,
                "reader restart did not clear stale transaction");
    abort = 1'b1;
    @(negedge clk);
    abort = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_ABORT,
                            "abort after stale-failure restart");

    hold_requests = 1'b1;
    submit_complete_image();
    wait_read_request("same-edge request failure");
    hold_requests = 1'b0;
    force_stage_transfer_failed = 1'b1;
    #1ps;
    expect_true(read_request_ready && !read_request_valid,
                "same-edge request failure leaked handshake");
    @(negedge clk);
    force_stage_transfer_failed = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_STAGE_BACKEND,
                            "same-edge request failure");

    submit_complete_image();
    wait_read_response("same-edge response failure");
    responses_before = payload_response_count;
    force_stage_transfer_failed = 1'b1;
    #1ps;
    expect_true(!read_word_ready,
                "same-edge response failure consumed response");
    @(negedge clk);
    force_stage_transfer_failed = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_STAGE_BACKEND,
                            "same-edge response failure");
    expect_true(payload_response_count == responses_before,
                "failed response was counted");

    // A stray A4 finalize is also a cancellation barrier on every backend
    // handshake.  The frontend must not let the backend accept work on the
    // same edge that the transaction is being terminally rejected.
    hold_stage_start = 1'b1;
    submit_complete_image();
    wait_stage_start("finalize start race");
    starts_before = stage_start_count;
    hold_stage_start = 1'b0;
    copy_finalize = 1'b1;
    #1ps;
    expect_true(stage_transfer_start_ready && !stage_transfer_start,
                "finalize/start-ready race leaked start");
    @(negedge clk);
    copy_finalize = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_COPY_LENGTH,
                            "finalize start race");
    expect_true(stage_start_count == starts_before,
                "finalize start reached backend");

    hold_requests = 1'b1;
    submit_complete_image();
    wait_read_request("finalize request race");
    hold_requests = 1'b0;
    copy_finalize = 1'b1;
    #1ps;
    expect_true(read_request_ready && !read_request_valid,
                "finalize/request-ready race leaked request");
    @(negedge clk);
    copy_finalize = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_COPY_LENGTH,
                            "finalize request race");

    submit_complete_image();
    wait_read_response("finalize response race");
    responses_before = payload_response_count;
    copy_finalize = 1'b1;
    #1ps;
    expect_true(!read_word_ready,
                "finalize/response-ready race consumed response");
    @(negedge clk);
    copy_finalize = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_COPY_LENGTH,
                            "finalize response race");
    expect_true(payload_response_count == responses_before,
                "finalize-cancelled response was counted");

    // External stage mutation has identical gating at start, request, and a
    // held response. This represents any non-preflight writer, including A0.
    hold_stage_start = 1'b1;
    submit_complete_image();
    wait_stage_start("content start race");
    starts_before = stage_start_count;
    hold_stage_start = 1'b0;
    external_stage_content_changed = 1'b1;
    #1ps;
    expect_true(!stage_transfer_start && !copy_word_ready,
                "content-change/start-ready race leaked handshake");
    @(negedge clk);
    external_stage_content_changed = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_STAGE_CHANGED,
                            "content-change start race");
    expect_true(stage_start_count == starts_before,
                "content-change start reached backend");

    hold_requests = 1'b1;
    submit_complete_image();
    wait_read_request("content request race");
    hold_requests = 1'b0;
    external_stage_content_changed = 1'b1;
    #1ps;
    expect_true(!read_request_valid,
                "content-change/request-ready race leaked request");
    @(negedge clk);
    external_stage_content_changed = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_STAGE_CHANGED,
                            "content-change request race");

    submit_complete_image();
    wait_read_response("content response race");
    responses_before = payload_response_count;
    external_stage_content_changed = 1'b1;
    #1ps;
    expect_true(!read_word_ready,
                "content-change/response-ready race consumed response");
    @(negedge clk);
    external_stage_content_changed = 1'b0;
    wait_preflight_terminal(1'b0, FAILURE_STAGE_CHANGED,
                            "content-change response race");
    expect_true(payload_response_count == responses_before,
                "content-change response was counted");

    // Compatibility drift has the same start/response handshake exclusion.
    hold_stage_start = 1'b1;
    submit_complete_image();
    wait_stage_start("compatibility start race");
    starts_before = stage_start_count;
    hold_stage_start = 1'b0;
    current_settings = current_settings ^ V2_SETTINGS_HARD_MATCH;
    #1ps;
    expect_true(!stage_transfer_start,
                "compatibility/start-ready race leaked start");
    @(negedge clk);
    wait_preflight_terminal(1'b0, FAILURE_HEADER_FIELDS,
                            "compatibility start race");
    current_settings = current_settings ^ V2_SETTINGS_HARD_MATCH;
    expect_true(stage_start_count == starts_before,
                "compatibility-drift start reached backend");

    submit_complete_image();
    wait_read_response("compatibility response race");
    responses_before = payload_response_count;
    current_rom_bytes = current_rom_bytes ^ 32'd4;
    #1ps;
    expect_true(!read_word_ready,
                "compatibility/response-ready race consumed response");
    @(negedge clk);
    wait_preflight_terminal(1'b0, FAILURE_HEADER_FIELDS,
                            "compatibility response race");
    current_rom_bytes = current_rom_bytes ^ 32'd4;
    expect_true(payload_response_count == responses_before,
                "compatibility-drift response was counted");

    // Stalls neither complete nor validate early; abort invalidates and drains.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    hold_requests = 1'b1;
    submit_complete_image();
    wait_read_request("stalled abort");
    repeat (8) begin
      @(negedge clk);
      expect_true(preflight_busy && !preflight_done &&
                  !staged_image_valid,
                  "stalled read validated early");
    end
    abort = 1'b1;
    @(negedge clk);
    abort = 1'b0;
    hold_requests = 1'b0;
    expect_true(failure_reason == FAILURE_ABORT && !staged_image_valid,
                "abort did not invalidate stalled validation");

    // Invalid staged state can never make the owner pause or apply.
    starts_before = restore_start_count;
    pulse_restore_request();
    expect_true(restore_failed && !restore_busy && !runtime_pause_request &&
                restore_start_count == starts_before,
                "invalid preflight state crossed owner barrier");

    // Final-word/finalize race: the exact last committed word may finalize on
    // the same edge, but validity still waits for every payload response.
    build_profile(V2_MODEL_MONO, V2_MAPPER_2001, V2_RAM_NONE);
    submit_image_except_last();
    @(negedge clk);
    copy_word_offset = V2_TOTAL_BYTES - 4;
    copy_word_data = payload[PAYLOAD_WORDS-1];
    copy_word_valid = 1'b1;
    copy_finalize = 1'b1;
    @(negedge clk);
    copy_word_valid = 1'b0;
    copy_finalize = 1'b0;
    expect_true(!staged_image_valid && !preflight_done,
                "final committed word published validity early");
    responses_before = payload_response_count;
    generation_before = staged_image_generation;
    wait_preflight_terminal(1'b1, 0, "same-edge final word");
    expect_true(payload_response_count - responses_before == PAYLOAD_WORDS,
                "same-edge finalize skipped payload responses");
    expect_true(staged_image_generation == generation_before + 1,
                "same-edge finalize generation count wrong");

    exercise_capture_overwrite_invalidation();

    $display("PASS APF savestate v2 structural/integrity/profile/device preflight profiles=3 exact_bytes=%0d payload_words=%0d mutations=13 copy_failures=2 backend_failures=10 owner_apply=%0d generation=%0d final_race=1 abort=1 lock=1 capture_invalidation=1 semantic_gate_pending=1",
             V2_TOTAL_BYTES, PAYLOAD_WORDS, restore_start_count,
             staged_image_generation);
    $finish;
  end
endmodule

`default_nettype wire
