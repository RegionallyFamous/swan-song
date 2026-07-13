`timescale 1ns/1ps

// Convert Pocket video to the pure grayscale required by APF LCD modes.
module apf_grayscale_video (
    input  wire [23:0] rgb,
    input  wire        enabled,
    output wire [23:0] rgb_out
);
  // 1:2:1 integer luma: inexpensive, monotonic, and full-range at both ends.
  wire [9:0] luma_sum =
      {2'b00, rgb[23:16]} + {1'b0, rgb[15:8], 1'b0} + {2'b00, rgb[7:0]};
  wire [7:0] luma = luma_sum[9:2];

  assign rgb_out = enabled ? {3{luma}} : rgb;
endmodule
