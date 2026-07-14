`timescale 1ns/1ps

module apf_pll_boot_reset_tb;
  reg clk = 1'b0;
  wire reset;

  integer edge_count = 0;

  always #5ns clk = ~clk;

  apf_pll_boot_reset dut (
      .clk  (clk),
      .reset(reset)
  );

  initial begin
    #1ps;
    if (reset !== 1'b1) begin
      $fatal(1, "PLL reset was not asserted at power-up");
    end

    repeat (7) begin
      @(posedge clk);
      edge_count = edge_count + 1;
      #1ps;
      if (reset !== 1'b1) begin
        $fatal(1, "PLL reset released early after edge %0d", edge_count);
      end
    end

    @(posedge clk);
    edge_count = edge_count + 1;
    #1ps;
    if (reset !== 1'b0) begin
      $fatal(1, "PLL reset did not release after exactly eight edges");
    end

    repeat (32) begin
      @(posedge clk);
      edge_count = edge_count + 1;
      #1ps;
      if (reset !== 1'b0) begin
        $fatal(1, "PLL reset reasserted after boot at edge %0d", edge_count);
      end
    end

    $display(
        "PASS APF PLL boot reset asserted_edges=8 observed_low_edges=%0d",
        edge_count - 8
    );
    $finish;
  end
endmodule
