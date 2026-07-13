`timescale 1ns / 1ps

module pocket_save_init_tb;

  reg clk = 1'b0;
  always #5 clk = ~clk;

  reg         cart_download = 1'b0;
  reg         load_complete = 1'b0;
  reg         reset_n = 1'b0;
  reg         save_payload_write = 1'b0;
  reg         save_is_sram = 1'b0;
  reg         save_is_eeprom = 1'b1;
  reg  [19:0] save_size_bytes = 20'd0;
  reg         sram_write_ack = 1'b0;

  wire        clearing;
  wire        clearing_sram;
  wire        clear_sram_write;
  wire        clear_eeprom_write;
  wire [19:0] clear_word_addr;
  wire        initialization_resolved;

  pocket_save_init dut (
      .clk(clk),
      .cart_download(cart_download),
      .load_complete(load_complete),
      .reset_n(reset_n),
      .save_payload_write(save_payload_write),
      .save_is_sram(save_is_sram),
      .save_is_eeprom(save_is_eeprom),
      .save_size_bytes(save_size_bytes),
      .sram_write_ack(sram_write_ack),
      .clearing(clearing),
      .clearing_sram(clearing_sram),
      .clear_sram_write(clear_sram_write),
      .clear_eeprom_write(clear_eeprom_write),
      .clear_word_addr(clear_word_addr),
      .initialization_resolved(initialization_resolved)
  );

  reg [15:0] eeprom_mem[0:1023];
  reg [15:0] initial_eeprom_mem[0:1023];
  reg [15:0] sram_mem[0:16384];
  reg [15:0] initial_sram_mem[0:16384];

  integer expected_words = 0;
  integer clear_write_count = 0;
  integer i;
  reg testing_eeprom = 1'b0;
  reg testing_sram = 1'b0;

  // Model the SDRAM request/acknowledgement handshake. One rising ACK commits
  // exactly one word, matching the controller contract used by the initializer.
  always @(posedge clk) begin
    if (testing_sram && clear_sram_write && !sram_write_ack)
      sram_write_ack <= 1'b1;
    else
      sram_write_ack <= 1'b0;
  end

  always @(posedge clk) begin
    if (clear_eeprom_write && clear_sram_write)
      $fatal(1, "both persistence clear paths asserted together");

    if (clear_eeprom_write) begin
      if (!testing_eeprom) $fatal(1, "unexpected EEPROM clear path");
      if (clear_word_addr >= expected_words[19:0])
        $fatal(1, "EEPROM clear exceeded selected capacity: addr=%0d words=%0d",
               clear_word_addr, expected_words);
      if (clear_word_addr != clear_write_count[19:0])
        $fatal(1, "EEPROM address skipped/repeated: got=%0d expected=%0d",
               clear_word_addr, clear_write_count);
      eeprom_mem[clear_word_addr[9:0]] <= 16'hffff;
      clear_write_count <= clear_write_count + 1;
    end

    if (testing_sram && clear_sram_write && sram_write_ack) begin
      if (clear_word_addr >= expected_words[19:0])
        $fatal(1, "SRAM clear exceeded selected capacity: addr=%0d words=%0d",
               clear_word_addr, expected_words);
      if (clear_word_addr != clear_write_count[19:0])
        $fatal(1, "SRAM address skipped/repeated: got=%0d expected=%0d",
               clear_word_addr, clear_write_count);
      sram_mem[clear_word_addr[14:0]] <= 16'h0000;
      clear_write_count <= clear_write_count + 1;
    end
  end

  task automatic tick;
    begin
      @(posedge clk);
      #1;
    end
  endtask

  task automatic arm_cartridge(
      input integer byte_count,
      input reg select_sram,
      input reg select_eeprom
  );
    begin
      load_complete = 1'b0;
      save_payload_write = 1'b0;
      save_size_bytes = byte_count[19:0];
      save_is_sram = select_sram;
      save_is_eeprom = select_eeprom;
      testing_sram = select_sram;
      testing_eeprom = select_eeprom;
      clear_write_count = 0;
      expected_words = byte_count / 2;
      cart_download = 1'b1;
      repeat (3) tick();
      if (initialization_resolved || clearing)
        $fatal(1, "new cartridge did not clear resolved/pending lifecycle state");
      cart_download = 1'b0;
      tick();
    end
  endtask

  task automatic pulse_load_complete;
    begin
      load_complete = 1'b1;
      tick();
      load_complete = 1'b0;
    end
  endtask

  task automatic wait_until_resolved;
    integer watchdog;
    begin
      watchdog = 0;
      while (!initialization_resolved) begin
        tick();
        watchdog = watchdog + 1;
        if (watchdog > 70000) $fatal(1, "save initialization did not resolve");
      end
      if (clearing) $fatal(1, "initializer resolved while clear remained active");
      tick();
    end
  endtask

  task automatic seed_eeprom;
    begin
      for (i = 0; i < 1024; i = i + 1) begin
        eeprom_mem[i] = 16'h4000 ^ i[15:0];
        initial_eeprom_mem[i] = 16'h4000 ^ i[15:0];
      end
    end
  endtask

  task automatic seed_sram;
    begin
      for (i = 0; i <= 16384; i = i + 1) begin
        sram_mem[i] = 16'h8000 ^ i[15:0];
        initial_sram_mem[i] = 16'h8000 ^ i[15:0];
      end
    end
  endtask

  task automatic prove_no_reclear(input integer byte_count);
    integer writes_before;
    begin
      writes_before = clear_write_count;

      // Duplicate/held load-complete indications are inert after resolution.
      load_complete = 1'b1;
      repeat (4) tick();
      load_complete = 1'b0;
      repeat (2) tick();
      if (!initialization_resolved || clearing || clear_write_count != writes_before)
        $fatal(1, "repeated load_complete re-armed %0d-byte save", byte_count);

      // Host reset is retained only for wrapper compatibility and must have no
      // effect on the per-title initialization lifecycle in either direction.
      reset_n = 1'b1;
      repeat (4) tick();
      reset_n = 1'b0;
      repeat (4) tick();
      reset_n = 1'b1;
      repeat (4) tick();
      if (!initialization_resolved || clearing || clear_write_count != writes_before)
        $fatal(1, "host Reset Enter/Exit re-armed %0d-byte save", byte_count);
    end
  endtask

  task automatic check_absent_eeprom(input integer byte_count);
    begin
      seed_eeprom();
      arm_cartridge(byte_count, 1'b0, 1'b1);
      repeat (5) tick();
      if (clearing || initialization_resolved)
        $fatal(1, "EEPROM started before load_complete");
      pulse_load_complete();
      if (!clearing || initialization_resolved)
        $fatal(1, "absent EEPROM did not enter unresolved clear state");
      wait_until_resolved();

      if (clear_write_count != expected_words)
        $fatal(1, "wrong clear count for %0d-byte EEPROM: got=%0d expected=%0d",
               byte_count, clear_write_count, expected_words);
      for (i = 0; i < 1024; i = i + 1) begin
        if (i < expected_words) begin
          if (eeprom_mem[i] !== 16'hffff)
            $fatal(1, "EEPROM word %0d was not initialized to 0xFFFF", i);
        end else if (eeprom_mem[i] !== initial_eeprom_mem[i]) begin
          $fatal(1, "EEPROM word %0d outside selected capacity changed", i);
        end
      end

      eeprom_mem[0] = 16'ha55a;
      prove_no_reclear(byte_count);
      if (eeprom_mem[0] !== 16'ha55a)
        $fatal(1, "runtime EEPROM data was erased after resolution");
    end
  endtask

  task automatic check_loaded_eeprom(input integer byte_count);
    integer last_word;
    begin
      seed_eeprom();
      arm_cartridge(byte_count, 1'b0, 1'b1);
      last_word = expected_words - 1;
      eeprom_mem[0] = 16'h1357;
      eeprom_mem[last_word] = 16'h2468;
      save_payload_write = 1'b1;
      tick();
      save_payload_write = 1'b0;
      pulse_load_complete();

      if (!initialization_resolved || clearing || clear_write_count != 0)
        $fatal(1, "loaded %0d-byte EEPROM did not resolve without clearing", byte_count);
      if (eeprom_mem[0] !== 16'h1357 || eeprom_mem[last_word] !== 16'h2468)
        $fatal(1, "loaded %0d-byte EEPROM sentinels changed", byte_count);
      prove_no_reclear(byte_count);
    end
  endtask

  task automatic check_absent_sram;
    begin
      seed_sram();
      // Exercise the smallest supported SRAM capacity: 32 KiB / 16K words.
      arm_cartridge(32768, 1'b1, 1'b0);
      pulse_load_complete();
      if (!clearing_sram || initialization_resolved)
        $fatal(1, "absent SRAM did not enter unresolved handshake clear");
      wait_until_resolved();
      if (clear_write_count != 16384)
        $fatal(1, "32 KiB SRAM clear count=%0d expected=16384", clear_write_count);
      for (i = 0; i < 16384; i = i + 1) begin
        if (sram_mem[i] !== 16'h0000)
          $fatal(1, "SRAM word %0d was not initialized to zero", i);
      end
      if (sram_mem[16384] !== initial_sram_mem[16384])
        $fatal(1, "SRAM word immediately outside selected capacity changed");
      sram_mem[0] = 16'h5aa5;
      prove_no_reclear(32768);
      if (sram_mem[0] !== 16'h5aa5)
        $fatal(1, "runtime SRAM data was erased after resolution");
    end
  endtask

  initial begin
    // Exact external EEPROM capacities for header types 10, 20, and 50.
    check_absent_eeprom(128);
    check_absent_eeprom(2048);
    check_absent_eeprom(1024);

    check_loaded_eeprom(128);
    check_loaded_eeprom(2048);
    check_loaded_eeprom(1024);

    check_absent_sram();

    // A payload write coincident with load_complete must resolve as loaded.
    seed_eeprom();
    arm_cartridge(128, 1'b0, 1'b1);
    save_payload_write = 1'b1;
    load_complete = 1'b1;
    tick();
    save_payload_write = 1'b0;
    load_complete = 1'b0;
    if (!initialization_resolved || clearing || clear_write_count != 0)
      $fatal(1, "coincident payload/load_complete was treated as absent");

    // Titles without persistent memory still resolve at the official boundary.
    arm_cartridge(0, 1'b0, 1'b0);
    pulse_load_complete();
    if (!initialization_resolved || clearing || clear_write_count != 0)
      $fatal(1, "nonpersistent title did not resolve without clearing");

    $display("PASS pre-run save initialization, exact capacities, and persistent resolution");
    $finish;
  end

endmodule
