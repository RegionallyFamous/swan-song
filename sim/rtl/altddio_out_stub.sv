`timescale 1ns/1ps

// Simulation-only behavioral stand-in for the Intel clock-output primitive
// instantiated by rtl/sdram.sv. The SDRAM controller tests command/data timing;
// they do not depend on vendor-specific DDR implementation details.
module altddio_out #(
    parameter extend_oe_disable = "OFF",
    parameter intended_device_family = "Cyclone V",
    parameter invert_output = "OFF",
    parameter lpm_hint = "UNUSED",
    parameter lpm_type = "altddio_out",
    parameter oe_reg = "UNREGISTERED",
    parameter power_up_high = "OFF",
    parameter width = 1
) (
    input  wire [width-1:0] datain_h,
    input  wire [width-1:0] datain_l,
    input  wire             outclock,
    output wire [width-1:0] dataout,
    input  wire             aclr,
    input  wire             aset,
    input  wire             oe,
    input  wire             outclocken,
    input  wire             sclr,
    input  wire             sset
);
  wire [width-1:0] ddr_value = outclock ? datain_h : datain_l;
  assign dataout = oe && outclocken ? ddr_value : {width{1'bz}};

  // Keep the full vendor interface represented without giving the reset pins
  // behavior the hardware primitive does not use in this design.
  wire unused = &{1'b0, aclr, aset, sclr, sset, extend_oe_disable[0],
                  intended_device_family[0], invert_output[0], lpm_hint[0],
                  lpm_type[0], oe_reg[0], power_up_high[0]};
endmodule
