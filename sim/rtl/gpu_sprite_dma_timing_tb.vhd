library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

use work.pRegisterBus.all;
use work.pBus_savestates.all;

-- Clean-room sprite-table timing regression. No cartridge, firmware,
-- commercial data, or title-derived bytes are used.
--
-- Reference contract:
--   WSdev Display/Sprites documents the 512-byte sprite table:
--   https://ws.nesdev.org/w/index.php?title=Display/Sprites&oldid=507
--   Mesen2 b9fa69dd ProcessSpriteCopy latches count at cycle 0 and copies one
--   16-bit word per cycle with a wrapping 9-bit table offset. It reads base
--   and first live on each cycle:
--   https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsPpu.cpp#L299-L310
--   ares 449b9371 snapshots count, base, and first on entry to its 256-cycle
--   line-144 OAM sync. This RTL deliberately uses that all-three boundary:
--   https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/sprite.cpp#L1-L22
entity gpu_sprite_dma_timing_tb is
end entity;

architecture tb of gpu_sprite_dma_timing_tb is
   signal clk       : std_logic := '0';
   signal ce        : std_logic := '0';
   signal reset     : std_logic := '0';

   signal reg_din   : std_logic_vector(BUS_buswidth - 1 downto 0) := (others => '0');
   signal reg_adr   : std_logic_vector(BUS_busadr - 1 downto 0) := (others => '0');
   signal reg_wren  : std_logic := '0';
   signal reg_rst   : std_logic := '0';

   signal ss_din    : std_logic_vector(SSBUS_buswidth - 1 downto 0) := (others => '0');
   signal ss_adr    : std_logic_vector(SSBUS_busadr - 1 downto 0) := (others => '0');
   signal ss_wren   : std_logic := '0';
   signal ss_rst    : std_logic := '0';
   signal ss_dout   : std_logic_vector(SSBUS_buswidth - 1 downto 0);

   signal ram_addr       : std_logic_vector(15 downto 0);
   signal ram_dataread   : std_logic_vector(15 downto 0) := (others => '0');
   signal ram_resp_addr  : std_logic_vector(15 downto 0) := (others => '0');

   signal vtime          : std_logic_vector(7 downto 0);
   signal fetch_valid    : std_logic;
   signal fetch_role     : std_logic_vector(2 downto 0);
   signal sprite_row_valid       : std_logic;
   signal sprite_row_table_addr  : std_logic_vector(15 downto 0);
   signal sprite_row_table_value : std_logic_vector(31 downto 0);
   signal sprite_row_meta        : std_logic_vector(16 downto 0);
   signal table_variant          : natural range 0 to 3 := 0;
   signal video_mode             : std_logic_vector(2 downto 0) := "000";

   function table_word(
      address : std_logic_vector(15 downto 0);
      variant : natural
   )
      return std_logic_vector is
      variable word_address : natural;
   begin
      word_address := to_integer(unsigned(address));
      if variant > 0 and word_address >= 16#0200# and word_address < 16#0400# then
         if variant = 3 then
            if (word_address - 16#0200#) mod 4 = 0 then
               return std_logic_vector(to_unsigned((word_address - 16#0200#) / 4, 16));
            else
               return std_logic_vector(to_unsigned(((word_address - 16#0200#) / 4) * 256, 16));
            end if;
         end if;
         if word_address = 16#03FC# then
            if variant = 1 then return x"0101"; else return x"0202"; end if;
         elsif word_address = 16#03FE# then
            if variant = 1 then return x"1000"; else return x"2000"; end if;
         elsif (word_address - 16#0200#) mod 4 = 2 then
            -- All non-target descriptors have Y=$F0 and are inactive for
            -- rows 0/1. Descriptor 127 alone distinguishes old/new tables.
            return x"00F0";
         else
            return x"0000";
         end if;
      end if;

      -- Two wrapped descriptors have distinct low/high halves and y=0, so
      -- their eventual row admissions prove data assembly as well as address
      -- provenance. Every other word is address-patterned, never anonymous 0.
      case to_integer(unsigned(address)) is
         when 16#13FC# => return x"0101";
         when 16#13FE# => return x"1000";
         when 16#1200# => return x"0202";
         when 16#1202# => return x"2000";
         when others =>
            return std_logic_vector(unsigned(address) xor to_unsigned(16#A55A#, 16));
      end case;
   end function;
begin
   clk <= not clk after 5 ns;

   -- The production VRAM is a synchronous dpram. This address-patterned model
   -- also returns response metadata from the exact request word.
   ram_model : process (clk)
   begin
      if rising_edge(clk) then
         ram_dataread  <= table_word(ram_addr, table_variant);
         ram_resp_addr <= ram_addr;
      end if;
   end process;

   dut : entity work.gpu
      generic map (
         is_simu => '1'
      )
      port map (
         clk => clk,
         ce => ce,
         reset => reset,
         isColor => '1',
         video_mode => video_mode,
         IRQ_LineComp => open,
         IRQ_VBlankTmr => open,
         IRQ_VBlank => open,
         IRQ_HBlankTmr => open,
         vertical => open,
         RegBus_Din => reg_din,
         RegBus_Adr => reg_adr,
         RegBus_wren => reg_wren,
         RegBus_rst => reg_rst,
         RegBus_Dout => open,
         RAM_addr => ram_addr,
         RAM_dataread => ram_dataread,
         RAM_response_addr => ram_resp_addr,
         RAM_response_collision => '0',
         Color_addr => open,
         Color_dataread => (others => '0'),
         pixel_out_addr => open,
         pixel_out_data => open,
         pixel_out_we => open,
         SOUND_addr => (others => '0'),
         SOUND_dataread => open,
         SOUND_valid => open,
         SSBUS_Din => ss_din,
         SSBUS_Adr => ss_adr,
         SSBUS_wren => ss_wren,
         SSBUS_rst => ss_rst,
         SSBUS_Dout => ss_dout,
         export_vtime => vtime,
         debug_vram_fetch_valid => fetch_valid,
         debug_vram_fetch_role => fetch_role,
         debug_bg0_cell_valid => open,
         debug_bg0_cell_map_addr => open,
         debug_bg0_cell_map_value => open,
         debug_bg0_cell_row_addr => open,
         debug_bg0_cell_row_value => open,
         debug_bg0_cell_meta => open,
         debug_bg1_cell_valid => open,
         debug_bg1_cell_map_addr => open,
         debug_bg1_cell_map_value => open,
         debug_bg1_cell_row_addr => open,
         debug_bg1_cell_row_value => open,
         debug_bg1_cell_meta => open,
         debug_sprite_row_valid => sprite_row_valid,
         debug_sprite_row_table_addr => sprite_row_table_addr,
         debug_sprite_row_table_value => sprite_row_table_value,
         debug_sprite_row_table_generation => open,
         debug_sprite_row_line_epoch => open,
         debug_sprite_row_addr => open,
         debug_sprite_row_value => open,
         debug_sprite_row_meta => sprite_row_meta
      );

   stimulus : process
      variable shadow_line       : natural range 0 to 158 := 0;
      variable shadow_cycle      : natural range 0 to 255 := 0;
      variable shadow_final      : natural range 0 to 158 := 158;
      variable arbiter_phase     : natural range 0 to 7 := 0;
      variable tracking          : boolean := false;
      variable expect_transfer   : boolean := false;
      variable verify_rows       : boolean := false;
      variable verify_dma_addresses : boolean := true;
      variable verify_final144_rows : boolean := false;
      variable verify_saturated_rows : boolean := false;
      variable requested_phase   : natural range 0 to 7 := 1;
      variable fetch_count       : natural := 0;
      variable case_fetch_count  : natural := 0;
      variable row_count         : natural := 0;
      variable new_row0_count    : natural := 0;
      variable new_row1_count    : natural := 0;
      variable saturated_row_count : natural := 0;
      variable expected_addr     : natural;

      procedure observe(edge_phase : natural) is
      begin
         if tracking and reset = '0' and ce = '1' then
            if shadow_cycle = 255 then
               shadow_cycle := 0;
               if shadow_line = shadow_final then
                  shadow_line := 0;
               else
                  shadow_line := shadow_line + 1;
               end if;
            else
               shadow_cycle := shadow_cycle + 1;
            end if;
         end if;

         if fetch_valid = '1' and fetch_role = "100" then
            assert reset = '0'
               report "sprite-table request remained visible during reset" severity failure;
            assert tracking and expect_transfer
               report "sprite-table request occurred while transfer was disarmed" severity failure;
            assert shadow_line = 144 and unsigned(vtime) = 144
               report "sprite-table request escaped line 144" severity failure;
            assert case_fetch_count < 256
               report "more than 256 sprite-table requests" severity failure;
            if verify_dma_addresses then
               assert shadow_cycle = case_fetch_count
                  report "sprite-table request is not one word per logical system cycle" severity failure;
            end if;

            if verify_dma_addresses then
               expected_addr := 16#1200# + ((16#1FC# + (case_fetch_count * 2)) mod 512);
               assert unsigned(ram_addr) = expected_addr
                  report "sprite-table wrapped address mismatch" severity failure;
            end if;

            report "sprite_dma trace boundary_phase=" & integer'image(requested_phase) &
                   " arbiter_phase=" & integer'image(edge_phase) &
                   " line=" & integer'image(shadow_line) &
                   " cycle=" & integer'image(shadow_cycle) &
                   " address=0x" & to_hstring(ram_addr) &
                   " count=" & integer'image(case_fetch_count + 1)
               severity note;
            case_fetch_count := case_fetch_count + 1;
            fetch_count := fetch_count + 1;
         end if;

         if verify_rows and sprite_row_valid = '1' and shadow_line = 158 then
            assert sprite_row_meta(7 downto 0) = x"00"
               report "terminal-line sprite prefetch did not target next-frame row0"
               severity failure;
            if row_count = 0 then
               assert unsigned(sprite_row_table_addr) = 16#13FC#
                  report "first cached descriptor did not use wrapped late-line-143 address" severity failure;
               assert sprite_row_table_value = x"10000101"
                  report "first cached descriptor low/high data assembly mismatch" severity failure;
            elsif row_count = 1 then
               assert unsigned(sprite_row_table_addr) = 16#1200#
                  report "second cached descriptor did not wrap to table base" severity failure;
               assert sprite_row_table_value = x"20000202"
                  report "second cached descriptor low/high data assembly mismatch" severity failure;
            end if;
            row_count := row_count + 1;
         end if;

         if verify_final144_rows and sprite_row_valid = '1' then
            assert unsigned(sprite_row_table_addr) = 16#03FC#
               report "final144 row prefetch did not reach descriptor127"
               severity failure;
            if sprite_row_meta(7 downto 0) = x"00" then
               assert shadow_line = 0 and sprite_row_table_value = x"20000202"
                  report "final144 row0 was not streamed from newly copied OAM"
                  severity failure;
               new_row0_count := new_row0_count + 1;
            elsif sprite_row_meta(7 downto 0) = x"01" then
               assert shadow_line = 0 and sprite_row_table_value = x"20000202"
                  report "final144 row1 was not prepared from complete-new OAM"
                  severity failure;
               new_row1_count := new_row1_count + 1;
            else
               assert false
                  report "final144 OAM handoff admitted an unexpected sprite row"
                  severity failure;
            end if;
         end if;

         if verify_saturated_rows and sprite_row_valid = '1' then
            assert saturated_row_count < 32
               report "final144 stream admitted more than 32 sprites" severity failure;
            assert unsigned(sprite_row_table_addr) =
                   to_unsigned(16#0200# + saturated_row_count * 4, 16)
               report "final144 saturated stream did not preserve first-32 OAM order"
               severity failure;
            assert sprite_row_meta(7 downto 0) = x"00" and
                   unsigned(sprite_row_meta(12 downto 8)) = saturated_row_count
               report "final144 saturated stream row/slot metadata mismatch"
               severity failure;
            saturated_row_count := saturated_row_count + 1;
         end if;
      end procedure;

      procedure tick is
         variable edge_phase : natural range 0 to 7;
      begin
         edge_phase := arbiter_phase;
         wait until rising_edge(clk);
         wait for 1 ns;
         observe(edge_phase);
         arbiter_phase := (arbiter_phase + 1) mod 8;
      end procedure;

      procedure write_ss(address : natural; value : std_logic_vector(63 downto 0)) is
      begin
         ss_adr <= std_logic_vector(to_unsigned(address, ss_adr'length));
         ss_din <= value;
         ss_wren <= '1';
         tick;
         ss_wren <= '0';
      end procedure;

      procedure write_reg(address : natural; value : natural) is
      begin
         reg_adr <= std_logic_vector(to_unsigned(address, reg_adr'length));
         reg_din <= std_logic_vector(to_unsigned(value, reg_din'length));
         reg_wren <= '1';
         tick;
         reg_wren <= '0';
      end procedure;

      procedure align_phase(target : natural) is
      begin
         while arbiter_phase /= target loop
            tick;
         end loop;
      end procedure;

      procedure pulse_system_cycle is
      begin
         ce <= '1';
         tick;
         ce <= '0';
      end procedure;

      procedure system_cycle_fast is
      begin
         pulse_system_cycle;
         for i in 1 to 3 loop
            tick;
         end loop;
      end procedure;

      procedure restore_raster(line_number : natural; cycle_number : natural) is
         variable gpu_state : std_logic_vector(63 downto 0) := (others => '0');
      begin
         tracking := false;
         expect_transfer := false;
         gpu_state(7 downto 0) := std_logic_vector(to_unsigned(cycle_number, 8));
         gpu_state(15 downto 8) := std_logic_vector(to_unsigned(line_number, 8));
         write_ss(7, gpu_state);
         reset <= '1';
         tick;
         reset <= '0';
         shadow_line := line_number;
         shadow_cycle := cycle_number;
      end procedure;

      procedure run_phase_case(boundary_phase : natural; check_rows : boolean) is
         variable start_fetch_count : natural;
      begin
         requested_phase := boundary_phase;
         case_fetch_count := 0;
         row_count := 0;
         verify_rows := check_rows;
         verify_dma_addresses := true;
         shadow_final := 158;
         restore_raster(142, 250);

         -- Initial values deliberately differ from the late line-143 values.
         video_mode <= "100"; -- Color 2bpp: six-bit SPR_BASE
         write_reg(16#04#, 16#01#);
         write_reg(16#05#, 16#00#);
         write_reg(16#06#, 16#01#);

         tracking := true;
         expect_transfer := true;
         start_fetch_count := fetch_count;

         -- Reach line 143 cycle 240. Any inherited line-142 DMA fails observe.
         for i in 1 to 246 loop
            system_cycle_fast;
         end loop;
         assert shadow_line = 143 and shadow_cycle = 240
            report "bench raster setup error" severity failure;

         -- These values must be captured at the line-144 boundary. FIRST=127
         -- makes descriptor 1 wrap from 0x13fe back to base 0x1200.
         write_reg(16#04#, 16#09#);
         write_reg(16#05#, 16#7F#);
         write_reg(16#06#, 16#02#);
         for i in 1 to 15 loop
            system_cycle_fast;
         end loop;
         assert shadow_line = 143 and shadow_cycle = 255
            report "did not reach the line-144 boundary" severity failure;

         -- Put the actual boundary edge at each fast-forward arbiter phase.
         align_phase(boundary_phase);
         pulse_system_cycle;
         assert shadow_line = 144 and shadow_cycle = 0
            report "did not enter line 144 at cycle 0" severity failure;

         -- Keep the four-clock fast cadence while changing all three live
         -- registers on the three clocks between cycle 0 and cycle 1.
         write_reg(16#04#, 16#01#);
         write_reg(16#05#, 16#00#);
         write_reg(16#06#, 16#01#);

         for i in 1 to 255 loop
            system_cycle_fast;
         end loop;
         assert shadow_line = 144 and shadow_cycle = 255
            report "line-144 transfer ended at the wrong raster cycle" severity failure;
         assert case_fetch_count = 256 and fetch_count = start_fetch_count + 256
            report "line 144 did not issue exactly 256 word requests" severity failure;

         -- Advancing one complete fast cycle proves word 255 was physically
         -- attributed before, rather than surfacing as a false line-145 read.
         system_cycle_fast;
         assert shadow_line = 145 and shadow_cycle = 0
            report "did not enter line 145 after complete transfer" severity failure;
         assert case_fetch_count = 256
            report "sprite-table request leaked into line 145" severity failure;

         if check_rows then
            -- Reach the next line 0. The programmed terminal line preloads
            -- row-0 sprites before line 0 is rendered. Count=2 and both
            -- patterned descriptors must be accepted; the post-boundary
            -- count=1 must not win.
            for i in 1 to (14 * 256 + 52) loop
               system_cycle_fast;
            end loop;
            assert shadow_line = 0
               report "did not reach the next visible frame" severity failure;
            assert row_count = 2
               report "late line-143 SPR_COUNT=2 or wrapped descriptor data was not captured" severity failure;
         end if;

         tracking := false;
         expect_transfer := false;
         verify_rows := false;
      end procedure;

      variable restore_state : std_logic_vector(63 downto 0) := (others => '0');
      variable before_cancel : natural;
   begin
      ce <= '0';
      reset <= '1';
      reg_rst <= '1';
      ss_rst <= '1';
      tick;
      reset <= '0';
      reg_rst <= '0';
      ss_rst <= '0';

      -- Normal/fast-forward transitions and arbitrary reset lengths can put
      -- the boundary ce at any arbiter phase. Test all eight, including the
      -- same-edge table slots (1/5) and every queued residue.
      run_phase_case(0, true);
      run_phase_case(1, false);
      run_phase_case(2, false);
      run_phase_case(3, false);
      run_phase_case(4, false);
      run_phase_case(5, false);
      run_phase_case(6, false);
      run_phase_case(7, false);

      -- Begin another transfer, then restore the legacy raster payload into
      -- the middle of line 144. The cache/transfer phase is not in that
      -- payload and Pocket Memories is unsupported, so reset must cancel the
      -- old request and leave the remainder fail-closed until next frame.
      requested_phase := 3;
      case_fetch_count := 0;
      restore_raster(143, 255);
      video_mode <= "100";
      write_reg(16#04#, 16#09#);
      write_reg(16#05#, 16#7F#);
      write_reg(16#06#, 16#02#);
      align_phase(3);
      tracking := true;
      expect_transfer := true;
      pulse_system_cycle;
      for i in 1 to 3 loop
         tick;
      end loop;
      for i in 1 to 8 loop
         system_cycle_fast;
      end loop;
      assert case_fetch_count = 9
         report "reset-cancellation precondition did not issue nine words" severity failure;

      tracking := false;
      expect_transfer := false;
      restore_state(7 downto 0) := std_logic_vector(to_unsigned(64, 8));
      restore_state(15 downto 8) := std_logic_vector(to_unsigned(144, 8));
      write_ss(7, restore_state);
      reset <= '1';
      tick;
      reset <= '0';
      shadow_line := 144;
      shadow_cycle := 64;
      before_cancel := fetch_count;
      tracking := true;
      for i in 1 to 32 loop
         system_cycle_fast;
      end loop;
      assert shadow_line = 144 and shadow_cycle = 96
         report "reset/restore cancellation raster setup error" severity failure;
      assert fetch_count = before_cancel
         report "reset/restore resumed an unsaved line-144 transfer remainder" severity failure;

      -- Minimum VBlank-capable total: seed a complete old internal table,
      -- then refresh all 128 descriptors on terminal line144. Descriptor127
      -- differs between old/new tables and is active on rows0/1. Row0 must be
      -- streamed from the just-completed descriptor, never scanned from the
      -- partial spriteRAM array; row1 then uses the same complete-new table.
      tracking := false;
      expect_transfer := false;
      verify_dma_addresses := false;
      shadow_final := 144;
      table_variant <= 1;
      write_reg(16#16#, 144);
      video_mode <= "100";
      write_reg(16#04#, 1);
      write_reg(16#05#, 0);
      write_reg(16#06#, 128);
      restore_raster(143, 255);

      requested_phase := 0;
      case_fetch_count := 0;
      tracking := true;
      expect_transfer := true;
      align_phase(0);
      pulse_system_cycle;
      for i in 1 to 3 loop
         tick;
      end loop;
      for i in 1 to 255 loop
         system_cycle_fast;
      end loop;
      assert shadow_line = 144 and shadow_cycle = 255 and case_fetch_count = 256
         report "old-table seed did not copy exactly 256 words" severity failure;
      system_cycle_fast;
      expect_transfer := false;
      assert shadow_line = 0 and shadow_cycle = 0
         report "final144 old-table seed did not wrap to line0" severity failure;
      expect_transfer := false;
      for i in 1 to 8 loop
         tick;
      end loop;

      -- Replace the complete old table at every possible boundary arbiter
      -- phase. Descriptor127 is the only active sprite and arrives last, so it
      -- exercises the worst-case cross-wrap response, deferred start, and
      -- complete-new row1 handoff without relying on an early descriptor.
      for boundary_phase in 0 to 7 loop
         table_variant <= 2;
         tick;
         restore_raster(143, 255);
         requested_phase := boundary_phase;
         case_fetch_count := 0;
         new_row0_count := 0;
         new_row1_count := 0;
         verify_final144_rows := true;
         tracking := true;
         expect_transfer := true;
         align_phase(boundary_phase);
         pulse_system_cycle;
         for i in 1 to 3 loop
            tick;
         end loop;
         for i in 1 to 255 loop
            system_cycle_fast;
         end loop;
         assert shadow_line = 144 and shadow_cycle = 255 and case_fetch_count = 256
            report "new-table line144 DMA did not copy exactly 256 words"
            severity failure;
         system_cycle_fast;
         expect_transfer := false;
         assert shadow_line = 0 and shadow_cycle = 0
            report "new-table final144 DMA did not wrap to line0" severity failure;
         for i in 1 to 160 loop
            system_cycle_fast;
         end loop;
         assert new_row0_count = 1 and new_row1_count = 1
            report "final144 OAM handoff was stale, partial, mixed, or phase-dependent"
            severity failure;
         verify_final144_rows := false;
         tracking := false;
      end loop;

      -- Saturated traffic makes every descriptor active. The physical RTL,
      -- not only the independent scheduler model, must sustain the one-current
      -- plus one-pending cadence and retain exactly the first 32 in OAM order.
      table_variant <= 3;
      tick;
      for boundary_phase in 0 to 7 loop
         restore_raster(143, 255);
         requested_phase := boundary_phase;
         case_fetch_count := 0;
         saturated_row_count := 0;
         verify_saturated_rows := true;
         tracking := true;
         expect_transfer := true;
         align_phase(boundary_phase);
         pulse_system_cycle;
         for i in 1 to 3 loop
            tick;
         end loop;
         for i in 1 to 255 loop
            system_cycle_fast;
         end loop;
         assert case_fetch_count = 256
            report "final144 saturated transfer did not copy exactly 256 words"
            severity failure;
         system_cycle_fast;
         expect_transfer := false;
         for i in 1 to 8 loop
            system_cycle_fast;
         end loop;
         assert saturated_row_count = 32
            report "final144 saturated stream did not retain exactly the first 32 sprites"
            severity failure;
         verify_saturated_rows := false;
         tracking := false;
      end loop;

      report "PASS GPU sprite DMA line-144 timing at all eight arbiter phases, wrap data, boundary latch, provenance, reset cancellation, final144 newly copied row0/row1 handoff, and all-phase saturated first-32 retention"
         severity note;
      std.env.stop;
      wait;
   end process;
end architecture;
