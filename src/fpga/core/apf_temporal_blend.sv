`timescale 1ns/1ps

// Exact temporal blending for three RGB444 framebuffer samples.
//
// mode 0: newest sample only
// mode 1: rounded average of newest and previous samples
// mode 2: rounded average of all three samples
// mode 3: reserved; fail safely to mode 0
//
// Averaging is performed after exact 4-bit-to-8-bit expansion. Consequently
// equal inputs are invariant, including full white (255), rather than becoming
// progressively darker when temporal blending is enabled.
module apf_temporal_blend (
    input  wire [1:0]  mode,
    input  wire [11:0] rgb_newest,
    input  wire [11:0] rgb_previous,
    input  wire [11:0] rgb_oldest,
    output wire [23:0] rgb_out
);
  function automatic [7:0] blend_channel;
    input [1:0] blend_mode;
    input [3:0] newest;
    input [3:0] previous;
    input [3:0] oldest;
    reg [5:0] sample_sum;
    reg [9:0] expanded_sum;
    reg [9:0] rounded_result;
    begin
      case (blend_mode)
        2'd1: begin
          sample_sum = {2'b00, newest} + {2'b00, previous};
          expanded_sum = sample_sum * 10'd17;
          rounded_result = (expanded_sum + 10'd1) >> 1;
          blend_channel =
              rounded_result > 10'd255 ? 8'hFF : rounded_result[7:0];
        end

        2'd2: begin
          sample_sum =
              {2'b00, newest} + {2'b00, previous} + {2'b00, oldest};
          expanded_sum = sample_sum * 10'd17;
          rounded_result = (expanded_sum + 10'd1) / 10'd3;
          blend_channel =
              rounded_result > 10'd255 ? 8'hFF : rounded_result[7:0];
        end

        default: begin
          // Both Off and the reserved encoding preserve the newest sample.
          sample_sum = 6'd0;
          expanded_sum = 10'd0;
          rounded_result = 10'd0;
          blend_channel = {newest, newest};
        end
      endcase
    end
  endfunction

  assign rgb_out[23:16] = blend_channel(
      mode, rgb_newest[11:8], rgb_previous[11:8], rgb_oldest[11:8]
  );
  assign rgb_out[15:8] = blend_channel(
      mode, rgb_newest[7:4], rgb_previous[7:4], rgb_oldest[7:4]
  );
  assign rgb_out[7:0] = blend_channel(
      mode, rgb_newest[3:0], rgb_previous[3:0], rgb_oldest[3:0]
  );
endmodule
