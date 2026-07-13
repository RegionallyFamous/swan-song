`timescale 1ns/1ps

// APF-safe 60 Hz scanout raster position generator.
//
// The Pocket video clock is 6.144 MHz.  A 397 x 258 raster therefore runs at
// 59.984769492 Hz, inside APF's documented 47 Hz to ~61 Hz input range and
// substantially closer to nominal 60 Hz than the inherited 401 x 258 raster.
// Active-area, blanking, and sync generation remain in wonderswan.sv; this
// block owns only the line/frame cadence and makes it directly testable.
module apf_scanout_cadence #(
    parameter [8:0] LINE_PIXELS = 9'd397,
    parameter [8:0] FRAME_LINES = 9'd258
) (
    input  wire       clk,
    input  wire       reset,
    input  wire       pixel_enable,
    output reg  [8:0] x,
    output reg  [8:0] y,
    output wire       line_end,
    output wire       frame_boundary
);
  localparam [8:0] LINE_LAST = LINE_PIXELS - 1'd1;
  localparam [8:0] FRAME_LAST = FRAME_LINES - 1'd1;

  assign line_end = x >= LINE_LAST;
  assign frame_boundary = pixel_enable && line_end && y >= FRAME_LAST;

  always @(posedge clk) begin
    if (reset) begin
      x <= 9'd0;
      y <= 9'd0;
    end else if (pixel_enable) begin
      if (line_end) begin
        x <= 9'd0;
        if (y >= FRAME_LAST)
          y <= 9'd0;
        else
          y <= y + 1'd1;
      end else begin
        x <= x + 1'd1;
      end
    end
  end
endmodule
