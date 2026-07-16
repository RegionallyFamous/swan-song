architecture chip32.vm
output "chip32.bin", create

// we will put data into here that we're working on.  It's the last 1K of the 8K chip32 memory
constant rambuf = 0x1b00

constant rom_dataslot = 0
constant save_dataslot = 11
constant mono_eeprom_dataslot = 12
constant color_eeprom_dataslot = 13

constant cart_download_addr = 0x0
constant is_color_cart_addr = 0x4

constant save_download_addr = 0x10
constant rom_validation_status_addr = 0x14
// This is an instruction-count guard, not a wall-clock duration. Analogue does
// not publish the VM rate or its firmware crash-cycle limit, so Pocket QA must
// calibrate the visible timeout path on the target firmware.
constant rom_validation_timeout = 0x00100000

// Host init command
constant host_init = 0x4002

macro load_asset(variable ioctl_download_addr, variable dataslot_id, variable error_msg) {
  ld r1,#ioctl_download_addr // Set address for write
  ld r2,#1 // Downloading start
  pmpw r1,r2 // Write ioctl_download = 1

  ld r3,#dataslot_id
  ld r14,#error_msg
  loadf r3 // Load asset

  if error_msg != 0 {
    // Only throw error if an error msg provided
    jp nz,print_error_and_exit
  }

  // ld r1,#ioctl_download_addr // Set address for write
  ld r2,#0 // Downloading end
  pmpw r1,r2 // Write ioctl_download = 0
}

macro load_rom_asset(variable ioctl_download_addr, variable dataslot_id) {
  ld r1,#ioctl_download_addr
  ld r2,#1
  pmpw r1,r2

  ld r3,#dataslot_id
  ld r14,#rom_err_msg
  loadf r3
  jp nz,print_error_and_exit

  // Prefix fill is interleaved before EOF; validation/status CDC completes
  // after the final LOADF word.
  ld r1,#ioctl_download_addr
  ld r2,#0
  pmpw r1,r2
  ld r1,#rom_validation_status_addr
  ld r4,#rom_validation_timeout

rom_validation_poll:
  pmpr r1,r2
  cmp r2,#1
  jp z,rom_validation_ready
  cmp r2,#2
  jp z,rom_validation_rejected
  sub r4,#1
  jp nz,rom_validation_poll
  ld r14,#rom_validation_timeout_msg
  jp print_error_and_exit

rom_validation_rejected:
  ld r14,#rom_validation_rejected_msg
  jp print_error_and_exit

rom_validation_ready:
}

// Error vector (0x0)
jp error_handler

// Init vector (0x2)
// Choose core
ld r0,#0
core r0

ld r1,#rom_dataslot // populate data slot
ld r2,#rambuf // get ram buf position
getext r1,r2
ld r1,#ext_wsc
test r1,r2
jp z,set_wsc // Set wsc

dont_set_wsc:
ld r3,#0
jp start_load

set_wsc:
ld r3,#1

start_load:
ld r1,#is_color_cart_addr
pmpw r1,r3 // Write is_color_cart = r3

// Load cart
load_rom_asset(cart_download_addr, rom_dataslot)

// Load save
// Console EEPROM is fixed-name, core-specific machine state. Load both models
// before the cartridge save and before HOST 4002 releases execution.
load_asset(save_download_addr, mono_eeprom_dataslot, 0)
load_asset(save_download_addr, color_eeprom_dataslot, 0)

// Load per-title cartridge save through its independent slot/window.
load_asset(save_download_addr, save_dataslot, 0)

// Start core
ld r0,#host_init
host r0,r0

exit 0

// Error handling
error_handler:
ld r14,#test_err_msg

print_error_and_exit:
printf r14
exit 1

ext_wsc:
db "WSC",0

test_err_msg:
db "Error",0

rom_err_msg:
db "Could not load ROM",0

rom_validation_rejected_msg:
db "ROM footer/checksum rejected",0

rom_validation_timeout_msg:
db "ROM validation timed out",0
