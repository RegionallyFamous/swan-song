`timescale 1ns/1ps

// Atomic broadcast CDC for the APF cartridge byte count.
//
// The accepted 0082 length determines both the prefix inserted for a compact
// non-power-of-two image and the mapper aperture exposed after loading.  Keep
// that multi-bit value frozen until both consuming clock domains have captured
// the same snapshot; synchronizing its bits independently could create a
// transient but valid-looking aperture.
module apf_rom_plan_cdc (
    input  wire        reset_n,

    input  wire        clk_74a,
    input  wire [24:0] rom_size_74a,
    input  wire        commit_74a,
    output wire        busy_74a,
    output reg         rejected_74a,

    input  wire        clk_mem,
    output reg  [24:0] rom_size_mem,
    output reg         valid_mem,

    input  wire        clk_sys,
    output reg  [24:0] rom_size_sys,
    output reg         valid_sys
);
  (* ASYNC_REG = "TRUE" *) reg [1:0] source_reset_sync = 2'b00;
  (* ASYNC_REG = "TRUE" *) reg [1:0] memory_reset_sync = 2'b00;
  (* ASYNC_REG = "TRUE" *) reg [1:0] system_reset_sync = 2'b00;
  wire source_reset_n = source_reset_sync[1];
  wire memory_reset_n = memory_reset_sync[1];
  wire system_reset_n = system_reset_sync[1];

  always @(posedge clk_74a or negedge reset_n) begin
    if (!reset_n) source_reset_sync <= 2'b00;
    else source_reset_sync <= {source_reset_sync[0], 1'b1};
  end

  always @(posedge clk_mem or negedge reset_n) begin
    if (!reset_n) memory_reset_sync <= 2'b00;
    else memory_reset_sync <= {memory_reset_sync[0], 1'b1};
  end

  always @(posedge clk_sys or negedge reset_n) begin
    if (!reset_n) system_reset_sync <= 2'b00;
    else system_reset_sync <= {system_reset_sync[0], 1'b1};
  end

  reg [24:0] rom_size_hold;
  reg request_toggle;
  reg commit_previous;

  (* ASYNC_REG = "TRUE" *) reg acknowledge_mem_meta;
  (* ASYNC_REG = "TRUE" *) reg acknowledge_mem_sync;
  (* ASYNC_REG = "TRUE" *) reg acknowledge_sys_meta;
  (* ASYNC_REG = "TRUE" *) reg acknowledge_sys_sync;

  reg acknowledge_mem;
  (* ASYNC_REG = "TRUE" *) reg request_mem_meta;
  (* ASYNC_REG = "TRUE" *) reg request_mem_sync;
  reg request_mem_seen;

  reg acknowledge_sys;
  (* ASYNC_REG = "TRUE" *) reg request_sys_meta;
  (* ASYNC_REG = "TRUE" *) reg request_sys_sync;
  reg request_sys_seen;

  assign busy_74a = (request_toggle != acknowledge_mem_sync) ||
                    (request_toggle != acknowledge_sys_sync);

  always @(posedge clk_74a or negedge source_reset_n) begin
    if (!source_reset_n) begin
      rom_size_hold <= 25'd0;
      request_toggle <= 1'b0;
      commit_previous <= 1'b0;
      acknowledge_mem_meta <= 1'b0;
      acknowledge_mem_sync <= 1'b0;
      acknowledge_sys_meta <= 1'b0;
      acknowledge_sys_sync <= 1'b0;
      rejected_74a <= 1'b0;
    end else begin
      acknowledge_mem_meta <= acknowledge_mem;
      acknowledge_mem_sync <= acknowledge_mem_meta;
      acknowledge_sys_meta <= acknowledge_sys;
      acknowledge_sys_sync <= acknowledge_sys_meta;
      commit_previous <= commit_74a;
      rejected_74a <= 1'b0;

      if (commit_74a && !commit_previous) begin
        if (!busy_74a) begin
          rom_size_hold <= rom_size_74a;
          request_toggle <= ~request_toggle;
        end else begin
          rejected_74a <= 1'b1;
        end
      end
    end
  end

  always @(posedge clk_mem or negedge memory_reset_n) begin
    if (!memory_reset_n) begin
      acknowledge_mem <= 1'b0;
      request_mem_meta <= 1'b0;
      request_mem_sync <= 1'b0;
      request_mem_seen <= 1'b0;
      rom_size_mem <= 25'd0;
      valid_mem <= 1'b0;
    end else begin
      request_mem_meta <= request_toggle;
      request_mem_sync <= request_mem_meta;
      valid_mem <= 1'b0;
      if (request_mem_sync != request_mem_seen) begin
        rom_size_mem <= rom_size_hold;
        valid_mem <= 1'b1;
        request_mem_seen <= request_mem_sync;
        acknowledge_mem <= request_mem_sync;
      end
    end
  end

  always @(posedge clk_sys or negedge system_reset_n) begin
    if (!system_reset_n) begin
      acknowledge_sys <= 1'b0;
      request_sys_meta <= 1'b0;
      request_sys_sync <= 1'b0;
      request_sys_seen <= 1'b0;
      rom_size_sys <= 25'd0;
      valid_sys <= 1'b0;
    end else begin
      request_sys_meta <= request_toggle;
      request_sys_sync <= request_sys_meta;
      valid_sys <= 1'b0;
      if (request_sys_sync != request_sys_seen) begin
        rom_size_sys <= rom_size_hold;
        valid_sys <= 1'b1;
        request_sys_seen <= request_sys_sync;
        acknowledge_sys <= request_sys_sync;
      end
    end
  end
endmodule
