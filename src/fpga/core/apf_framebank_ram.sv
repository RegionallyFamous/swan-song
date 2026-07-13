`timescale 1ns/1ps

// One RGB444 WonderSwan framebuffer, shaped for Cyclone V M10K aspect ratios.
//
// A monolithic 32,256 x 12 RAM can be mapped as twelve deep one-bit slices,
// wasting the parity capacity in each M10K.  Splitting the pixel into 10-bit
// and 2-bit memories permits the native 2K x 5 and 4K x 2 configurations:
// 32 M10Ks for pixel[11:2] plus 8 M10Ks for pixel[1:0].  The split is bit exact
// and retains the original synchronous, one-clock read latency.
//
// Buffered operation guarantees that the writer never addresses a bank owned
// by scanout.  Direct mode deliberately permits tearing, so mixed-port
// read-during-write data is not part of the functional contract.  Declaring
// that don't-care behavior prevents Quartus from inserting bypass logic.
module apf_framebank_ram #(
    parameter integer FRAME_PIXELS = 32256,
    parameter integer ADDRESS_WIDTH = 15
) (
    input  wire                     clk,
    input  wire                     write_enable,
    input  wire [ADDRESS_WIDTH-1:0] write_address,
    input  wire [11:0]              write_data,
    input  wire [ADDRESS_WIDTH-1:0] read_address,
    output wire [11:0]              read_data
);
  (* ramstyle = "M10K, no_rw_check", max_depth = 2048 *)
  reg [9:0] pixels_hi [0:FRAME_PIXELS-1];
  (* ramstyle = "M10K, no_rw_check", max_depth = 4096 *)
  reg [1:0] pixels_lo [0:FRAME_PIXELS-1];

  reg [9:0] read_hi;
  reg [1:0] read_lo;

  assign read_data = {read_hi, read_lo};

  always @(posedge clk) begin
    if (write_enable) begin
      pixels_hi[write_address] <= write_data[11:2];
      pixels_lo[write_address] <= write_data[1:0];
    end

    read_hi <= pixels_hi[read_address];
    read_lo <= pixels_lo[read_address];
  end
endmodule
