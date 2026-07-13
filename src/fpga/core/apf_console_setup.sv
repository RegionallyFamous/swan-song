`timescale 1ns/1ps

// Recreate the original WonderSwan power-on owner-setup gesture from a Pocket
// interact action.  The source-domain action asserts console reset and Start
// together, then releases reset first so the boot ROM samples a held Start.
//
// These are levels, not pulses: each crosses the asynchronous clk_source ->
// clk_destination boundary through its own three-stage synchronizer.  A
// retrigger reloads both intervals, while Reset Enter clears both source and
// destination state immediately so no stale forced input can survive a host
// lifecycle restart.
module apf_console_setup #(
    parameter integer RESET_CYCLES = 1_048_576,
    parameter integer START_CYCLES = 33_554_432
) (
    input  wire clk_source,
    input  wire clk_destination,
    input  wire reset_n,
    input  wire trigger,

    output wire reset_active_destination,
    output wire start_active_destination
);
  localparam integer COUNTER_WIDTH = $clog2(START_CYCLES + 1);

  initial begin
    if (RESET_CYCLES < 1) begin
      $error("apf_console_setup requires RESET_CYCLES >= 1");
    end
    if (START_CYCLES <= RESET_CYCLES) begin
      $error("apf_console_setup requires START_CYCLES > RESET_CYCLES");
    end
  end

  reg [COUNTER_WIDTH-1:0] reset_counter_source = {COUNTER_WIDTH{1'b0}};
  reg [COUNTER_WIDTH-1:0] start_counter_source = {COUNTER_WIDTH{1'b0}};

  wire reset_active_source = reset_counter_source != 0;
  wire start_active_source = start_counter_source != 0;

  always @(posedge clk_source or negedge reset_n) begin
    if (!reset_n) begin
      reset_counter_source <= {COUNTER_WIDTH{1'b0}};
      start_counter_source <= {COUNTER_WIDTH{1'b0}};
    end else if (trigger) begin
      reset_counter_source <= RESET_CYCLES[COUNTER_WIDTH-1:0];
      start_counter_source <= START_CYCLES[COUNTER_WIDTH-1:0];
    end else begin
      if (reset_active_source) reset_counter_source <= reset_counter_source - 1'b1;
      if (start_active_source) start_counter_source <= start_counter_source - 1'b1;
    end
  end

  (* ASYNC_REG = "TRUE",
     altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *)
  reg [2:0] reset_sync_destination = 3'b000;
  (* ASYNC_REG = "TRUE",
     altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *)
  reg [2:0] start_sync_destination = 3'b000;

  always @(posedge clk_destination or negedge reset_n) begin
    if (!reset_n) begin
      reset_sync_destination <= 3'b000;
      start_sync_destination <= 3'b000;
    end else begin
      reset_sync_destination <= {reset_sync_destination[1:0], reset_active_source};
      start_sync_destination <= {start_sync_destination[1:0], start_active_source};
    end
  end

  assign reset_active_destination = reset_sync_destination[2];
  assign start_active_destination = start_sync_destination[2];
endmodule
