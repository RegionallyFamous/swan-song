`timescale 1ns/1ps

// Associates the WonderSwan orientation bit with the physical frame bank that
// owns the pixels.  Buffered scanout can lag the live console by several
// producer frames, so using the live bit directly can rotate an older frame
// with newer metadata.  Bank metadata follows the same publish/promote rules
// as the pixels and therefore survives pending-frame supersession correctly.
//
// Direct mode deliberately permits pixel tearing, but its presentation
// orientation is still latched at the outgoing scanout frame boundary.  The
// first post-reset level is captured immediately so a title that boots in
// portrait does not need to emit one incorrectly oriented startup frame.
module apf_frame_orientation (
    input  wire       clk,
    input  wire       reset,

    input  wire       producer_frame_done,
    input  wire [2:0] write_bank,
    input  wire       producer_orientation,

    input  wire       consumer_frame_boundary,
    input  wire       buffered_frame_visible,
    input  wire [2:0] history_newest,

    output wire       presented_orientation
);
  reg [4:0] bank_orientation = 5'b00000;
  reg direct_orientation = 1'b0;
  reg direct_orientation_valid = 1'b0;

  always @(posedge clk) begin
    if (reset) begin
      bank_orientation <= 5'b00000;
      direct_orientation <= 1'b0;
      direct_orientation_valid <= 1'b0;
    end else begin
      if (!direct_orientation_valid) begin
        direct_orientation <= producer_orientation;
        direct_orientation_valid <= 1'b1;
      end else if (consumer_frame_boundary) begin
        direct_orientation <= producer_orientation;
      end

      if (producer_frame_done) begin
        // The arbiter guarantees a legal 0..4 writer.  Keep a defensive
        // default that ignores a corrupt/reserved identifier instead of
        // indexing outside the metadata vector.
        case (write_bank)
          3'd0: bank_orientation[0] <= producer_orientation;
          3'd1: bank_orientation[1] <= producer_orientation;
          3'd2: bank_orientation[2] <= producer_orientation;
          3'd3: bank_orientation[3] <= producer_orientation;
          3'd4: bank_orientation[4] <= producer_orientation;
          default: begin
          end
        endcase
      end
    end
  end

  reg buffered_orientation;
  always @(*) begin
    case (history_newest)
      3'd0: buffered_orientation = bank_orientation[0];
      3'd1: buffered_orientation = bank_orientation[1];
      3'd2: buffered_orientation = bank_orientation[2];
      3'd3: buffered_orientation = bank_orientation[3];
      3'd4: buffered_orientation = bank_orientation[4];
      default: buffered_orientation = 1'b0;
    endcase
  end

  assign presented_orientation = buffered_frame_visible ?
      buffered_orientation : direct_orientation;
endmodule
