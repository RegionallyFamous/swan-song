`timescale 1ns/1ps

module apf_reset_sync_tb;
  localparam integer STAGES = 3;

  reg clk = 1'b0;
  reg reset_n_async = 1'b0;
  wire reset_n_sync;

  integer destination_edges = 0;
  integer release_edge = 0;
  integer async_assertions = 0;
  reg previous_sync = 1'b0;

  always #5ns clk = ~clk;

  apf_reset_sync #(
      .STAGES(STAGES)
  ) dut (
      .clk          (clk),
      .reset_n_async(reset_n_async),
      .reset_n_sync (reset_n_sync)
  );

  always @(posedge clk) begin
    destination_edges = destination_edges + 1;
    #1ps;

    if (reset_n_sync !== 1'b0 && reset_n_sync !== 1'b1) begin
      $fatal(1, "reset_n_sync became unknown at destination edge %0d", destination_edges);
    end

    if (!previous_sync && reset_n_sync) begin
      if (!reset_n_async) begin
        $fatal(1, "reset_n_sync released while async reset remained asserted");
      end
      release_edge = destination_edges;
    end
    previous_sync = reset_n_sync;
  end

  always @(negedge reset_n_async) begin
    async_assertions = async_assertions + 1;
    #1ps;
    if (reset_n_sync !== 1'b0) begin
      $fatal(1, "asynchronous assertion was not immediate");
    end
    previous_sync = 1'b0;
  end

  always @(reset_n_sync) begin
    if (reset_n_sync !== 1'b0 && reset_n_sync !== 1'b1) begin
      $fatal(1, "reset_n_sync changed to X/Z");
    end
    if (reset_n_sync && !clk) begin
      $fatal(1, "reset_n_sync released away from a destination rising edge");
    end
  end

  task automatic expect_release_after_exact_edges;
    integer first_edge;
    integer edge_index;
    begin
      release_edge = 0;
      first_edge = destination_edges + 1;
      reset_n_async = 1'b1;

      for (edge_index = 1; edge_index <= STAGES; edge_index = edge_index + 1) begin
        @(posedge clk);
        #2ps;
        if (edge_index < STAGES && reset_n_sync !== 1'b0) begin
          $fatal(1, "early release after %0d/%0d destination edges", edge_index, STAGES);
        end
        if (edge_index == STAGES && reset_n_sync !== 1'b1) begin
          $fatal(1, "missing release after exactly %0d destination edges", STAGES);
        end
      end

      if (release_edge != first_edge + STAGES - 1) begin
        $fatal(
            1,
            "release edge mismatch: got %0d expected %0d",
            release_edge,
            first_edge + STAGES - 1
        );
      end
    end
  endtask

  initial begin
    #1ps;
    if (reset_n_sync !== 1'b0) begin
      $fatal(1, "power-up state was not deterministic reset");
    end

    // Release between destination edges and prove the full synchronizer delay.
    #2ns;
    expect_release_after_exact_edges();

    // Lose ready/reset between edges.  Assertion must not wait for a clock.
    #3ns;
    reset_n_async = 1'b0;
    #2ns;
    if (reset_n_sync !== 1'b0) begin
      $fatal(1, "reset_n_sync did not remain asserted after off-edge loss");
    end

    // Hold reset across multiple edges, then recover with the same exact delay.
    repeat (2) @(posedge clk);
    #2ns;
    expect_release_after_exact_edges();

    // Repeated short lock loss must clear every synchronizer stage immediately.
    #1ns;
    reset_n_async = 1'b0;
    #1ns;
    reset_n_async = 1'b1;
    @(posedge clk);
    #2ps;
    if (reset_n_sync !== 1'b0) begin
      $fatal(1, "one edge after repeated loss released reset early");
    end

    #1ns;
    reset_n_async = 1'b0;
    #1ns;
    if (reset_n_sync !== 1'b0) begin
      $fatal(1, "second repeated assertion failed");
    end
    #1ns;
    expect_release_after_exact_edges();

    if (async_assertions != 3) begin
      $fatal(1, "asynchronous assertion count=%0d expected=3", async_assertions);
    end

    $display(
        "PASS APF reset synchronizer async_assertions=%0d release_stages=%0d destination_edges=%0d",
        async_assertions,
        STAGES,
        destination_edges
    );
    $finish;
  end
endmodule
