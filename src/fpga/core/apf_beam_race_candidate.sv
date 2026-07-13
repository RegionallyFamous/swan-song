`timescale 1ns/1ps

// Isolated Phase-4 experiment; deliberately not instantiated by the core.
//
// A candidate beam-race frame may use the current writer only after pixel zero
// of that generation has been observed.  `producer_contract_valid` is an
// intentionally strict prerequisite: it must guarantee that all 144 rows will
// finish at normal cadence after the output boundary.  The translated GPU does
// not currently provide such a guarantee because LCD Final Line is live and
// programmable, so production integration must leave this input unavailable
// (and therefore fail closed) until that contract can be proven.
module apf_beam_race_candidate (
    input  wire        clk,
    input  wire        reset,
    input  wire        pixel_write,
    input  wire [14:0] pixel_address,
    input  wire        producer_frame_done,
    input  wire [2:0]  writer_bank,
    input  wire        output_frame_boundary,
    input  wire        normal_speed,
    input  wire        producer_contract_valid,
    output reg         beam_valid,
    output reg  [2:0]  beam_bank,
    output wire        protect_valid,
    output wire [2:0]  protect_bank
);
  reg writer_started;

  assign protect_valid = beam_valid;
  assign protect_bank = beam_bank;

  always @(posedge clk) begin
    if (reset) begin
      writer_started <= 1'b0;
      beam_valid <= 1'b0;
      beam_bank <= 3'd0;
    end else begin
      // A completed writer is handed to the ordinary complete-frame path. The
      // next bank is ineligible until its first pixel has actually arrived.
      if (producer_frame_done)
        writer_started <= 1'b0;
      else if (pixel_write && pixel_address == 15'd0)
        writer_started <= 1'b1;

      if (output_frame_boundary) begin
        beam_valid <= normal_speed && producer_contract_valid && writer_started;
        if (normal_speed && producer_contract_valid && writer_started)
          beam_bank <= writer_bank;
      end
    end
  end
endmodule
