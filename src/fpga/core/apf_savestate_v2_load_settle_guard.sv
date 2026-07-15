`timescale 1ns/1ps
`default_nettype none

// Converts the EEPROM controller's intentional load/settle acknowledge gap
// into an explicit ownership-retention handshake for apf_savestate_v2_owner.
//
// The raw frozen acknowledgement is never forged.  Instead, device_settling
// tells the owner that a previously acknowledged EEPROM is still exclusively
// owned while its synchronous RAM pipeline settles.  The owner may tolerate
// raw ack low only during this bounded interval and may not release the device
// until raw ack returns.  Reset, repeated/illegal loads, an unrequested ack
// loss, or an overlong gap raise a sticky fault and end the retention window.
//
// This module is intentionally absent from ap_core.qsf.  A future production
// data plane must instantiate one guard per EEPROM in the EEPROM clock domain
// and synchronize any cross-domain load command before enabling Memories.
module apf_savestate_v2_load_settle_guard #(
    // The real EEPROM needs one raw-low sample for a canonical v2 image and
    // two for its defensive legacy-state normalization path.  Integration
    // must bind this parameter to the proved device implementation.
    parameter integer MAX_ACK_LOW_CYCLES = 2
) (
    input  wire clk,
    input  wire lifecycle_reset_n,

    input  wire freeze_request,
    input  wire load_pulse,
    input  wire device_reset,
    input  wire device_frozen_raw,

    output wire device_settling,
    output reg  protocol_fault
);
  reg settling_i;
  reg freeze_was_acknowledged;
  integer ack_low_cycles;

  // Do not retain ownership through release or a device reset, even between
  // clocks.  All interface inputs are otherwise synchronous to clk.
  assign device_settling = freeze_request && !device_reset && settling_i;

  always @(posedge clk or negedge lifecycle_reset_n) begin
    if (!lifecycle_reset_n) begin
      settling_i <= 1'b0;
      freeze_was_acknowledged <= 1'b0;
      ack_low_cycles <= 0;
      protocol_fault <= 1'b0;
    end else if (!freeze_request) begin
      settling_i <= 1'b0;
      freeze_was_acknowledged <= 1'b0;
      ack_low_cycles <= 0;
      if (load_pulse)
        protocol_fault <= 1'b1;
    end else if (device_reset) begin
      // EEPROM reset has priority over freeze in the real device and may
      // replace live controller state.  It is never an allowed settle gap.
      settling_i <= 1'b0;
      freeze_was_acknowledged <= 1'b0;
      ack_low_cycles <= 0;
      protocol_fault <= 1'b1;
    end else if (settling_i) begin
      if (load_pulse) begin
        // A second pulse makes the eventual raw ack ambiguous.
        settling_i <= 1'b0;
        ack_low_cycles <= 0;
        protocol_fault <= 1'b1;
      end else if (device_frozen_raw) begin
        settling_i <= 1'b0;
        freeze_was_acknowledged <= 1'b1;
        ack_low_cycles <= 0;
      end else if (ack_low_cycles < MAX_ACK_LOW_CYCLES) begin
        ack_low_cycles <= ack_low_cycles + 1;
      end else begin
        // Stop claiming retained ownership.  The owner observes raw ack low
        // without device_settling and takes its normal fail-closed path.
        settling_i <= 1'b0;
        freeze_was_acknowledged <= 1'b0;
        ack_low_cycles <= 0;
        protocol_fault <= 1'b1;
      end
    end else if (load_pulse) begin
      if (device_frozen_raw && freeze_was_acknowledged) begin
        settling_i <= 1'b1;
        ack_low_cycles <= 0;
      end else begin
        // Load on the first freeze edge, or after ack loss, is illegal.
        protocol_fault <= 1'b1;
      end
    end else if (device_frozen_raw) begin
      freeze_was_acknowledged <= 1'b1;
    end else if (freeze_was_acknowledged) begin
      // A raw drop without an accepted load is never masked.
      freeze_was_acknowledged <= 1'b0;
      protocol_fault <= 1'b1;
    end
  end

  initial begin
    if (MAX_ACK_LOW_CYCLES < 1)
      $error("MAX_ACK_LOW_CYCLES must be positive");
  end
endmodule

`default_nettype wire
