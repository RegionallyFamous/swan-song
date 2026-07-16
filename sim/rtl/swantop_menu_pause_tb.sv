`timescale 1ps/1ps

// Exercises the real GHDL-translated SwanTop scheduler from the built-in mono
// Open IPL. The IPL locks its boot ROM and enters a synthetic cartridge whose
// program performs one external ROM read, one cartridge-SRAM write, and one
// SRAM readback, publishing the read values into IRAM. Pause is asserted while
// each watched one-clk_sys request pulse is live. A deliberately slow memory
// model completes the watched transaction while the console is frozen.
module swantop_menu_pause_tb;
  localparam [24:0] ROM_ADDRESS = 25'h0000000;
  localparam [24:0] CARTRIDGE_PROGRAM_ADDRESS = 25'h0000100;
  localparam [24:0] CARTRIDGE_RESET_ADDRESS = 25'h000fff0;
  localparam [24:0] SRAM_ADDRESS = 25'h1000000;
  localparam [15:0] ROM_SENTINEL = 16'h4d52;
  localparam [15:0] SRAM_INITIAL = 16'hd00d;
  localparam [15:0] SRAM_WRITTEN = 16'ha55a;

  reg clk = 1'b0;
  reg clk_ram = 1'b0;
  always #5000 clk = ~clk;

  integer ram_phase_ps = 0;
  initial begin
    if (!$value$plusargs("ram_phase_ps=%d", ram_phase_ps))
      ram_phase_ps = 0;
    case (ram_phase_ps)
      0: ;
      833: #833;
      1666: #1666;
      2499: #2499;
      default: $fatal(1, "unsupported RAM clock phase: %0d", ram_phase_ps);
    endcase
    forever #1667 clk_ram = ~clk_ram;
  end

  reg reset_in = 1'b1;
  reg pause_in = 1'b0;
  reg preserve_internal_eeprom = 1'b1;
  reg memories_pause_request = 1'b0;
  reg [15:0] EXTRAM_dataread = 16'h0000;
  reg [9:0] eeprom_addr = 10'd0;
  reg [15:0] eeprom_din = 16'd0;
  reg eeprom_req = 1'b0;
  reg eeprom_rnw = 1'b1;
  reg internal_eeprom_bank = 1'b0;
  reg [9:0] internal_eeprom_addr = 10'd0;
  reg [15:0] internal_eeprom_din = 16'd0;
  reg internal_eeprom_req = 1'b0;
  reg internal_eeprom_rnw = 1'b1;
  reg [23:0] maskAddr = 24'h00ffff;
  reg [7:0] romtype = 8'd0;
  reg [7:0] ramtype = 8'h01;
  reg hasRTC = 1'b1;
  reg open_ipl_word_width = 1'b1;
  reg open_ipl_protect_owner_area = 1'b1;
  reg isColor = 1'b0;
  reg fastforward = 1'b0;
  reg turbo = 1'b0;
  reg KeyY1 = 1'b0;
  reg KeyY2 = 1'b0;
  reg KeyY3 = 1'b0;
  reg KeyY4 = 1'b0;
  reg KeyX1 = 1'b0;
  reg KeyX2 = 1'b0;
  reg KeyX3 = 1'b0;
  reg KeyX4 = 1'b0;
  reg KeyStart = 1'b0;
  reg KeyA = 1'b0;
  reg KeyB = 1'b0;
  reg RTC_timestampNew = 1'b0;
  reg [31:0] RTC_timestampIn = 32'd0;
  reg [31:0] RTC_timestampSaved = 32'd0;
  reg [41:0] RTC_savedtimeIn = 42'd0;
  reg RTC_saveLoaded = 1'b0;
  reg rtc_state_freeze = 1'b0;
  reg rtc_state_load = 1'b0;
  reg [255:0] rtc_state_data_in = 256'd0;
  reg internal_eeprom_state_freeze = 1'b0;
  reg internal_eeprom_state_load = 1'b0;
  reg [127:0] internal_eeprom_state_in = 128'd0;
  reg cartridge_eeprom_state_freeze = 1'b0;
  reg cartridge_eeprom_state_load = 1'b0;
  reg [127:0] cartridge_eeprom_state_in = 128'd0;
  reg increaseSSHeaderCount = 1'b0;
  reg save_state = 1'b0;
  reg load_state = 1'b0;
  reg [1:0] savestate_number = 2'd0;
  reg [63:0] SAVE_out_Dout = 64'd0;
  reg SAVE_out_done = 1'b0;
  reg rewind_on = 1'b0;
  reg rewind_active = 1'b0;

  wire EXTRAM_doRefresh;
  wire EXTRAM_read;
  wire EXTRAM_write;
  wire [1:0] EXTRAM_be;
  wire [24:0] EXTRAM_addr;
  wire [15:0] EXTRAM_datawrite;
  wire [14:0] pixel_out_addr;
  wire [11:0] pixel_out_data;
  wire pixel_out_we;
  wire [15:0] audio_l;
  wire [15:0] audio_r;
  wire [255:0] rtc_state_data_out;
  wire debug_console_ce;
  wire debug_cpu_ce;
  wire debug_memory_ce;
  wire debug_refresh;
  wire [1:0] debug_resume_wait;
  wire debug_mem_valid;
  wire debug_mem_write;
  wire [19:0] debug_mem_address;
  wire [15:0] debug_mem_value;
  wire [1:0] debug_mem_byte_enable;
  wire [3:0] debug_mem_space;

  SwanTop dut (
      .clk(clk),
      .clk_ram(clk_ram),
      .reset_in(reset_in),
      .pause_in(pause_in),
      .preserve_internal_eeprom(preserve_internal_eeprom),
      .memories_pause_request(memories_pause_request),
      .EXTRAM_doRefresh(EXTRAM_doRefresh),
      .EXTRAM_read(EXTRAM_read),
      .EXTRAM_write(EXTRAM_write),
      .EXTRAM_be(EXTRAM_be),
      .EXTRAM_addr(EXTRAM_addr),
      .EXTRAM_datawrite(EXTRAM_datawrite),
      .EXTRAM_dataread(EXTRAM_dataread),
      .eeprom_addr(eeprom_addr),
      .eeprom_din(eeprom_din),
      .eeprom_req(eeprom_req),
      .eeprom_rnw(eeprom_rnw),
      .internal_eeprom_bank(internal_eeprom_bank),
      .internal_eeprom_addr(internal_eeprom_addr),
      .internal_eeprom_din(internal_eeprom_din),
      .internal_eeprom_req(internal_eeprom_req),
      .internal_eeprom_rnw(internal_eeprom_rnw),
      .maskAddr(maskAddr),
      .romtype(romtype),
      .ramtype(ramtype),
      .hasRTC(hasRTC),
      .open_ipl_word_width(open_ipl_word_width),
      .open_ipl_protect_owner_area(open_ipl_protect_owner_area),
      .pixel_out_addr(pixel_out_addr),
      .pixel_out_data(pixel_out_data),
      .pixel_out_we(pixel_out_we),
      .audio_l(audio_l),
      .audio_r(audio_r),
      .isColor(isColor),
      .fastforward(fastforward),
      .turbo(turbo),
      .KeyY1(KeyY1),
      .KeyY2(KeyY2),
      .KeyY3(KeyY3),
      .KeyY4(KeyY4),
      .KeyX1(KeyX1),
      .KeyX2(KeyX2),
      .KeyX3(KeyX3),
      .KeyX4(KeyX4),
      .KeyStart(KeyStart),
      .KeyA(KeyA),
      .KeyB(KeyB),
      .RTC_timestampNew(RTC_timestampNew),
      .RTC_timestampIn(RTC_timestampIn),
      .RTC_timestampSaved(RTC_timestampSaved),
      .RTC_savedtimeIn(RTC_savedtimeIn),
      .RTC_saveLoaded(RTC_saveLoaded),
      .rtc_state_freeze(rtc_state_freeze),
      .rtc_state_load(rtc_state_load),
      .rtc_state_data_in(rtc_state_data_in),
      .rtc_state_data_out(rtc_state_data_out),
      .internal_eeprom_state_freeze(internal_eeprom_state_freeze),
      .internal_eeprom_state_load(internal_eeprom_state_load),
      .internal_eeprom_state_in(internal_eeprom_state_in),
      .cartridge_eeprom_state_freeze(cartridge_eeprom_state_freeze),
      .cartridge_eeprom_state_load(cartridge_eeprom_state_load),
      .cartridge_eeprom_state_in(cartridge_eeprom_state_in),
      .increaseSSHeaderCount(increaseSSHeaderCount),
      .save_state(save_state),
      .load_state(load_state),
      .savestate_number(savestate_number),
      .SAVE_out_Dout(SAVE_out_Dout),
      .SAVE_out_done(SAVE_out_done),
      .rewind_on(rewind_on),
      .rewind_active(rewind_active),
      .debug_console_ce(debug_console_ce),
      .debug_cpu_ce(debug_cpu_ce),
      .debug_memory_ce(debug_memory_ce),
      .debug_refresh(debug_refresh),
      .debug_resume_wait(debug_resume_wait),
      .debug_mem_valid(debug_mem_valid),
      .debug_mem_write(debug_mem_write),
      .debug_mem_address(debug_mem_address),
      .debug_mem_value(debug_mem_value),
      .debug_mem_byte_enable(debug_mem_byte_enable),
      .debug_mem_space(debug_mem_space)
  );

  task automatic tick;
    begin
      @(posedge clk);
      #1;
    end
  endtask

  // A 64 KiB cartridge image. The footer reset vector jumps from FFFF:0000 to
  // 2000:0100, keeping offset 0000 free for the watched ROM data read. Words
  // are little-endian, exactly as they appear on the 16-bit cartridge bus.
  function automatic [15:0] cartridge_word(input [24:0] byte_address);
    begin
      case (byte_address)
        ROM_ADDRESS: cartridge_word = ROM_SENTINEL;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h00: cartridge_word = 16'hb8fa;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h02: cartridge_word = 16'h2000;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h04: cartridge_word = 16'hd88e;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h06: cartridge_word = 16'h00a1;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h08: cartridge_word = 16'h8900;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h0a: cartridge_word = 16'hb8c3;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h0c: cartridge_word = 16'h0000;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h0e: cartridge_word = 16'hd88e;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h10: cartridge_word = 16'h1e89;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h12: cartridge_word = 16'h0100;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h14: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h16: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h18: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h1a: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h1c: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h1e: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h20: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h22: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h24: cartridge_word = 16'h00b8;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h26: cartridge_word = 16'h8e10;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h28: cartridge_word = 16'hb8d8;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h2a: cartridge_word = 16'ha55a;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h2c: cartridge_word = 16'h00a3;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h2e: cartridge_word = 16'h9000;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h30: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h32: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h34: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h36: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h38: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h3a: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h3c: cartridge_word = 16'h9090;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h3e: cartridge_word = 16'ha190;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h40: cartridge_word = 16'h0000;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h42: cartridge_word = 16'hc389;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h44: cartridge_word = 16'h00b8;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h46: cartridge_word = 16'h8e00;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h48: cartridge_word = 16'h89d8;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h4a: cartridge_word = 16'h021e;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h4c: cartridge_word = 16'hf401;
        CARTRIDGE_PROGRAM_ADDRESS + 25'h4e: cartridge_word = 16'hfeeb;
        CARTRIDGE_RESET_ADDRESS + 25'h0: cartridge_word = 16'h00ea;
        CARTRIDGE_RESET_ADDRESS + 25'h2: cartridge_word = 16'h0001;
        CARTRIDGE_RESET_ADDRESS + 25'h4: cartridge_word = 16'h9020;
        default: cartridge_word = 16'h9090;
      endcase
    end
  endfunction

  // External requests are single clk_sys pulses. Capture their edge in the
  // independent RAM domain, then delay service well beyond nominal SDRAM M3
  // write/M8 read timing. This makes response retention across pause observable.
  reg prev_read_ram = 1'b0;
  reg prev_write_ram = 1'b0;
  reg read_pending = 1'b0;
  reg write_pending = 1'b0;
  reg [5:0] read_delay = 6'd0;
  reg [5:0] write_delay = 6'd0;
  reg [24:0] captured_read_addr = 25'd0;
  reg [24:0] captured_write_addr = 25'd0;
  reg [1:0] captured_write_be = 2'd0;
  reg [15:0] captured_write_data = 16'd0;
  reg [15:0] sram_word = SRAM_INITIAL;
  integer memory_read_completions = 0;
  integer memory_write_commits = 0;

  always @(posedge clk_ram) begin
    if (reset_in) begin
      prev_read_ram <= 1'b0;
      prev_write_ram <= 1'b0;
      read_pending <= 1'b0;
      write_pending <= 1'b0;
      read_delay <= 6'd0;
      write_delay <= 6'd0;
      captured_read_addr <= 25'd0;
      captured_write_addr <= 25'd0;
      captured_write_be <= 2'd0;
      captured_write_data <= 16'd0;
      EXTRAM_dataread <= 16'h0000;
      sram_word <= SRAM_INITIAL;
      memory_read_completions <= 0;
      memory_write_commits <= 0;
    end else begin
      prev_read_ram <= EXTRAM_read;
      prev_write_ram <= EXTRAM_write;

      if (EXTRAM_read && !prev_read_ram) begin
        if (read_pending)
          $fatal(1, "external memory accepted an overlapping read");
        captured_read_addr <= EXTRAM_addr;
        // Cartridge instruction fetches use normal memory timing. The two
        // watched reads are delayed so their return arrives during pause.
        if (EXTRAM_addr == ROM_ADDRESS || EXTRAM_addr == SRAM_ADDRESS)
          read_delay <= 6'd14;
        else
          read_delay <= 6'd3;
        read_pending <= 1'b1;
      end
      if (EXTRAM_write && !prev_write_ram) begin
        if (write_pending)
          $fatal(1, "external memory accepted an overlapping write");
        captured_write_addr <= EXTRAM_addr;
        captured_write_be <= EXTRAM_be;
        captured_write_data <= EXTRAM_datawrite;
        write_delay <= 6'd9;
        write_pending <= 1'b1;
      end

      if (read_pending) begin
        if (read_delay != 0) begin
          read_delay <= read_delay - 1'b1;
        end else begin
          if (captured_read_addr[24] == 1'b0)
            EXTRAM_dataread <= cartridge_word(captured_read_addr);
          else if (captured_read_addr == SRAM_ADDRESS)
            EXTRAM_dataread <= sram_word;
          else
            $fatal(1, "delayed read used unexpected address %07x", captured_read_addr);
          read_pending <= 1'b0;
          if (captured_read_addr == ROM_ADDRESS ||
              captured_read_addr == SRAM_ADDRESS)
            memory_read_completions <= memory_read_completions + 1;
        end
      end

      if (write_pending) begin
        if (write_delay != 0) begin
          write_delay <= write_delay - 1'b1;
        end else begin
          if (captured_write_addr != SRAM_ADDRESS ||
              captured_write_be != 2'b11 ||
              captured_write_data != SRAM_WRITTEN)
            $fatal(1, "delayed SRAM write payload changed");
          sram_word <= captured_write_data;
          write_pending <= 1'b0;
          memory_write_commits <= memory_write_commits + 1;
        end
      end
    end
  end

  reg prev_read_sys = 1'b0;
  reg prev_write_sys = 1'b0;
  integer rom_read_episodes = 0;
  integer sram_read_episodes = 0;
  integer sram_write_episodes = 0;
  integer rom_marker_count = 0;
  integer sram_marker_count = 0;

  always @(posedge clk) begin
    if (reset_in) begin
      prev_read_sys <= 1'b0;
      prev_write_sys <= 1'b0;
      rom_read_episodes <= 0;
      sram_read_episodes <= 0;
      sram_write_episodes <= 0;
      rom_marker_count <= 0;
      sram_marker_count <= 0;
    end else begin
      if (EXTRAM_read && !prev_read_sys) begin
        if (EXTRAM_addr == ROM_ADDRESS)
          rom_read_episodes <= rom_read_episodes + 1;
        else if (EXTRAM_addr == SRAM_ADDRESS)
          sram_read_episodes <= sram_read_episodes + 1;
        else if (EXTRAM_addr[24] != 1'b0)
          $fatal(1, "unexpected external read address %07x", EXTRAM_addr);
      end
      if (EXTRAM_write && !prev_write_sys) begin
        if (EXTRAM_addr != SRAM_ADDRESS)
          $fatal(1, "unexpected external write address %07x", EXTRAM_addr);
        sram_write_episodes <= sram_write_episodes + 1;
      end
      prev_read_sys <= EXTRAM_read;
      prev_write_sys <= EXTRAM_write;

      if (debug_mem_valid && debug_mem_write && debug_mem_space == 4'd1) begin
        if (debug_mem_address == 20'h00100) begin
          if (debug_mem_byte_enable != 2'b11 || debug_mem_value != ROM_SENTINEL)
            $fatal(1, "ROM result IRAM marker mismatch be=%b value=%04x",
                   debug_mem_byte_enable, debug_mem_value);
          if (rom_marker_count != 0)
            $fatal(1, "ROM result IRAM marker replayed");
          rom_marker_count <= rom_marker_count + 1;
        end else if (debug_mem_address == 20'h00102) begin
          if (debug_mem_byte_enable != 2'b11 || debug_mem_value != SRAM_WRITTEN)
            $fatal(1, "SRAM result IRAM marker mismatch be=%b value=%04x",
                   debug_mem_byte_enable, debug_mem_value);
          if (sram_marker_count != 0)
            $fatal(1, "SRAM result IRAM marker replayed");
          sram_marker_count <= sram_marker_count + 1;
        end
      end
    end
  end

  integer index;
  integer refresh_count;
  integer phase_before;
  integer phase_after;
  integer timeout;
  integer resume_console_pulses;
  reg [14:0] held_pixel_addr;
  reg [11:0] held_pixel_data;
  reg [15:0] held_audio_l;
  reg [15:0] held_audio_r;

  task automatic pause_external_transaction(
      input bit expected_write,
      input [24:0] expected_address,
      input [1:0] expected_be,
      input [15:0] expected_write_data,
      input [15:0] expected_read_data,
      input integer result_marker,
      input string label_text
  );
    reg response_seen;
    begin
      timeout = 0;
      while (!((expected_write ? EXTRAM_write : EXTRAM_read) &&
               EXTRAM_addr == expected_address) && timeout < 12000) begin
        tick;
        timeout = timeout + 1;
      end
      if (!((expected_write ? EXTRAM_write : EXTRAM_read) &&
            EXTRAM_addr == expected_address))
        $fatal(1, "%s request did not arrive", label_text);
      if ((expected_write ? EXTRAM_read : EXTRAM_write) ||
          EXTRAM_addr != expected_address || EXTRAM_be != expected_be)
        $fatal(1, "%s request metadata mismatch read=%b write=%b addr=%07x be=%b",
               label_text, EXTRAM_read, EXTRAM_write, EXTRAM_addr, EXTRAM_be);
      if (expected_write && EXTRAM_datawrite != expected_write_data)
        $fatal(1, "%s write data mismatch %04x", label_text, EXTRAM_datawrite);

      // The request remains high from the clk_sys edge until this independently
      // phased assertion. Address, byte enable, and write data are validated
      // and captured only while that request is live; after the one permitted
      // falling edge, those combinational outputs are no longer a protocol.
      #251;
      if (!(expected_write ? EXTRAM_write : EXTRAM_read))
        $fatal(1, "%s request pulse ended before pause assertion", label_text);
      pause_in = 1'b1;
      tick;
      if (debug_console_ce || debug_cpu_ce || debug_memory_ce)
        $fatal(1, "%s pause edge left a console clock enable asserted", label_text);
      if (EXTRAM_read || EXTRAM_write)
        $fatal(1, "%s request pulse did not end exactly once", label_text);

      held_pixel_addr = pixel_out_addr;
      held_pixel_data = pixel_out_data;
      held_audio_l = audio_l;
      held_audio_r = audio_r;
      phase_before = rtc_state_data_out[159:128];
      refresh_count = 0;
      response_seen = expected_write;

      for (index = 0; index < 260; index = index + 1) begin
        tick;
        if (debug_console_ce || debug_cpu_ce || debug_memory_ce)
          $fatal(1, "%s console enable leaked at paused edge %0d", label_text, index);
        if (EXTRAM_read || EXTRAM_write)
          $fatal(1, "%s external request replayed while paused", label_text);
        if (!expected_write && EXTRAM_dataread == expected_read_data)
          response_seen = 1'b1;
        if (!expected_write && response_seen && EXTRAM_dataread != expected_read_data)
          $fatal(1, "%s returned data was not held while paused", label_text);
        if (pixel_out_we)
          $fatal(1, "%s GPU produced a pixel write while paused", label_text);
        if (pixel_out_addr !== held_pixel_addr || pixel_out_data !== held_pixel_data)
          $fatal(1, "%s frame producer state changed while paused", label_text);
        if (audio_l !== held_audio_l || audio_r !== held_audio_r)
          $fatal(1, "%s sound sample changed while paused", label_text);
        if (debug_refresh !== EXTRAM_doRefresh)
          $fatal(1, "%s refresh observability diverged", label_text);
        if (EXTRAM_doRefresh)
          refresh_count = refresh_count + 1;
      end
      phase_after = rtc_state_data_out[159:128];
      if (refresh_count < 2)
        $fatal(1, "%s SDRAM refresh stopped during pause; pulses=%0d",
               label_text, refresh_count);
      if (phase_after - phase_before < 255 || phase_after - phase_before > 265)
        $fatal(1, "%s RTC did not advance on raw clock: %0d -> %0d",
               label_text, phase_before, phase_after);
      if (!response_seen)
        $fatal(1, "%s delayed read response did not arrive during pause", label_text);
      if (expected_write &&
          (memory_write_commits != 1 || sram_word != SRAM_WRITTEN))
        $fatal(1, "%s did not commit exactly once", label_text);

      @(negedge clk);
      pause_in = 1'b0;
      for (index = 0; index < 3; index = index + 1) begin
        tick;
        if (debug_console_ce || debug_cpu_ce || debug_memory_ce)
          $fatal(1, "%s resume warmup leaked CE on edge %0d", label_text, index);
        if ((index == 0 && debug_resume_wait !== 2'd2) ||
            (index == 1 && debug_resume_wait !== 2'd1) ||
            (index == 2 && debug_resume_wait !== 2'd0))
          $fatal(1, "%s resume warmup mismatch edge=%0d wait=%0d",
                 label_text, index, debug_resume_wait);
        if (!expected_write && EXTRAM_dataread != expected_read_data)
          $fatal(1, "%s returned data was not held through resume", label_text);
      end

      // Read correctness is established by a later CPU write to IRAM, not by
      // the two-cycle debug memory observer (which can predate delayed data).
      if (result_marker != 0) begin
        timeout = 0;
        while (((result_marker == 1) ? rom_marker_count : sram_marker_count) == 0 &&
               timeout < 12000) begin
          tick;
          timeout = timeout + 1;
        end
        if (((result_marker == 1) ? rom_marker_count : sram_marker_count) != 1)
          $fatal(1, "%s result marker did not arrive exactly once", label_text);
      end
    end
  endtask

  task automatic final_idle_pause_contract;
    begin
      // Retain the original independent composition check: enter from Fast
      // Forward, clear it while the menu owns input, and observe exactly one
      // normal-rate console pulse after the three-cycle resume barrier.
      @(negedge clk);
      fastforward = 1'b1;
      repeat (24) tick;
      if (!debug_memory_ce)
        $fatal(1, "Fast Forward did not reach accelerated memory CE state");
      @(negedge clk);
      pause_in = 1'b1;
      tick;
      if (debug_console_ce || debug_cpu_ce || debug_memory_ce)
        $fatal(1, "idle pause edge left a console clock enable asserted");
      repeat (260) begin
        tick;
        if (debug_console_ce || debug_cpu_ce || debug_memory_ce)
          $fatal(1, "idle pause leaked a console clock enable");
        if (EXTRAM_read || EXTRAM_write)
          $fatal(1, "halted probe emitted an external request while paused");
      end
      @(negedge clk);
      fastforward = 1'b0;
      pause_in = 1'b0;
      for (index = 0; index < 3; index = index + 1) begin
        tick;
        if (debug_console_ce || debug_cpu_ce || debug_memory_ce)
          $fatal(1, "idle resume warmup leaked CE on edge %0d", index);
        if ((index == 0 && debug_resume_wait !== 2'd2) ||
            (index == 1 && debug_resume_wait !== 2'd1) ||
            (index == 2 && debug_resume_wait !== 2'd0))
          $fatal(1, "idle resume warmup mismatch edge=%0d wait=%0d",
                 index, debug_resume_wait);
      end
      resume_console_pulses = 0;
      for (index = 0; index < 12; index = index + 1) begin
        tick;
        if (debug_console_ce)
          resume_console_pulses = resume_console_pulses + 1;
      end
      if (resume_console_pulses != 1)
        $fatal(1, "idle resume duplicated/lost console pulses=%0d",
               resume_console_pulses);
    end
  endtask

  integer fastforward_case = 0;
  initial begin
    if (!$value$plusargs("fastforward=%d", fastforward_case))
      fastforward_case = 0;
    if (fastforward_case != 0 && fastforward_case != 1)
      $fatal(1, "fastforward case must be 0 or 1");

    repeat (12) tick;
    @(negedge clk);
    fastforward = fastforward_case[0];
    reset_in = 1'b0;

    pause_external_transaction(
        1'b0, ROM_ADDRESS, 2'b00, 16'd0, ROM_SENTINEL, 1, "ROM read");
    pause_external_transaction(
        1'b1, SRAM_ADDRESS, 2'b11, SRAM_WRITTEN, 16'd0, 0, "SRAM write");
    pause_external_transaction(
        1'b0, SRAM_ADDRESS, 2'b11, 16'd0, SRAM_WRITTEN, 2, "SRAM readback");

    repeat (48) tick;
    if (rom_read_episodes != 1 || sram_write_episodes != 1 ||
        sram_read_episodes != 1 || memory_read_completions != 2 ||
        memory_write_commits != 1 || rom_marker_count != 1 ||
        sram_marker_count != 1)
      $fatal(1,
             "transaction cardinality mismatch rom=%0d sw=%0d sr=%0d rc=%0d wc=%0d markers=%0d/%0d",
             rom_read_episodes, sram_write_episodes, sram_read_episodes,
             memory_read_completions, memory_write_commits,
             rom_marker_count, sram_marker_count);

    final_idle_pause_contract();

    $display(
        "PASS built-in Open IPL SwanTop pause external transactions exactly once mode=%s ram_phase_ps=%0d; console/DMA/GPU/audio gated, refresh+RTC continue, frame/sample hold, 3-cycle resume",
        (fastforward_case != 0) ? "fast-forward" : "normal",
        ram_phase_ps
    );
    $finish;
  end
endmodule
