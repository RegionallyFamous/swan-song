`timescale 1ns/1ps

module apf_fast_forward_control_tb;
  reg clk = 1'b0;
  always #5 clk = ~clk;

  reg reset_n = 1'b0;
  reg clear_state = 1'b0;
  reg button_select = 1'b0;
  wire fast_forward;
  integer errors = 0;

  apf_fast_forward_control #(
      .HOLD_CYCLES(8)
  ) dut (
      .clk(clk),
      .reset_n(reset_n),
      .clear_state(clear_state),
      .button_select(button_select),
      .fast_forward(fast_forward)
  );

  task automatic fail(input string message);
    begin
      $display("FAIL: %s", message);
      errors = errors + 1;
    end
  endtask

  task automatic drive_select(input bit value, input integer cycles);
    begin
      @(negedge clk);
      button_select = value;
      repeat (cycles) @(posedge clk);
      #1;
    end
  endtask

  task automatic expect_fast(input bit expected, input string message);
    begin
      #1;
      if (fast_forward !== expected)
        fail(message);
    end
  endtask

  initial begin
    repeat (3) @(posedge clk);
    expect_fast(1'b0, "reset exposed Fast Forward");
    @(negedge clk);
    reset_n = 1'b1;

    // A short tap latches Fast Forward; the next short tap cancels it.
    drive_select(1'b1, 2);
    expect_fast(1'b1, "short press did not run Fast Forward while held");
    drive_select(1'b0, 1);
    expect_fast(1'b1, "short tap did not latch Fast Forward");
    drive_select(1'b1, 2);
    drive_select(1'b0, 1);
    expect_fast(1'b0, "second short tap did not cancel the latch");

    // A long hold is momentary and must not latch on release.
    drive_select(1'b1, 10);
    expect_fast(1'b1, "long hold did not enable Fast Forward");
    drive_select(1'b0, 1);
    expect_fast(1'b0, "long hold latched after release");

    // Focus/reset/title clear is represented by clear_state.  It erases the
    // latch, edge history, counter, and held state.  The upstream ownership
    // guard keeps it asserted until a valid neutral PAD packet has arrived.
    drive_select(1'b1, 2);
    drive_select(1'b0, 1);
    expect_fast(1'b1, "precondition tap did not latch");
    @(negedge clk);
    button_select = 1'b1;
    clear_state = 1'b1;
    repeat (3) @(posedge clk);
    expect_fast(1'b0, "clear did not dominate held Select and a prior latch");
    @(negedge clk);
    button_select = 1'b0;
    repeat (2) @(posedge clk);
    @(negedge clk);
    clear_state = 1'b0;
    repeat (2) @(posedge clk);
    expect_fast(1'b0, "Fast Forward reappeared after neutral rearm");

    // Host reset independently clears every state element.
    drive_select(1'b1, 2);
    drive_select(1'b0, 1);
    expect_fast(1'b1, "second precondition tap did not latch");
    @(negedge clk);
    reset_n = 1'b0;
    repeat (2) @(posedge clk);
    expect_fast(1'b0, "host reset did not clear Fast Forward");
    @(negedge clk);
    reset_n = 1'b1;
    repeat (2) @(posedge clk);
    expect_fast(1'b0, "Fast Forward state survived host reset");

    if (errors != 0)
      $fatal(1, "Fast Forward control failed with %0d errors", errors);

    $display("PASS Fast Forward tap, hold, focus/reset/title clear, and neutral rearm contract");
    $finish;
  end
endmodule
