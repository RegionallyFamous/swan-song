`timescale 1ns/1ps

// Atomic bundled-data CDC for Pocket's runtime nonvolatile-slot metadata.
//
// The producer must pulse commit_source only after both metadata fields belong
// to the same, fully received cartridge. An accepted snapshot remains frozen
// until the acknowledgement returns. A commit attempted while busy is
// rejected explicitly instead of replacing the in-flight payload.
module apf_save_metadata_cdc (
    input  wire        reset_n,

    input  wire        clk_source,
    input  wire [19:0] save_size_bytes_source,
    input  wire        has_rtc_source,
    input  wire        commit_source,
    output wire        busy_source,
    output reg         rejected_source,

    input  wire        clk_74a,
    (* preserve *) output reg  [19:0] save_size_bytes_74a,
    (* preserve *) output reg         has_rtc_74a,
    output reg         metadata_valid_74a
);
  // Assertion is asynchronous so an interrupted transfer is discarded in
  // both domains. Release is synchronized independently to each clock.
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *) reg [1:0] source_reset_sync = 2'b00;
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *) reg [1:0] destination_reset_sync = 2'b00;
  wire source_reset_n = source_reset_sync[1];
  wire destination_reset_n = destination_reset_sync[1];

  always @(posedge clk_source or negedge reset_n) begin
    if (!reset_n) source_reset_sync <= 2'b00;
    else source_reset_sync <= {source_reset_sync[0], 1'b1};
  end

  always @(posedge clk_74a or negedge reset_n) begin
    if (!reset_n) destination_reset_sync <= 2'b00;
    else destination_reset_sync <= {destination_reset_sync[0], 1'b1};
  end

  // The footer decoder currently emits a sparse set of canonical save sizes.
  // Preserve every logical payload bit at both ends so Quartus cannot fold
  // constant-zero bits out of the exact, fail-closed bundled-data constraint.
  (* preserve *) reg [20:0] metadata_hold;
  reg request_toggle;
  reg commit_previous;

  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *) reg acknowledge_meta;
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *) reg acknowledge_sync;

  reg acknowledge_toggle;
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *) reg request_meta;
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *) reg request_sync;
  reg request_seen;

  assign busy_source = request_toggle != acknowledge_sync;

  always @(posedge clk_source or negedge source_reset_n) begin
    if (!source_reset_n) begin
      metadata_hold <= 21'd0;
      request_toggle <= 1'b0;
      commit_previous <= 1'b0;
      acknowledge_meta <= 1'b0;
      acknowledge_sync <= 1'b0;
      rejected_source <= 1'b0;
    end else begin
      acknowledge_meta <= acknowledge_toggle;
      acknowledge_sync <= acknowledge_meta;
      commit_previous <= commit_source;
      rejected_source <= 1'b0;

      if (commit_source && !commit_previous) begin
        if (!busy_source) begin
          metadata_hold <= {has_rtc_source, save_size_bytes_source};
          request_toggle <= ~request_toggle;
        end else begin
          rejected_source <= 1'b1;
        end
      end
    end
  end

  always @(posedge clk_74a or negedge destination_reset_n) begin
    if (!destination_reset_n) begin
      request_meta <= 1'b0;
      request_sync <= 1'b0;
      request_seen <= 1'b0;
      acknowledge_toggle <= 1'b0;
      save_size_bytes_74a <= 20'd0;
      has_rtc_74a <= 1'b0;
      metadata_valid_74a <= 1'b0;
    end else begin
      request_meta <= request_toggle;
      request_sync <= request_meta;
      metadata_valid_74a <= 1'b0;

      if (request_sync != request_seen) begin
        {has_rtc_74a, save_size_bytes_74a} <= metadata_hold;
        metadata_valid_74a <= 1'b1;
        request_seen <= request_sync;
        acknowledge_toggle <= request_sync;
      end
    end
  end
endmodule
