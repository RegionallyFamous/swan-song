`timescale 1ns/1ps

module pocket_console_eeprom_init_tb;
  reg clk = 1'b0;
  always #5 clk = ~clk;

  reg cart_download = 1'b0;
  wire clearing;
  wire write_en;
  wire [10:0] physical_word_addr;
  wire [15:0] write_data;
  wire initialization_resolved;

  reg [15:0] backing [0:2047];
  integer writes = 0;
  integer errors = 0;
  integer i;

  pocket_console_eeprom_init dut (
      .clk(clk),
      .cart_download(cart_download),
      .clearing(clearing),
      .write_en(write_en),
      .physical_word_addr(physical_word_addr),
      .write_data(write_data),
      .initialization_resolved(initialization_resolved)
  );

  task automatic fail(input string message);
    begin
      $display("FAIL: %s", message);
      errors = errors + 1;
    end
  endtask

  task automatic tick;
    begin
      @(posedge clk);
      #1;
    end
  endtask

  always @(posedge clk) begin
    if (write_en) begin
      if (physical_word_addr > 11'd1087)
        fail("factory writer escaped the two defined banks");
      backing[physical_word_addr] <= write_data;
      writes = writes + 1;
    end
  end

  initial begin
    for (i = 0; i < 2048; i = i + 1)
      backing[i] = 16'hA500 ^ i[15:0];

    // Cold start creates both complete images and leaves unused bank-1 words
    // untouched.
    while (!initialization_resolved) tick();
    tick();
    if (clearing || write_en) fail("resolved initializer remained active");
    if (writes != 1088) fail($sformatf("cold write count=%0d expected=1088", writes));
    if (backing[11'h030] !== 16'h1921 || backing[11'h041] !== 16'h0327)
      fail("Color factory image mismatch");
    if (backing[11'h430] !== 16'h1921 || backing[11'h43c] !== 16'h0024)
      fail("mono factory image mismatch");
    if (backing[11'h43f] !== 16'h0000 || backing[11'h440] !== 16'hA140)
      fail("mono boundary or unused backing changed");

    // Runtime modifications survive indefinitely because ordinary reset is
    // intentionally not an initializer input.
    backing[11'h000] = 16'h1357;
    backing[11'h400] = 16'h2468;
    repeat (20) tick();
    if (backing[11'h000] !== 16'h1357 || backing[11'h400] !== 16'h2468)
      fail("runtime data changed without a title-load event");

    // A new title re-arms exactly one seed pass. Holding cart_download must
    // suppress writes so an APF transfer cannot overlap a partial factory pass.
    writes = 0;
    cart_download = 1'b1;
    repeat (7) tick();
    if (!clearing || initialization_resolved || write_en || writes != 0)
      fail("held title load did not cleanly re-arm the initializer");
    cart_download = 1'b0;
    while (!initialization_resolved) tick();
    tick();
    if (writes != 1088) fail($sformatf("reload write count=%0d expected=1088", writes));
    if (backing[11'h000] !== 16'h0000 || backing[11'h400] !== 16'h0000)
      fail("title-load seed did not restore both banks before APF load");

    // Re-arm during a partial pass restarts from word zero and still resolves
    // to one complete deterministic image.
    cart_download = 1'b1;
    tick();
    cart_download = 1'b0;
    repeat (13) tick();
    cart_download = 1'b1;
    repeat (3) tick();
    if (physical_word_addr !== 11'd0 || write_en)
      fail("mid-pass title load did not restart/suppress writes");
    cart_download = 1'b0;
    while (!initialization_resolved) tick();

    if (errors != 0) $fatal(1, "console EEPROM initializer errors=%0d", errors);
    $display("PASS dual-bank console EEPROM factory initialization and lifecycle");
    $finish;
  end
endmodule
