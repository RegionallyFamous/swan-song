library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

-- Focused clean-room regression for the central WonderSwan SoC controls.
-- The reference URLs and behavioral disagreements are documented in the DUT.
entity soc_control_tb is
end entity;

architecture tb of soc_control_tb is
   signal clk                  : std_logic := '0';
   signal reset                : std_logic := '0';
   signal is_color_model       : std_logic := '0';
   signal reg_addr             : std_logic_vector(7 downto 0) := (others => '0');
   signal reg_write            : std_logic := '0';
   signal reg_data_in          : std_logic_vector(7 downto 0) := (others => '0');
   signal reg_data_out         : std_logic_vector(7 downto 0);
   signal reg_read_mapped      : std_logic;
   signal reg_write_mapped     : std_logic;
   signal port_60_mapped       : std_logic;
   signal state_load           : std_logic := '0';
   signal state_data_in        : std_logic_vector(15 downto 0) := (others => '0');
   signal state_data_out       : std_logic_vector(15 downto 0);
   signal boot_rom_locked      : std_logic;
   signal cartridge_rom_word   : std_logic;
   signal cartridge_rom_slow   : std_logic;
   signal color_enabled        : std_logic;
   signal video_mode           : std_logic_vector(2 downto 0);
   signal video_4bpp           : std_logic;
   signal video_4bpp_packed    : std_logic;
   signal cartridge_sram_slow  : std_logic;
   signal cartridge_io_slow    : std_logic;
   signal cartridge_clock_fast : std_logic;
begin
   clk <= not clk after 5 ns;

   dut : entity work.soc_control
      port map (
         clk => clk,
         reset => reset,
         is_color_model => is_color_model,
         reg_addr => reg_addr,
         reg_write => reg_write,
         reg_data_in => reg_data_in,
         reg_data_out => reg_data_out,
         reg_read_mapped => reg_read_mapped,
         reg_write_mapped => reg_write_mapped,
         port_60_mapped => port_60_mapped,
         state_load => state_load,
         state_data_in => state_data_in,
         state_data_out => state_data_out,
         boot_rom_locked => boot_rom_locked,
         cartridge_rom_word => cartridge_rom_word,
         cartridge_rom_slow => cartridge_rom_slow,
         color_enabled => color_enabled,
         video_mode => video_mode,
         video_4bpp => video_4bpp,
         video_4bpp_packed => video_4bpp_packed,
         cartridge_sram_slow => cartridge_sram_slow,
         cartridge_io_slow => cartridge_io_slow,
         cartridge_clock_fast => cartridge_clock_fast
      );

   stimulus : process
      procedure tick is
      begin
         wait until rising_edge(clk);
         wait for 1 ns;
      end procedure;

      procedure write_port(address : natural; value : natural) is
      begin
         reg_addr <= std_logic_vector(to_unsigned(address, reg_addr'length));
         reg_data_in <= std_logic_vector(to_unsigned(value, reg_data_in'length));
         reg_write <= '1';
         tick;
         reg_write <= '0';
      end procedure;

      procedure expect_port(
         address      : natural;
         expected     : natural;
         mapped       : std_logic;
         message_text : string
      ) is
      begin
         reg_addr <= std_logic_vector(to_unsigned(address, reg_addr'length));
         wait for 1 ns;
         assert reg_data_out = std_logic_vector(to_unsigned(expected, reg_data_out'length))
            report message_text & ": expected data " &
                   to_hstring(std_logic_vector(to_unsigned(expected, reg_data_out'length))) &
                   ", got " & to_hstring(reg_data_out)
            severity failure;
         assert reg_read_mapped = mapped and reg_write_mapped = mapped
            report message_text & ": mapped flags mismatch" severity failure;
      end procedure;

      procedure expect_exports(
         lock_value       : std_logic;
         rom_word_value   : std_logic;
         rom_slow_value   : std_logic;
         color_value      : std_logic;
         mode_value       : std_logic_vector(2 downto 0);
         sram_slow_value  : std_logic;
         io_slow_value    : std_logic;
         clock_fast_value : std_logic;
         message_text     : string
      ) is
      begin
         assert boot_rom_locked = lock_value and
                cartridge_rom_word = rom_word_value and
                cartridge_rom_slow = rom_slow_value and
                color_enabled = color_value and
                video_mode = mode_value and
                video_4bpp = mode_value(1) and
                video_4bpp_packed = mode_value(0) and
                cartridge_sram_slow = sram_slow_value and
                cartridge_io_slow = io_slow_value and
                cartridge_clock_fast = clock_fast_value
            report message_text & ": export mismatch" severity failure;
      end procedure;

      procedure load_state(value : std_logic_vector(15 downto 0)) is
      begin
         state_data_in <= value;
         state_load <= '1';
         tick;
         state_load <= '0';
      end procedure;
   begin
      -- Deterministic monochrome reset: $A0 exists, $60 is explicitly
      -- unmapped so the future bus owner can supply open bus.
      reset <= '1';
      tick;
      reset <= '0';
      expect_port(16#A0#, 16#80#, '1', "mono reset A0");
      expect_port(16#60#, 16#00#, '0', "mono open-bus handoff");
      assert port_60_mapped = '0' report "mono $60 was mapped" severity failure;
      assert state_data_out = x"0000" report "mono reset state was not zero" severity failure;
      expect_exports('0', '0', '0', '0', "000", '0', '0', '0', "mono reset");

      -- Mono writes to $60 are ignored, including all documented Color bits.
      write_port(16#60#, 16#FF#);
      expect_port(16#60#, 16#00#, '0', "mono ignored 60 write");
      assert state_data_out(15 downto 8) = x"00"
         report "mono $60 write created hidden state" severity failure;

      -- $A0 masks reserved bits.  Only boot lock is sticky; ROM width and ROM
      -- wait are ordinary replacement fields.
      write_port(16#A0#, 16#FF#);
      expect_port(16#A0#, 16#8D#, '1', "mono A0 mask");
      expect_exports('1', '1', '1', '0', "000", '0', '0', '0', "mono A0 set");
      write_port(16#A0#, 16#00#);
      expect_port(16#A0#, 16#81#, '1', "A0 sticky lock replace controls");
      expect_exports('1', '0', '0', '0', "000", '0', '0', '0', "A0 replace controls");
      write_port(16#A0#, 16#04#);
      expect_port(16#A0#, 16#85#, '1', "A0 ROM width replacement");

      reset <= '1';
      tick;
      reset <= '0';
      expect_port(16#A0#, 16#80#, '1', "reset clears A0 lock");

      -- Color $60 uses exactly mask EBh.  A second write replaces every
      -- implemented field, including the video-mode bits; it is not sticky.
      is_color_model <= '1';
      reset <= '1';
      tick;
      reset <= '0';
      expect_port(16#A0#, 16#82#, '1', "color reset A0");
      expect_port(16#60#, 16#0A#, '1', "color reset 60");
      assert port_60_mapped = '1' report "color $60 was not mapped" severity failure;
      assert state_data_out = x"0A00"
         report "color reset state did not preserve physical $60 defaults" severity failure;
      expect_exports('0', '0', '0', '0', "000", '1', '1', '0', "color reset");

      write_port(16#60#, 16#FF#);
      expect_port(16#60#, 16#EB#, '1', "color 60 mask");
      expect_exports('0', '0', '0', '1', "111", '1', '1', '1', "color all fields");

      -- The stored/read byte preserves every implemented raw bit, but the
      -- video-facing exports enforce the documented dependency chain:
      -- Color -> 4bpp -> packed 4bpp.  Invalid raw combinations therefore
      -- collapse to the nearest valid effective mode.
      write_port(16#60#, 16#20#);
      expect_port(16#60#, 16#20#, '1', "color 60 replacement");
      expect_exports('0', '0', '0', '0', "000", '0', '0', '0', "packed without color/4bpp");
      write_port(16#60#, 16#40#);
      expect_port(16#60#, 16#40#, '1', "raw 4bpp without color");
      expect_exports('0', '0', '0', '0', "000", '0', '0', '0', "4bpp without color");
      write_port(16#60#, 16#60#);
      expect_port(16#60#, 16#60#, '1', "raw packed 4bpp without color");
      expect_exports('0', '0', '0', '0', "000", '0', '0', '0', "packed 4bpp without color");
      write_port(16#60#, 16#80#);
      expect_port(16#60#, 16#80#, '1', "raw Color 2bpp");
      expect_exports('0', '0', '0', '1', "100", '0', '0', '0', "effective Color 2bpp");
      write_port(16#60#, 16#A0#);
      expect_port(16#60#, 16#A0#, '1', "raw packed request without 4bpp");
      expect_exports('0', '0', '0', '1', "100", '0', '0', '0', "packed request collapses to Color 2bpp");
      write_port(16#60#, 16#C0#);
      expect_port(16#60#, 16#C0#, '1', "raw Color 4bpp planar");
      expect_exports('0', '0', '0', '1', "110", '0', '0', '0', "effective Color 4bpp planar");
      write_port(16#60#, 16#E0#);
      expect_port(16#60#, 16#E0#, '1', "raw Color 4bpp packed");
      expect_exports('0', '0', '0', '1', "111", '0', '0', '0', "effective Color 4bpp packed");
      write_port(16#60#, 16#14#);
      expect_port(16#60#, 16#00#, '1', "color reserved-bit mask");
      write_port(16#60#, 16#09#);
      expect_port(16#60#, 16#09#, '1', "color bus-control replacement");
      expect_exports('0', '0', '0', '0', "000", '0', '1', '1', "color bus controls");

      -- Color identification is read-only.  A0 keeps bit 0 sticky while bits
      -- 2/3 replace exactly just as on monochrome hardware.
      write_port(16#A0#, 16#0D#);
      expect_port(16#A0#, 16#8F#, '1', "color A0 set");
      write_port(16#A0#, 16#00#);
      expect_port(16#A0#, 16#83#, '1', "color A0 sticky lock");

      -- Exact restore may clear the sticky boot lock, masks reserved state
      -- bits, and has priority over a simultaneous software write.
      reg_addr <= x"A0";
      reg_data_in <= x"0D";
      reg_write <= '1';
      state_data_in <= x"6B0C";
      state_load <= '1';
      tick;
      reg_write <= '0';
      state_load <= '0';
      expect_port(16#A0#, 16#8E#, '1', "state load clears sticky lock");
      expect_port(16#60#, 16#6B#, '1', "state load color fields");
      assert state_data_out = x"6B0C" report "exact state round trip mismatch" severity failure;

      load_state(x"FFFF");
      expect_port(16#A0#, 16#8F#, '1', "state A0 mask");
      expect_port(16#60#, 16#EB#, '1', "state 60 mask");
      assert state_data_out = x"EB0D" report "state masks were not canonical" severity failure;

      -- The production save loader does not use state_load for ordinary
      -- registers.  It pulses RegBus_rst, then replays the 256-byte register
      -- image through normal writes.  This sequence must be able to restore a
      -- clear boot lock even when the live state was previously locked.
      reset <= '1';
      tick;
      reset <= '0';
      write_port(16#A0#, 16#0C#);
      write_port(16#60#, 16#A3#);
      expect_port(16#A0#, 16#8E#, '1', "register-image A0 restore");
      expect_port(16#60#, 16#A3#, '1', "register-image 60 restore");
      assert state_data_out = x"A30C"
         report "register-image restore did not recreate canonical state" severity failure;

      -- Reset is stronger than either restore interface.  In production this
      -- is why the controller reset must follow RegBus_rst specifically: the
      -- general core reset is also pulsed after the register replay finishes.
      reg_addr <= x"A0";
      reg_data_in <= x"0D";
      reg_write <= '1';
      state_data_in <= x"EB0D";
      state_load <= '1';
      reset <= '1';
      tick;
      reg_write <= '0';
      state_load <= '0';
      reset <= '0';
      expect_port(16#A0#, 16#82#, '1', "reset priority over A0 restore");
      expect_port(16#60#, 16#0A#, '1', "reset priority over 60 restore");
      assert state_data_out = x"0A00"
         report "reset did not override simultaneous restore/write" severity failure;
      expect_exports('0', '0', '0', '0', "000", '1', '1', '0', "color reset priority");

      -- The model input is a physical/read-only property.  Its $A0 bit and
      -- Color-only mapping change without mutating the writable A0 state.
      write_port(16#A0#, 16#0C#);
      write_port(16#60#, 16#A3#);
      is_color_model <= '0';
      expect_port(16#A0#, 16#8C#, '1', "model bit follows monochrome input");
      expect_port(16#60#, 16#00#, '0', "model switch gates 60 immediately");
      expect_exports('0', '1', '1', '0', "000", '0', '0', '0', "model switch gates exports");
      tick;
      assert state_data_out = x"000C"
         report "monochrome clock retained hidden Color state" severity failure;

      -- Loading the same image as mono preserves only writable $A0 state and
      -- leaves $60 unmapped/zero.  Non-owned addresses also drive zero and
      -- report unmapped, making wired-OR integration deterministic.
      load_state(x"EB0D");
      expect_port(16#A0#, 16#8D#, '1', "mono state A0");
      expect_port(16#60#, 16#00#, '0', "mono state 60 handoff");
      assert state_data_out = x"000D" report "mono restore retained Color state" severity failure;
      expect_port(16#5F#, 16#00#, '0', "unowned address below 60");
      expect_port(16#61#, 16#00#, '0', "unowned address above 60");

      report "PASS soc_control $A0 controls, physical Color $60 reset, raw $60 storage, normalized video modes/prerequisites, mono handoff, reset priority, register-image replay, and exact state"
         severity note;
      std.env.stop;
      wait;
   end process;
end architecture;
