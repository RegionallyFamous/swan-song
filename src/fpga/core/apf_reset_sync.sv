`timescale 1ns/1ps

// Active-low reset/ready synchronizer.
//
// A low input asserts the output asynchronously so destination logic is put in
// reset even when its clock has stopped or is not yet stable.  A high input is
// released only after STAGES clean rising edges in the destination domain.
module apf_reset_sync #(
    parameter integer STAGES = 3
) (
    input  wire clk,
    input  wire reset_n_async,
    output wire reset_n_sync
);
  // Preserve the chain and identify every stage for Quartus metastability
  // optimization using Intel's supported HDL assignment attribute.
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *)
  reg [STAGES-1:0] sync_chain = {STAGES{1'b0}};

  initial begin
    if (STAGES < 2) begin
      $error("apf_reset_sync requires STAGES >= 2; received %0d", STAGES);
    end
  end

  always @(posedge clk or negedge reset_n_async) begin
    if (!reset_n_async) begin
      sync_chain <= {STAGES{1'b0}};
    end else begin
      sync_chain <= {sync_chain[STAGES-2:0], 1'b1};
    end
  end

  assign reset_n_sync = sync_chain[STAGES-1];
endmodule
