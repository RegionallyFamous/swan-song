`timescale 1ns/1ps

// PocketOS menu-focus level crossing.
//
// 0x00B0 is held in clk_74a by the APF command handler for as long as the OS
// owns focus.  It is a single control bit, so a dedicated three-register level
// synchronizer is sufficient; unlike physical input ownership, it does not
// need a bundled-data handshake.  Keeping this crossing separate from the
// neutral-rearm path is essential: menu exit must resume the console even when
// physical controls remain blocked waiting for a fresh neutral PAD sample.
module apf_menu_focus_cdc (
    input  wire clk_destination,
    input  wire reset_n_async,
    input  wire menu_focus_source,
    output wire menu_focus_destination
);

  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *)
  reg menu_focus_meta = 1'b0;
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *)
  reg menu_focus_sync = 1'b0;
  (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED; -name PRESERVE_REGISTER ON" *)
  reg menu_focus_level = 1'b0;

  assign menu_focus_destination = menu_focus_level;

  always @(posedge clk_destination or negedge reset_n_async) begin
    if (!reset_n_async) begin
      menu_focus_meta  <= 1'b0;
      menu_focus_sync  <= 1'b0;
      menu_focus_level <= 1'b0;
    end else begin
      menu_focus_meta  <= menu_focus_source;
      menu_focus_sync  <= menu_focus_meta;
      menu_focus_level <= menu_focus_sync;
    end
  end

endmodule
