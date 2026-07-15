`timescale 1ns/1ps

module apf_console_setup_tb;
  localparam integer RESET_CYCLES = 4;
  localparam integer START_CYCLES = 12;

  reg clk_source = 1'b0;
  reg clk_destination = 1'b0;
  reg reset_n = 1'b0;
  reg trigger = 1'b0;
  reg menu_focus_source = 1'b0;

  wire reset_active_destination;
  wire start_active_destination;

  always #5ns clk_source = ~clk_source;
  always #7ns clk_destination = ~clk_destination;

  apf_console_setup #(
      .RESET_CYCLES(RESET_CYCLES),
      .START_CYCLES(START_CYCLES)
  ) dut (
      .clk_source(clk_source),
      .clk_destination(clk_destination),
      .reset_n(reset_n),
      .trigger(trigger),
      .menu_focus_source(menu_focus_source),
      .reset_active_destination(reset_active_destination),
      .start_active_destination(start_active_destination)
  );

  task automatic pulse_trigger;
    begin
      @(negedge clk_source);
      trigger = 1'b1;
      @(posedge clk_source);
      #1ps;
      trigger = 1'b0;
      if (!dut.reset_active_source || !dut.start_active_source)
        $fatal(1, "trigger did not load both source-domain intervals");
    end
  endtask

  task automatic wait_destination_pair_high;
    integer edges;
    begin
      edges = 0;
      while ((!reset_active_destination || !start_active_destination) && edges < 8) begin
        @(posedge clk_destination);
        #1ps;
        edges = edges + 1;
      end
      if (!reset_active_destination || !start_active_destination)
        $fatal(1, "reset/Start levels did not cross to the destination");
    end
  endtask

  task automatic wait_destination_reset_low;
    integer edges;
    begin
      edges = 0;
      while (reset_active_destination && edges < 12) begin
        @(posedge clk_destination);
        #1ps;
        edges = edges + 1;
      end
      if (reset_active_destination)
        $fatal(1, "setup reset did not release");
      if (!start_active_destination)
        $fatal(1, "forced Start did not remain held after setup reset release");
    end
  endtask

  initial begin
    #2ns;
    reset_n = 1'b1;
    repeat (3) @(posedge clk_destination);
    #1ps;
    if (reset_active_destination || start_active_destination)
      $fatal(1, "idle sequencer exposed a setup level");

    // The action is selected while PocketOS still owns focus. The complete
    // gesture must remain armed indefinitely rather than expiring behind the
    // menu pause; both exact intervals begin only when focus returns.
    menu_focus_source = 1'b1;
    pulse_trigger();
    wait_destination_pair_high();
    repeat (START_CYCLES + 4) begin
      @(posedge clk_source);
      #1ps;
      if (dut.reset_counter_source !== RESET_CYCLES ||
          dut.start_counter_source !== START_CYCLES)
        $fatal(1, "Console Setup countdown advanced while menu owned focus");
    end
    @(negedge clk_source);
    menu_focus_source = 1'b0;

    // After focus release the source intervals are exact and reset releases
    // first, leaving a bounded held-Start window for the original BIOS.
    repeat (RESET_CYCLES - 1) begin
      @(posedge clk_source);
      #1ps;
      if (!dut.reset_active_source)
        $fatal(1, "source reset released before RESET_CYCLES elapsed");
    end
    @(posedge clk_source);
    #1ps;
    if (dut.reset_active_source || !dut.start_active_source)
      $fatal(1, "source intervals did not release reset before Start");
    if (!reset_active_destination || !start_active_destination)
      $fatal(1, "destination did not observe the reset/Start overlap");
    wait_destination_reset_low();

    // Retrigger while only Start remains active. Reset must reassert and both
    // countdowns must restart without a low glitch on forced Start.
    pulse_trigger();
    if (!start_active_destination)
      $fatal(1, "retrigger glitched forced Start low");
    wait_destination_pair_high();
    repeat (2) @(posedge clk_source);
    pulse_trigger();
    repeat (RESET_CYCLES - 1) begin
      @(posedge clk_source);
      #1ps;
      if (!dut.reset_active_source || !dut.start_active_source)
        $fatal(1, "retrigger did not extend both source intervals");
    end

    // Host Reset Enter is the highest-priority cancellation. Assertion clears
    // both clock domains immediately, and a trigger held during reset cannot
    // leave a deferred setup request behind.
    #1ns;
    reset_n = 1'b0;
    #1ps;
    if (reset_active_destination || start_active_destination ||
        dut.reset_active_source || dut.start_active_source)
      $fatal(1, "host reset did not immediately cancel Console Setup");
    trigger = 1'b1;
    repeat (2) @(posedge clk_source);
    #1ps;
    if (dut.reset_active_source || dut.start_active_source)
      $fatal(1, "trigger was accepted while host reset was active");
    trigger = 1'b0;
    menu_focus_source = 1'b1;
    reset_n = 1'b1;
    repeat (5) @(posedge clk_destination);
    #1ps;
    if (reset_active_destination || start_active_destination)
      $fatal(1, "cancelled Console Setup reappeared after Reset Exit");
    menu_focus_source = 1'b0;

    $display(
        "PASS APF Console Setup menu-hold reset_cycles=%0d start_cycles=%0d CDC=3-stage retrigger/cancel",
        RESET_CYCLES,
        START_CYCLES
    );
    $finish;
  end
endmodule
