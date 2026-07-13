#
# user core constraints
#
# put your clock groups in here as well as any net assignments
#

set_clock_groups -asynchronous \
 -group { bridge_spiclk } \
 -group { clk_74a } \
 -group { clk_74b } \
 -group { ic|mp1|mf_pllbase_inst|altera_pll_i|general[0].gpll~PLL_OUTPUT_COUNTER|divclk \
          ic|mp1|mf_pllbase_inst|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk } \
 -group { ic|mp1|mf_pllbase_inst|altera_pll_i|general[2].gpll~PLL_OUTPUT_COUNTER|divclk } \
 -group { ic|mp1|mf_pllbase_inst|altera_pll_i|general[3].gpll~PLL_OUTPUT_COUNTER|divclk } 

# Footer save metadata is a bundled-data CDC. metadata_hold is frozen before
# request_toggle enters the two-flop request_meta/request_sync chain and stays
# frozen until the acknowledgement returns. Keep the clocks asynchronous, but
# independently bound this exact 21-bit payload so it settles within one clk_74a
# period and its bits cannot spread across destination capture cycles.
set save_metadata_source_registers [get_registers -nowarn -no_duplicates \
  {ic|save_metadata_command_cdc|metadata_hold[*]}]
set save_metadata_destination_registers [get_registers -nowarn -no_duplicates \
  {ic|save_metadata_command_cdc|save_size_bytes_74a[*] \
   ic|save_metadata_command_cdc|has_rtc_74a}]

# Fail closed if synthesis changes the intended hierarchy. An empty collection
# would otherwise leave this safety-critical bundled bus unconstrained.
if {[get_collection_size $save_metadata_source_registers] != 21} {
  error "save metadata CDC constraint expected 21 metadata_hold registers"
}
if {[get_collection_size $save_metadata_destination_registers] != 21} {
  error "save metadata CDC constraint expected 21 destination registers"
}

set_net_delay -max \
  -get_value_from_clock_period dst_clock_period \
  -value_multiplier 1.0 \
  -from $save_metadata_source_registers \
  -to $save_metadata_destination_registers
set_max_skew \
  -get_skew_value_from_clock_period min_clock_period \
  -skew_value_multiplier 1.0 \
  -from $save_metadata_source_registers \
  -to $save_metadata_destination_registers

derive_clock_uncertainty
