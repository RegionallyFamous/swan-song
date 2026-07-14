`timescale 1ns/1ps

// Atomic physical-input ownership crossing.
//
// The filtered button bitmap and its ownership state are one logical value:
// observing either half from a different PAD sample can expose a torn chord or
// release input ownership before the neutral bitmap has arrived.  Hold the
// complete 17-bit payload stable while a toggle request crosses to clk_sys,
// capture it in one destination edge, and acknowledge that capture before the
// source payload may change again.  Changes which arrive while a transfer is in
// flight are coalesced into the next complete payload.
//
// A blocked payload is canonicalized to all-zero buttons.  Reset asserts the
// same safe destination value asynchronously; release proceeds only through a
// subsequent acknowledged source transfer.
module apf_input_blocked_cdc (
    input  wire        clk_source,
    input  wire        clk_destination,
    input  wire        reset_n_async,
    input  wire [15:0] buttons_source,
    input  wire        input_blocked_source,
    output wire [15:0] buttons_destination,
    output wire        input_blocked_destination
);

  localparam [16:0] SAFE_PAYLOAD = {1'b1, 16'h0000};

  wire [16:0] canonical_payload_source =
      input_blocked_source ? SAFE_PAYLOAD : {1'b0, buttons_source};

  reg [16:0] payload_hold_source = SAFE_PAYLOAD;
  reg request_toggle_source = 1'b0;

  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *)
  reg acknowledge_meta_source = 1'b0;
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *)
  reg acknowledge_sync_source = 1'b0;

  reg acknowledge_toggle_destination = 1'b0;
  reg request_seen_destination = 1'b0;

  // Four APF trigger bits are intentionally unused by WonderSwan today. Keep
  // the whole destination register bank so the fitted netlist and its exact
  // SDC cardinality continue to enforce one complete 17-bit capture.
  (* preserve, noprune *) reg [16:0] payload_destination = SAFE_PAYLOAD;
  assign {input_blocked_destination, buttons_destination} =
      payload_destination;

  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *)
  reg request_meta_destination = 1'b0;
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *)
  reg request_sync_destination = 1'b0;

  wire transfer_idle_source =
      acknowledge_sync_source == request_toggle_source;

  always @(posedge clk_source or negedge reset_n_async) begin
    if (!reset_n_async) begin
      payload_hold_source <= SAFE_PAYLOAD;
      request_toggle_source <= 1'b0;
      acknowledge_meta_source <= 1'b0;
      acknowledge_sync_source <= 1'b0;
    end else begin
      acknowledge_meta_source <= acknowledge_toggle_destination;
      acknowledge_sync_source <= acknowledge_meta_source;

      if (transfer_idle_source &&
          canonical_payload_source != payload_hold_source) begin
        payload_hold_source <= canonical_payload_source;
        request_toggle_source <= ~request_toggle_source;
      end
    end
  end

  always @(posedge clk_destination or negedge reset_n_async) begin
    if (!reset_n_async) begin
      payload_destination <= SAFE_PAYLOAD;
      acknowledge_toggle_destination <= 1'b0;
      request_seen_destination <= 1'b0;
      request_meta_destination <= 1'b0;
      request_sync_destination <= 1'b0;
    end else begin
      request_meta_destination <= request_toggle_source;
      request_sync_destination <= request_meta_destination;

      if (request_sync_destination != request_seen_destination) begin
        payload_destination <= payload_hold_source;
        request_seen_destination <= request_sync_destination;
        acknowledge_toggle_destination <= request_sync_destination;
      end
    end
  end

endmodule
