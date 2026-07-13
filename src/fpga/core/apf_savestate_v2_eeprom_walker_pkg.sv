`default_nettype none

// Stable result codes for the isolated Memories v2 EEPROM backing walker.
// They are intentionally separate from the serialized ABI: these values are
// transaction diagnostics and never enter a save-state image.
package apf_savestate_v2_eeprom_walker_pkg;
  localparam logic [3:0] EEPROM_WALK_FAILURE_NONE          = 4'd0;
  localparam logic [3:0] EEPROM_WALK_FAILURE_CONFIG        = 4'd1;
  localparam logic [3:0] EEPROM_WALK_FAILURE_ABORT         = 4'd2;
  localparam logic [3:0] EEPROM_WALK_FAILURE_STAGE_BACKEND = 4'd3;
  localparam logic [3:0] EEPROM_WALK_FAILURE_MEMORY_BACKEND = 4'd4;
  localparam logic [3:0] EEPROM_WALK_FAILURE_PADDING       = 4'd5;
  localparam logic [3:0] EEPROM_WALK_FAILURE_STAGE_TIMEOUT = 4'd6;
  localparam logic [3:0] EEPROM_WALK_FAILURE_MEMORY_TIMEOUT = 4'd7;
  localparam logic [3:0] EEPROM_WALK_FAILURE_INTERNAL      = 4'd8;
endpackage

`default_nettype wire
