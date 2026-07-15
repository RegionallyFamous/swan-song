`timescale 1ns/1ps

// APF-safe scanout raster position generator.
//
// The Pocket video clock is 6.144 MHz.  The default 397 x 258 raster runs at
// 59.984769492 Hz.  The optional 391 x 258 raster runs at 60.905251888 Hz,
// inside APF's documented approximate 61 Hz ceiling, and reduces the number
// of complete native frames that must be skipped.  The mode input is applied
// only at a frame boundary by wonderswan.sv, so a line can never change length
// while it is being scanned.
// Active-area, blanking, and sync generation remain in wonderswan.sv; this
// block owns only the line/frame cadence and makes it directly testable.
module apf_scanout_cadence #(
    parameter [8:0] STANDARD_LINE_PIXELS = 9'd397,
    parameter [8:0] SMOOTH_LINE_PIXELS = 9'd391,
    parameter [8:0] FRAME_LINES = 9'd258
) (
    input  wire       clk,
    input  wire       reset,
    input  wire       pixel_enable,
    input  wire       smooth_61hz,
    output reg  [8:0] x,
    output reg  [8:0] y,
    output wire       line_end,
    output wire       frame_boundary
);
  localparam [8:0] FRAME_LAST = FRAME_LINES - 1'd1;
  wire [8:0] line_last = smooth_61hz ?
      SMOOTH_LINE_PIXELS - 1'd1 : STANDARD_LINE_PIXELS - 1'd1;

  assign line_end = x >= line_last;
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
