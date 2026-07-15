`timescale 1ns/1ps

module apf_menu_focus_cdc_tb;
  reg clk_destination = 1'b0;
  always #7 clk_destination = ~clk_destination;

  reg reset_n_async = 1'b0;
  reg menu_focus_source = 1'b0;
  wire menu_focus_destination;
  integer destination_edges = 0;
  integer transitions = 0;
  reg previous_destination = 1'b0;

  apf_menu_focus_cdc dut (
      .clk_destination(clk_destination),
      .reset_n_async(reset_n_async),
      .menu_focus_source(menu_focus_source),
      .menu_focus_destination(menu_focus_destination)
  );

  always @(posedge clk_destination) begin
    #1ps;
    destination_edges = destination_edges + 1;
    if (menu_focus_destination != previous_destination)
      transitions = transitions + 1;
    previous_destination = menu_focus_destination;
  end

  task automatic wait_level(
      input bit expected,
      input integer minimum_edges,
      input integer maximum_edges,
      input string message
  );
    integer start_edge;
    integer elapsed;
    begin
      start_edge = destination_edges;
      while (menu_focus_destination !== expected &&
             destination_edges - start_edge <= maximum_edges) begin
        @(posedge clk_destination);
        #1ps;
      end
      elapsed = destination_edges - start_edge;
      if (menu_focus_destination !== expected)
        $fatal(1, "%s: level never arrived", message);
      if (elapsed < minimum_edges || elapsed > maximum_edges)
        $fatal(1, "%s: latency %0d outside [%0d,%0d]", message,
               elapsed, minimum_edges, maximum_edges);
    end
  endtask

  initial begin
    #1;
    if (menu_focus_destination !== 1'b0)
      $fatal(1, "reset did not publish an unpaused destination immediately");

    // Release reset away from a destination edge, then assert focus at another
    // deliberately asynchronous phase.  A three-register level synchronizer
    // must produce one clean transition after three destination captures.
    #3 reset_n_async = 1'b1;
    #5 menu_focus_source = 1'b1;
    wait_level(1'b1, 3, 4, "focus assertion");
    if (transitions != 1)
      $fatal(1, "focus assertion produced %0d destination transitions", transitions);

    repeat (9) begin
      @(posedge clk_destination);
      #1ps;
      if (menu_focus_destination !== 1'b1)
        $fatal(1, "held focus level glitched low");
    end

    // Deassert at a different phase and require one bounded, clean release.
    #4 menu_focus_source = 1'b0;
    wait_level(1'b0, 3, 4, "focus release");
    if (transitions != 2)
      $fatal(1, "focus release produced %0d total transitions", transitions);

    // A late reset is asynchronous and must clear a held pause without waiting
    // for clk_destination.  Reset release still traverses all three stages.
    #3 menu_focus_source = 1'b1;
    wait_level(1'b1, 3, 4, "second focus assertion");
    #2 reset_n_async = 1'b0;
    #1;
    if (menu_focus_destination !== 1'b0)
      $fatal(1, "asynchronous reset did not clear held focus immediately");
    reset_n_async = 1'b1;
    wait_level(1'b1, 3, 4, "post-reset held source");

    $display("PASS menu-focus level CDC assert/release/hold/asynchronous-reset");
    $finish;
  end
endmodule
