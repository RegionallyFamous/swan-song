`timescale 1ns/1ps

module apf_rom_loader_adapter_tb;
  localparam integer RAW_SIZE = 896 * 1024;
  localparam integer APERTURE_SIZE = 1024 * 1024;
  localparam integer PREFIX_SIZE = APERTURE_SIZE - RAW_SIZE;

  reg clk = 1'b0;
  always #5 clk = ~clk;

  reg reset_n = 1'b0;
  reg plan_valid = 1'b0;
  reg [24:0] raw_size = 25'd0;
  reg cart_download = 1'b0;
  reg raw_write_en = 1'b0;
  reg [24:0] raw_write_addr = 25'd0;
  reg [15:0] raw_write_data = 16'd0;
  wire raw_write_complete;
  wire adapter_sdram_req;
  wire adapter_sdram_rnw;
  wire [24:0] adapter_sdram_byte_addr;
  wire [15:0] adapter_sdram_write_data;
  wire adapter_sdram_ready;
  wire sdram_req;
  wire sdram_rnw;
  wire [24:0] sdram_word_addr;
  wire [15:0] sdram_write_data;
  reg sdram_ready = 1'b0;
  wire plan_non_power_of_two;
  wire [23:0] mapped_mask;
  wire prepare_busy;
  wire image_ready;
  wire validation_failed;

  reg [7:0] rom [0:RAW_SIZE-1];
  reg [15:0] memory [0:(APERTURE_SIZE/2)-1];
  reg previous_sdram_req = 1'b0;
  integer errors = 0;
  integer address;
  integer timeout;
  string rom_path;

  apf_rom_loader_adapter dut (
      .clk(clk),
      .reset_n(reset_n),
      .plan_valid(plan_valid),
      .raw_size(raw_size),
      .cart_download(cart_download),
      .raw_write_en(raw_write_en),
      .raw_write_addr(raw_write_addr),
      .raw_write_data(raw_write_data),
      .raw_write_complete(raw_write_complete),
      .sdram_req(adapter_sdram_req),
      .sdram_rnw(adapter_sdram_rnw),
      .sdram_byte_addr(adapter_sdram_byte_addr),
      .sdram_write_data(adapter_sdram_write_data),
      .sdram_ready(adapter_sdram_ready),
      .plan_non_power_of_two(plan_non_power_of_two),
      .mapped_mask(mapped_mask),
      .prepare_busy(prepare_busy),
      .image_ready(image_ready),
      .validation_failed(validation_failed)
  );

  // Exercise the production path, not just the adapter in isolation.  The
  // future staging owner remains tied off exactly as it is in wonderswan.sv.
  apf_sdram_channel1_mux channel1_owner (
      .clk(clk),
      .reset_n(reset_n),
      .stage_acquire(1'b0),
      .runtime_quiesced(1'b0),
      .stage_granted(),
      .protocol_error(),
      .rom_req(adapter_sdram_req),
      .rom_rnw(adapter_sdram_rnw),
      .rom_addr({1'b0, adapter_sdram_byte_addr[24:1]}),
      .rom_write_data(adapter_sdram_write_data),
      .rom_ready(adapter_sdram_ready),
      .rom_read_data(),
      .stage_req(1'b0),
      .stage_rnw(1'b1),
      .stage_addr(25'd0),
      .stage_write_data(16'd0),
      .stage_ready(),
      .stage_read_data(),
      .sdram_req(sdram_req),
      .sdram_rnw(sdram_rnw),
      .sdram_addr(sdram_word_addr),
      .sdram_write_data(sdram_write_data),
      .sdram_ready(sdram_ready),
      .sdram_read_data(16'd0)
  );

  task automatic fail(input string message);
    begin
      $display("FAIL: %s", message);
      errors = errors + 1;
    end
  endtask

  task automatic publish_plan(input [24:0] size);
    begin
      @(negedge clk);
      raw_size = size;
      plan_valid = 1'b1;
      @(negedge clk);
      plan_valid = 1'b0;
    end
  endtask

  task automatic write_word(input [24:0] byte_address, input [15:0] data);
    begin
      @(negedge clk);
      raw_write_addr = byte_address;
      raw_write_data = data;
      raw_write_en = 1'b1;
      timeout = 0;
      while (!raw_write_complete && timeout < 100) begin
        @(negedge clk);
        timeout = timeout + 1;
      end
      if (!raw_write_complete)
        fail($sformatf("raw write timed out at %0h", byte_address));
      raw_write_en = 1'b0;
    end
  endtask

  // Minimal edge-triggered model of the production SDRAM channel.
  always @(posedge clk) begin
    sdram_ready <= 1'b0;
    previous_sdram_req <= sdram_req;
    if (sdram_req && !previous_sdram_req) begin
      if (sdram_rnw) begin
        fail("ROM loader issued an unexpected SDRAM read");
      end else if (sdram_word_addr >= APERTURE_SIZE / 2) begin
        fail($sformatf("SDRAM address escaped aperture: %0h", sdram_word_addr));
      end else begin
        memory[sdram_word_addr] <= sdram_write_data;
        sdram_ready <= 1'b1;
      end
    end
  end

  initial begin
    if (!$value$plusargs("ROM=%s", rom_path)) begin
      $display("FAIL: missing +ROM fixture path");
      $fatal(1);
    end
    $readmemh(rom_path, rom);
    for (address = 0; address < APERTURE_SIZE / 2; address = address + 1)
      memory[address] = 16'h0000;

    repeat (3) @(negedge clk);
    reset_n = 1'b1;

    // The legacy path remains direct: no address offset, prefix request, or
    // post-load validation is inserted for a power-of-two plan.
    cart_download = 1'b1;
    publish_plan(25'h0020000);
    write_word(25'h0001234, 16'h5aa5);
    if (plan_non_power_of_two || prepare_busy)
      fail("power-of-two plan entered compact-ROM path");
    if (memory[25'h0001234 >> 1] != 16'h5aa5)
      fail("power-of-two path changed the direct SDRAM address/data");
    cart_download = 1'b0;
    repeat (4) @(negedge clk);

    // Adversarial target phase: LOADF raises download and holds its first word
    // before the accepted-size CDC pulse arrives.  The adapter must stall it,
    // never exposing the previous direct plan or writing address zero.
    @(posedge clk);
    #1;
    cart_download = 1'b1;
    raw_write_addr = 25'd0;
    raw_write_data = {rom[1], rom[0]};
    raw_write_en = 1'b1;
    repeat (4) begin
      @(negedge clk);
      if (raw_write_complete || sdram_req)
        fail("first LOADF word escaped before its per-load plan arrived");
    end
    publish_plan(RAW_SIZE);
    timeout = 0;
    while (!raw_write_complete && timeout < 100) begin
      @(negedge clk);
      timeout = timeout + 1;
    end
    if (!raw_write_complete)
      fail("held first compact-ROM word did not resume after plan arrival");
    raw_write_en = 1'b0;
    if (memory[0] !== 16'h0000)
      fail("held first compact-ROM word was written at unshifted address zero");

    // Real target case: right-align 896 KiB in a 1 MiB aperture while raw APF
    // words and prefix fill compete for the same single SDRAM channel.
    if (!plan_non_power_of_two || mapped_mask != 24'h0fffff)
      fail("896 KiB plan did not publish the 1 MiB mapper mask");
    // Hold the raw stream continuously from the second word through EOF. The
    // adapter must interleave one prefix write after each raw completion,
    // rather than relying on an idle gap that APF does not promise.
    @(negedge clk);
    raw_write_en = 1'b1;
    for (address = 2; address < RAW_SIZE; address = address + 2) begin
      raw_write_addr = address;
      raw_write_data = {rom[address + 1], rom[address]};
      timeout = 0;
      while (raw_write_complete && timeout < 100) begin
        @(negedge clk);
        timeout = timeout + 1;
      end
      while (!raw_write_complete && timeout < 100) begin
        @(negedge clk);
        timeout = timeout + 1;
      end
      if (!raw_write_complete)
        fail($sformatf("continuous raw write timed out at %0h", address));
    end
    raw_write_en = 1'b0;
    if (dut.fill_active)
      fail("prefix fill did not finish before continuous raw EOF");
    for (address = 0; address < PREFIX_SIZE; address = address + 2) begin
      if (memory[address >> 1] != 16'hffff) begin
        fail($sformatf("pre-EOF prefix word %0h was not erased-fill", address));
        address = PREFIX_SIZE;
      end
    end
    cart_download = 1'b0;
    #1;
    if (!prepare_busy)
      fail("compact reset hold glitched low before valid-edge validation");

    timeout = 0;
    while (!image_ready && timeout < 2000000) begin
      @(negedge clk);
      timeout = timeout + 1;
    end
    if (!image_ready)
      fail("valid 896 KiB image never became ready");
    if (prepare_busy || validation_failed)
      fail("valid 896 KiB image remained busy or failed validation");

    for (address = 0; address < PREFIX_SIZE; address = address + 2) begin
      if (memory[address >> 1] != 16'hffff) begin
        fail($sformatf("prefix word %0h was not erased-fill", address));
        address = PREFIX_SIZE;
      end
    end
    for (address = 0; address < RAW_SIZE; address = address + 2) begin
      if (memory[(PREFIX_SIZE + address) >> 1] !==
          {rom[address + 1], rom[address]}) begin
        fail($sformatf("right-aligned ROM word mismatch at raw %0h", address));
        address = RAW_SIZE;
      end
    end
    if (memory[(APERTURE_SIZE - 16) >> 1][7:0] != 8'hea)
      fail("footer entry was not mapped into the final aperture bytes");

    // The generated fixture deliberately sets legal upper maintenance flags.
    // Mutating only the reserved low nibble and restamping the checksum must
    // fail the RTL footer contract while retaining the safe reset hold.
    @(posedge clk);
    #1;
    cart_download = 1'b1;
    raw_write_addr = 25'd0;
    raw_write_data = {rom[1], rom[0]};
    raw_write_en = 1'b1;
    repeat (2) begin
      @(negedge clk);
      if (raw_write_complete || sdram_req)
        fail("preceding compact plan leaked into the next held first word");
    end
    publish_plan(RAW_SIZE);
    timeout = 0;
    while (!raw_write_complete && timeout < 100) begin
      @(negedge clk);
      timeout = timeout + 1;
    end
    if (!raw_write_complete)
      fail("second held first word did not resume after plan arrival");
    raw_write_en = 1'b0;
    for (address = 2; address < RAW_SIZE; address = address + 2) begin
      if (address == RAW_SIZE - 12)
        write_word(address, {8'ha1, rom[address]});
      else if (address == RAW_SIZE - 2)
        write_word(address, {rom[address + 1], rom[address]} + 16'd1);
      else
        write_word(address, {rom[address + 1], rom[address]});
    end
    if (dut.fill_active)
      fail("prefix fill remained active at invalid compact EOF");
    cart_download = 1'b0;
    #1;
    if (!prepare_busy)
      fail("compact reset hold glitched low before invalid-edge validation");
    repeat (8) @(negedge clk);
    if (!validation_failed || !prepare_busy || image_ready)
      fail("reserved maintenance low-nibble mutation was not held in reset");

    // A rejected compact image leaves a sticky failure and reset hold, but a
    // subsequent full title load must re-arm the adapter and recover. Repeat
    // the adversarial first-word-before-plan ordering, then load the original
    // valid image to prove both the failure clear and terminal ready path.
    @(posedge clk);
    #1;
    cart_download = 1'b1;
    raw_write_addr = 25'd0;
    raw_write_data = {rom[1], rom[0]};
    raw_write_en = 1'b1;
    repeat (2) begin
      @(negedge clk);
      if (raw_write_complete || sdram_req)
        fail("failed compact plan leaked into recovery's held first word");
    end
    publish_plan(RAW_SIZE);
    timeout = 0;
    while (!raw_write_complete && timeout < 100) begin
      @(negedge clk);
      timeout = timeout + 1;
    end
    if (!raw_write_complete)
      fail("recovery held first word did not resume after plan arrival");
    raw_write_en = 1'b0;
    if (validation_failed)
      fail("new compact plan did not clear the preceding validation failure");
    for (address = 2; address < RAW_SIZE; address = address + 2)
      write_word(address, {rom[address + 1], rom[address]});
    if (dut.fill_active)
      fail("prefix fill remained active at recovery compact EOF");
    cart_download = 1'b0;
    #1;
    if (!prepare_busy)
      fail("compact reset hold glitched low before recovery validation");

    timeout = 0;
    while (!image_ready && timeout < 2000000) begin
      @(negedge clk);
      timeout = timeout + 1;
    end
    if (!image_ready || validation_failed || prepare_busy)
      fail("valid compact reload did not recover after validation failure");
    if (memory[(APERTURE_SIZE - 16) >> 1][7:0] != 8'hea)
      fail("recovered image did not restore the mapped footer");

    if (errors != 0) begin
      $display("FAIL apf_rom_loader_adapter_tb errors=%0d", errors);
      $fatal(1);
    end
    $display("PASS APF 896 KiB load, validation failure recovery, and direct bypass");
    $finish;
  end
endmodule
