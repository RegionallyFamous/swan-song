`timescale 1ns/1ps

// Source-pinned color conversion and temporal response for three RGB444
// framebuffer samples.
//
// mode 0: newest sample only
// mode 1: rounded average of newest and previous samples
// mode 2: finite LCD response, 1/2 newest + 1/4 previous + 1/4 oldest
// mode 3: reserved; fail safely to mode 0
//
// color_profile 0 is the exact RGB444 x17 expansion used by Mednafen 1.32.1.
// color_profile 1 is the high eight bits of pinned ares' WonderSwan Color /
// SwanCrystal color-emulation matrix (ares 449b937, ws/ppu/color.cpp).
//
// ares' generic video screen recursively averages the current and prior
// filtered outputs.  Mode 2 is a project-designed finite approximation of
// that response: expanding the recurrence gives 1/2, 1/4, ... weights, and
// the unrepresented older tail is collapsed onto the oldest available sample.
// It is deterministic and constant-color invariant, but it is not a measured
// WonderSwan Color or SwanCrystal panel transfer function.
module apf_temporal_blend (
    input  wire [1:0]  mode,
    input  wire        color_profile,
    input  wire [11:0] rgb_newest,
    input  wire [11:0] rgb_previous,
    input  wire [11:0] rgb_oldest,
    output wire [23:0] rgb_out
);
  function automatic [23:0] transform_color;
    input       profile;
    input [11:0] sample;
    reg [8:0] red_sum;
    reg [8:0] green_sum;
    reg [8:0] blue_sum;
    begin
      if (profile) begin
        // ares normalizes these nine-bit sums to sixteen bits. The high byte
        // delivered to Pocket is therefore exactly floor(sum / 2).
        red_sum = sample[11:8] * 9'd26 +
                  sample[7:4]  * 9'd4  +
                  sample[3:0]  * 9'd2;
        green_sum = sample[7:4] * 9'd24 +
                    sample[3:0] * 9'd8;
        blue_sum = sample[11:8] * 9'd6 +
                   sample[7:4]  * 9'd4 +
                   sample[3:0]  * 9'd22;
        transform_color = {red_sum[8:1], green_sum[8:1], blue_sum[8:1]};
      end else begin
        transform_color = {
          sample[11:8], sample[11:8],
          sample[7:4],  sample[7:4],
          sample[3:0],  sample[3:0]
        };
      end
    end
  endfunction

  function automatic [7:0] blend_channel;
    input [1:0] blend_mode;
    input [7:0] newest;
    input [7:0] previous;
    input [7:0] oldest;
    reg [9:0] weighted_sum;
    begin
      case (blend_mode)
        2'd1: begin
          // Preserve the existing two-frame mode's round-half-up behavior.
          weighted_sum = {2'b00, newest} + {2'b00, previous} + 10'd1;
          blend_channel = weighted_sum[8:1];
        end

        2'd2: begin
          // 1/2 newest + 1/4 previous + 1/4 oldest. Truncation matches
          // ares' per-channel recursive average rather than adding bias.
          weighted_sum = {1'b0, newest, 1'b0} +
                         {2'b00, previous} + {2'b00, oldest};
          blend_channel = weighted_sum[9:2];
        end

        default: begin
          // Both Off and the reserved encoding preserve the newest sample.
          weighted_sum = 10'd0;
          blend_channel = newest;
        end
      endcase
    end
  endfunction

  wire [23:0] newest_color = transform_color(color_profile, rgb_newest);
  wire [23:0] previous_color = transform_color(color_profile, rgb_previous);
  wire [23:0] oldest_color = transform_color(color_profile, rgb_oldest);

  assign rgb_out[23:16] = blend_channel(
      mode, newest_color[23:16], previous_color[23:16], oldest_color[23:16]
  );
  assign rgb_out[15:8] = blend_channel(
      mode, newest_color[15:8], previous_color[15:8], oldest_color[15:8]
  );
  assign rgb_out[7:0] = blend_channel(
      mode, newest_color[7:0], previous_color[7:0], oldest_color[7:0]
  );
endmodule
