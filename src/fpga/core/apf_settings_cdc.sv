`timescale 1ns/1ps

// Atomic level-tracking CDC for the complete Pocket interact-settings bundle.
//
// APF writes persistent interact values in the clk_source domain. Several
// legal menu transitions change both bits of a field (for example 01 -> 10),
// so synchronizing the individual bits can expose a transient but valid-looking
// setting. This module freezes one coherent snapshot before toggling a request,
// captures it once in the destination, and acknowledges that capture before the
// source payload may change. If settings change while busy, the newest complete
// level is sent immediately after the acknowledgement.
module apf_settings_cdc #(
    // Matches interact.json defaults in this packing:
    // {system[1:0], cpu_turbo, triple_buffer, lcd_response[1:0],
    //  orientation[1:0], landscape_180, color_profile,
    //  fastforward_sound}.
    parameter [10:0] DEFAULT_SETTINGS = 11'h081
) (
    input  wire       reset_n,

    input  wire       clk_source,
    input  wire [10:0] settings_source,
    output wire       update_pending_source,

    input  wire       clk_destination,
    output reg  [10:0] settings_destination
);
  // Assertion is asynchronous so loss of PLL readiness discards an in-flight
  // update in both domains. Release is synchronized independently to each.
  (* ASYNC_REG = "TRUE" *) reg [1:0] source_reset_sync;
  (* ASYNC_REG = "TRUE" *) reg [1:0] destination_reset_sync;
  wire source_reset_n = source_reset_sync[1];
  wire destination_reset_n = destination_reset_sync[1];

  always @(posedge clk_source or negedge reset_n) begin
    if (!reset_n) source_reset_sync <= 2'b00;
    else source_reset_sync <= {source_reset_sync[0], 1'b1};
  end

  always @(posedge clk_destination or negedge reset_n) begin
    if (!reset_n) destination_reset_sync <= 2'b00;
    else destination_reset_sync <= {destination_reset_sync[0], 1'b1};
  end

  reg [10:0] settings_hold_source;
  reg request_toggle_source;
  (* ASYNC_REG = "TRUE" *) reg acknowledge_meta_source;
  (* ASYNC_REG = "TRUE" *) reg acknowledge_sync_source;

  reg acknowledge_toggle_destination;
  (* ASYNC_REG = "TRUE" *) reg request_meta_destination;
  (* ASYNC_REG = "TRUE" *) reg request_sync_destination;
  reg request_seen_destination;

  wire transfer_busy_source =
      request_toggle_source != acknowledge_sync_source;
  assign update_pending_source = transfer_busy_source ||
      settings_source != settings_hold_source;

  always @(posedge clk_source or negedge source_reset_n) begin
    if (!source_reset_n) begin
      settings_hold_source <= DEFAULT_SETTINGS;
      request_toggle_source <= 1'b0;
      acknowledge_meta_source <= 1'b0;
      acknowledge_sync_source <= 1'b0;
    end else begin
      acknowledge_meta_source <= acknowledge_toggle_destination;
      acknowledge_sync_source <= acknowledge_meta_source;

      if (!transfer_busy_source &&
          settings_source != settings_hold_source) begin
        settings_hold_source <= settings_source;
        request_toggle_source <= ~request_toggle_source;
      end
    end
  end

  always @(posedge clk_destination or negedge destination_reset_n) begin
    if (!destination_reset_n) begin
      request_meta_destination <= 1'b0;
      request_sync_destination <= 1'b0;
      request_seen_destination <= 1'b0;
      acknowledge_toggle_destination <= 1'b0;
      settings_destination <= DEFAULT_SETTINGS;
    end else begin
      request_meta_destination <= request_toggle_source;
      request_sync_destination <= request_meta_destination;

      if (request_sync_destination != request_seen_destination) begin
        settings_destination <= settings_hold_source;
        request_seen_destination <= request_sync_destination;
        acknowledge_toggle_destination <= request_sync_destination;
      end
    end
  end
endmodule
