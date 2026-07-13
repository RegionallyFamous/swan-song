`timescale 1ns/1ps

module apf_scanout_cadence_tb;
  localparam integer LINE_PIXELS = 397;
  localparam integer FRAME_LINES = 258;
  localparam integer PIXEL_DIVIDE = 6;
  localparam integer FRAME_SYSTEM_CYCLES =
      LINE_PIXELS * FRAME_LINES * PIXEL_DIVIDE;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg pixel_enable = 1'b0;
  wire [8:0] x;
  wire [8:0] y;
  wire line_end;
  wire frame_boundary;

  integer system_cycles = 0;
  integer boundary_count = 0;
  integer last_boundary_cycle = -1;
  integer frame_interval = -1;
  integer expected_x = 0;
  integer expected_y = 0;
  integer frame;
  integer pixel;
  integer stall;

  always #1 clk = ~clk;

  apf_scanout_cadence dut (
      .clk(clk),
      .reset(reset),
      .pixel_enable(pixel_enable),
      .x(x),
      .y(y),
      .line_end(line_end),
      .frame_boundary(frame_boundary)
  );

  task automatic clock_once(input bit enable);
    bit expected_line_end;
    bit expected_frame_boundary;
    begin
      @(negedge clk);
      pixel_enable = enable;
      #1ps;
      expected_line_end = expected_x == LINE_PIXELS - 1;
      expected_frame_boundary =
          enable && expected_line_end && expected_y == FRAME_LINES - 1;

      if (x !== expected_x[8:0] || y !== expected_y[8:0])
        $fatal(1, "position mismatch got=(%0d,%0d) expected=(%0d,%0d)",
               x, y, expected_x, expected_y);
      if (line_end !== expected_line_end)
        $fatal(1, "line-end mismatch position=(%0d,%0d)", x, y);
      if (frame_boundary !== expected_frame_boundary)
        $fatal(1, "frame-boundary mismatch position=(%0d,%0d)", x, y);

      if (frame_boundary) begin
        boundary_count = boundary_count + 1;
        if (last_boundary_cycle >= 0)
          frame_interval = system_cycles - last_boundary_cycle;
        last_boundary_cycle = system_cycles;
      end

      @(posedge clk);
      #1ps;
      system_cycles = system_cycles + 1;
      if (enable) begin
        if (expected_line_end) begin
          expected_x = 0;
          if (expected_y == FRAME_LINES - 1)
            expected_y = 0;
          else
            expected_y = expected_y + 1;
        end else begin
          expected_x = expected_x + 1;
        end
      end
    end
  endtask

  initial begin
    repeat (3) @(posedge clk);
    @(negedge clk);
    reset = 1'b0;

    // Two complete output frames with the production /6 pixel enable. Every
    // disabled source cycle must hold the raster position and boundary low.
    for (frame = 0; frame < 2; frame = frame + 1) begin
      for (pixel = 0; pixel < LINE_PIXELS * FRAME_LINES; pixel = pixel + 1) begin
        for (stall = 0; stall < PIXEL_DIVIDE - 1; stall = stall + 1)
          clock_once(1'b0);
        clock_once(1'b1);
      end
    end

    if (boundary_count != 2)
      $fatal(1, "frame boundary count %0d", boundary_count);
    if (frame_interval != FRAME_SYSTEM_CYCLES)
      $fatal(1, "frame interval %0d expected %0d",
             frame_interval, FRAME_SYSTEM_CYCLES);
    if (x != 0 || y != 0)
      $fatal(1, "raster did not wrap to origin got=(%0d,%0d)", x, y);

    $display(
        "PASS APF scanout cadence raster=397x258 system_cycles=614556 pixel_clock=6.144MHz refresh=59.984769Hz"
    );
    $finish;
  end
endmodule
