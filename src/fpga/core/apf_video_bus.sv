`default_nettype none

// Convert the WonderSwan scan bundle into the APF video protocol. The core
// scan generator and Pocket video clock are related outputs of the same PLL;
// capture the complete bundle on the intervening system falling edge so RGB
// and control cannot be assembled from different scan-generator cycles.
module apf_video_bus (
    input wire clk_sys,
    input wire clk_video,

    input wire [23:0] core_rgb,
    input wire        core_hblank,
    input wire        core_vblank,
    input wire        core_hs,
    input wire        core_vs,

    input wire [23:0] scaler_eol_word,
    input wire        displaymode_grayscale_requested,

    output reg  [23:0] video_rgb = 24'd0,
    output reg         video_de = 1'b0,
    output reg         video_vs = 1'b0,
    output reg         video_hs = 1'b0,
    output wire        frame_start_video,
    output reg         displaymode_grayscale_applied = 1'b0
);
  reg [23:0] core_rgb_half = 24'd0;
  reg core_hblank_half = 1'b1;
  reg core_vblank_half = 1'b1;
  reg core_hs_half = 1'b0;
  reg core_vs_half = 1'b0;

  always @(negedge clk_sys) begin
    core_rgb_half <= core_rgb;
    core_hblank_half <= core_hblank;
    core_vblank_half <= core_vblank;
    core_hs_half <= core_hs;
    core_vs_half <= core_vs;
  end

  wire de = ~(core_hblank_half || core_vblank_half);
  wire [23:0] displaymode_video_rgb;
  apf_grayscale_video displaymode_video (
      .rgb(core_rgb_half),
      .enabled(displaymode_grayscale_applied),
      .rgb_out(displaymode_video_rgb)
  );

  reg [2:0] hs_delay = 3'd0;
  reg hs_prev = 1'b0;
  reg vs_prev = 1'b0;
  reg de_prev = 1'b0;

  assign frame_start_video = ~vs_prev && core_vs_half;

  always @(posedge clk_video) begin
    // Reserved words outside DE are always zero except for the single scaler
    // slot command emitted on the active-line DE falling edge.
    video_hs  <= 1'b0;
    video_de  <= 1'b0;
    video_rgb <= 24'd0;

    if (de) begin
      video_de  <= 1'b1;
      video_rgb <= displaymode_video_rgb;
    end else if (de_prev && ~de) begin
      video_rgb <= scaler_eol_word;
    end

    if (hs_delay > 0) begin
      hs_delay <= hs_delay - 1'b1;
    end

    if (hs_delay == 1) begin
      video_hs <= 1'b1;
    end

    if (~hs_prev && core_hs_half) begin
      // Keep HSync clear of VSync and the active/eol words.
      hs_delay <= 3'd7;
    end

    video_vs <= frame_start_video;
    if (frame_start_video) begin
      // Display mode changes are visible only at a complete frame boundary.
      displaymode_grayscale_applied <= displaymode_grayscale_requested;
    end

    hs_prev <= core_hs_half;
    vs_prev <= core_vs_half;
    de_prev <= de;
  end
endmodule

`default_nettype wire
