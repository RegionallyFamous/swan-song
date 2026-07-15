`default_nettype none

// Pocket reads interact variables once per frame and before restoring
// persistent values. Return the exact settings held in the host bridge clock
// domain so the menu observes the requested configuration, not a delayed CDC
// snapshot or the ROM-footer-resolved active system model.
module apf_interact_readback (
    input  wire [31:0] bridge_addr,
    input  wire [12:0] settings_source,
    output reg         hit,
    output reg  [31:0] data
);

  always @(*) begin
    hit = 1'b1;
    data = 32'd0;

    case (bridge_addr)
      32'h00000100: data = {30'd0, settings_source[12:11]};
      32'h00000110: data = {31'd0, settings_source[10]};
      32'h00000200: data = {31'd0, settings_source[9]};
      32'h00000204: data = {30'd0, settings_source[8:7]};
      32'h00000208: data = {30'd0, settings_source[6:5]};
      32'h0000020c: data = {31'd0, settings_source[2]};
      32'h00000210: data = {31'd0, settings_source[1]};
      32'h00000214: data = {30'd0, settings_source[4:3]};
      32'h00000300: data = {31'd0, settings_source[0]};
      default: begin
        hit = 1'b0;
        data = 32'd0;
      end
    endcase
  end

endmodule

`default_nettype wire
