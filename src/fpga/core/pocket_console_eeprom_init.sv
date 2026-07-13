`timescale 1ns/1ps

// Deterministic factory image for the two console-owned EEPROM banks.
//
// WonderSwan and WonderSwan Color console EEPROM is global machine state, not
// cartridge save data.  Re-arm only when a new title begins loading.  Host
// Reset Enter/Exit and the in-core reset action are deliberately absent from
// this interface, so neither can erase owner/settings data during a session.
module pocket_console_eeprom_init (
    input  wire        clk,
    input  wire        cart_download,

    output wire        clearing,
    output wire        write_en,
    // Physical backing layout: Color words 0..1023 in bank 0, followed by
    // mono words 0..63 in bank 1.  The remaining bank-1 words are unused.
    output wire [10:0] physical_word_addr,
    output wire [15:0] write_data,
    output reg         initialization_resolved = 1'b0
);

  localparam [10:0] LAST_FACTORY_WORD = 11'd1087;

  reg active = 1'b1;
  reg [10:0] word_addr = 11'd0;

  function automatic [15:0] factory_word(input [10:0] address);
    begin
      factory_word = 16'h0000;
      if (!address[10]) begin
        // WonderSwan Color bank. Preserve the deterministic open-core factory
        // identity used by the original controller initialization.
        case (address[9:0])
          10'h030: factory_word = 16'h1921;
          10'h031: factory_word = 16'h0E18;
          10'h032: factory_word = 16'h1C0F;
          10'h033: factory_word = 16'h211D;
          10'h034: factory_word = 16'h180B;
          10'h035: factory_word = 16'h190D;
          10'h036: factory_word = 16'h1916;
          10'h037: factory_word = 16'h001C;
          10'h03B: factory_word = 16'h0101;
          10'h03C: factory_word = 16'h0027;
          10'h03E: factory_word = 16'h0001;
          10'h040: factory_word = 16'h0101;
          10'h041: factory_word = 16'h0327;
          default: factory_word = 16'h0000;
        endcase
      end else begin
        // Original monochrome WonderSwan bank.
        case (address[9:0])
          10'h030: factory_word = 16'h1921;
          10'h031: factory_word = 16'h0E18;
          10'h032: factory_word = 16'h1C0F;
          10'h033: factory_word = 16'h211D;
          10'h034: factory_word = 16'h180B;
          10'h03B: factory_word = 16'h0001;
          10'h03C: factory_word = 16'h0024;
          10'h03E: factory_word = 16'h0001;
          default: factory_word = 16'h0000;
        endcase
      end
    end
  endfunction

  assign clearing = active;
  assign write_en = active && !cart_download;
  assign physical_word_addr = word_addr;
  assign write_data = factory_word(word_addr);

  always @(posedge clk) begin
    if (cart_download) begin
      active <= 1'b1;
      word_addr <= 11'd0;
      initialization_resolved <= 1'b0;
    end else if (active) begin
      if (word_addr == LAST_FACTORY_WORD) begin
        active <= 1'b0;
        initialization_resolved <= 1'b1;
      end else begin
        word_addr <= word_addr + 11'd1;
      end
    end
  end

endmodule
