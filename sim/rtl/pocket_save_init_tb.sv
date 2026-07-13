`timescale 1ns / 1ps

module pocket_save_init_tb;

  reg clk = 1'b0;
  always #5 clk = ~clk;

  reg         cart_download = 1'b0;
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

  pocket_save_init dut (
      .clk(clk),
      .cart_download(cart_download),
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
      .clear_word_addr(clear_word_addr)
  );

  reg [15:0] eeprom_mem[0:1023];
  reg [15:0] initial_mem[0:1023];
  integer expected_words = 0;
  integer clear_write_count = 0;
  integer i;

  always @(posedge clk) begin
    if (clear_eeprom_write) begin
      if (clear_word_addr >= expected_words[19:0]) begin
        $fatal(1, "EEPROM clear exceeded selected capacity: addr=%0d words=%0d",
               clear_word_addr, expected_words);
      end
      if (clear_word_addr != clear_write_count[19:0]) begin
        $fatal(1, "EEPROM clear address skipped/repeated: got=%0d expected=%0d",
               clear_word_addr, clear_write_count);
      end
      eeprom_mem[clear_word_addr[9:0]] <= 16'hffff;
      clear_write_count <= clear_write_count + 1;
    end

    if (clear_sram_write || clearing_sram) begin
      $fatal(1, "EEPROM test unexpectedly selected the SRAM clear path");
    end
  end

  task automatic tick;
    begin
      @(posedge clk);
      #1;
    end
  endtask

  task automatic arm_cartridge(input integer byte_count);
    begin
      reset_n = 1'b0;
      save_size_bytes = byte_count[19:0];
      save_is_sram = 1'b0;
      save_is_eeprom = 1'b1;
      save_payload_write = 1'b0;
      clear_write_count = 0;
      expected_words = byte_count / 2;
      cart_download = 1'b1;
      repeat (3) tick();
      cart_download = 1'b0;
      tick();
    end
  endtask

  task automatic seed_memory;
    begin
      for (i = 0; i < 1024; i = i + 1) begin
        eeprom_mem[i] = 16'h4000 ^ i[15:0];
        initial_mem[i] = 16'h4000 ^ i[15:0];
      end
    end
  endtask

  task automatic wait_for_clear;
    integer watchdog;
    begin
      reset_n = 1'b1;
      tick();
      watchdog = 0;
      while (clearing) begin
        tick();
        watchdog = watchdog + 1;
        if (watchdog > 1100) $fatal(1, "EEPROM initialization did not finish");
      end
      tick();
    end
  endtask

  task automatic check_absent_save(input integer byte_count);
    integer writes_before_reset;
    begin
      seed_memory();
      arm_cartridge(byte_count);
      wait_for_clear();

      if (clear_write_count != expected_words) begin
        $fatal(1, "wrong clear count for %0d-byte EEPROM: got=%0d expected=%0d",
               byte_count, clear_write_count, expected_words);
      end
      for (i = 0; i < 1024; i = i + 1) begin
        if (i < expected_words) begin
          if (eeprom_mem[i] !== 16'hffff)
            $fatal(1, "word %0d was not initialized to native EEPROM blank value", i);
        end else if (eeprom_mem[i] !== initial_mem[i]) begin
          $fatal(1, "word %0d outside the selected EEPROM capacity was modified", i);
        end
      end

      // Model a game write, then APF Reset Enter for quit/unload and a later
      // Reset Exit.  Neither lifecycle edge may re-arm fresh-save clearing.
      eeprom_mem[0] = 16'ha55a;
      writes_before_reset = clear_write_count;
      reset_n = 1'b0;
      repeat (5) tick();
      if (clear_write_count != writes_before_reset || eeprom_mem[0] !== 16'ha55a)
        $fatal(1, "Reset Enter erased runtime EEPROM data for %0d-byte save", byte_count);
      reset_n = 1'b1;
      repeat (5) tick();
      if (clearing || clear_write_count != writes_before_reset || eeprom_mem[0] !== 16'ha55a)
        $fatal(1, "later Reset Exit re-cleared runtime EEPROM data for %0d-byte save", byte_count);
    end
  endtask

  task automatic check_loaded_save(input integer byte_count);
    integer last_word;
    begin
      seed_memory();
      arm_cartridge(byte_count);
      last_word = expected_words - 1;

      // Model the APF payload load and retain sentinels at both capacity edges.
      eeprom_mem[0] = 16'h1357;
      eeprom_mem[last_word] = 16'h2468;
      save_payload_write = 1'b1;
      tick();
      save_payload_write = 1'b0;
      wait_for_clear();

      if (clearing || clear_write_count != 0)
        $fatal(1, "loaded %0d-byte EEPROM was treated as absent", byte_count);
      if (eeprom_mem[0] !== 16'h1357 || eeprom_mem[last_word] !== 16'h2468)
        $fatal(1, "loaded %0d-byte EEPROM sentinels were not preserved", byte_count);

      // The subsequent shutdown/unload window must expose the loaded/runtime
      // contents without an initializer write racing it.
      reset_n = 1'b0;
      repeat (5) tick();
      if (clear_write_count != 0 || eeprom_mem[0] !== 16'h1357 ||
          eeprom_mem[last_word] !== 16'h2468)
        $fatal(1, "shutdown altered loaded %0d-byte EEPROM", byte_count);
      reset_n = 1'b1;
      repeat (5) tick();
      if (clearing || clear_write_count != 0)
        $fatal(1, "loaded EEPROM was re-cleared after shutdown");
    end
  endtask

  initial begin
    // Header RAM types 10, 20, and 50 respectively.
    check_absent_save(128);
    check_absent_save(2048);
    check_absent_save(1024);

    check_loaded_save(128);
    check_loaded_save(2048);
    check_loaded_save(1024);

    $display("PASS external EEPROM exact absent-save initialization and loaded-save lifecycle");
    $finish;
  end

endmodule
