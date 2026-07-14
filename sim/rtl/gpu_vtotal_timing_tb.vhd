library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

use work.pRegisterBus.all;
use work.pBus_savestates.all;

-- Clean-room programmable-final-line regression.
--
-- Reference contract:
--   * WSdev Display/IO Ports rev 582: $16 is the inclusive final line and
--     default 158 means 159 lines; LCD output is delayed by one line.
--   * WSdev Timing rev 645: VBlank is line 144 and a shorter frame never
--     generates it.
--   * Mesen2 b9fa69dd wraps Scanline after live LastScanline and performs
--     line compare after the wrap.
--   * ares 449b9371 deliberately repeats its physical line counter for low
--     totals; only its vertical-compare interaction is marked TODO. This
--     bench follows the direct $02 wrap implemented by Mesen and WSdev's
--     inclusive-final-line definition.
entity gpu_vtotal_timing_tb is
end entity;

architecture tb of gpu_vtotal_timing_tb is
   signal clk       : std_logic := '0';
   signal ce        : std_logic := '0';
   signal reset     : std_logic := '0';

   signal irq_line_compare : std_logic;
   signal irq_vblank       : std_logic;
   signal irq_vblank_timer : std_logic;

   signal reg_din  : std_logic_vector(BUS_buswidth - 1 downto 0) := (others => '0');
   signal reg_adr  : std_logic_vector(BUS_busadr - 1 downto 0) := (others => '0');
   signal reg_wren : std_logic := '0';
   signal reg_rst  : std_logic := '0';
   signal reg_dout : std_logic_vector(BUS_buswidth - 1 downto 0);

   signal ss_din  : std_logic_vector(SSBUS_buswidth - 1 downto 0) := (others => '0');
   signal ss_adr  : std_logic_vector(SSBUS_busadr - 1 downto 0) := (others => '0');
   signal ss_wren : std_logic := '0';
   signal ss_rst  : std_logic := '0';
   signal ss_dout : std_logic_vector(SSBUS_buswidth - 1 downto 0);

   signal vtime : std_logic_vector(7 downto 0);

   signal ram_addr    : std_logic_vector(15 downto 0);
   signal fetch_valid : std_logic;
   signal fetch_role  : std_logic_vector(2 downto 0);
   signal color_dataread : std_logic_vector(15 downto 0) := x"0123";
   signal video_mode : std_logic_vector(2 downto 0) := "000";

   signal pixel_addr : integer range 0 to 32255;
   signal pixel_data : std_logic_vector(11 downto 0);
   signal pixel_we   : std_logic;
begin
   clk <= not clk after 5 ns;

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
         IRQ_LineComp => irq_line_compare,
         IRQ_VBlankTmr => irq_vblank_timer,
         IRQ_VBlank => irq_vblank,
         IRQ_HBlankTmr => open,
         vertical => open,
         RegBus_Din => reg_din,
         RegBus_Adr => reg_adr,
         RegBus_wren => reg_wren,
         RegBus_rst => reg_rst,
         RegBus_Dout => reg_dout,
         RAM_addr => ram_addr,
         RAM_dataread => (others => '0'),
         RAM_response_addr => (others => '0'),
         RAM_response_collision => '0',
         Color_addr => open,
         Color_dataread => color_dataread,
         pixel_out_addr => pixel_addr,
         pixel_out_data => pixel_data,
         pixel_out_we => pixel_we,
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
         debug_sprite_row_valid => open,
         debug_sprite_row_table_addr => open,
         debug_sprite_row_table_value => open,
         debug_sprite_row_table_generation => open,
         debug_sprite_row_line_epoch => open,
         debug_sprite_row_addr => open,
         debug_sprite_row_value => open,
         debug_sprite_row_meta => open
      );

   stimulus : process
      type row_count_array is array(0 to 143) of natural;
      variable row_counts    : row_count_array := (others => 0);
      variable pixel_total   : natural := 0;
      variable dma_count     : natural := 0;
      variable track_pixels  : boolean := false;
      variable track_dma     : boolean := false;
      variable track_line144 : boolean := false;
      variable line144_pixels : natural := 0;
      variable track_overlap : boolean := false;
      variable overlap_pixels : natural := 0;

      procedure observe is
         variable row : natural;
      begin
         if track_dma and fetch_valid = '1' and fetch_role = "100" then
            assert unsigned(vtime) = 144
               report "sprite-table request escaped actual line 144" severity failure;
            dma_count := dma_count + 1;
         end if;

         if track_line144 and fetch_valid = '1' and fetch_role(2) = '0' then
            assert false
               report "background fetch contended with line-144 OAM/publication"
               severity failure;
         end if;

         if track_line144 and pixel_we = '1' then
            assert unsigned(vtime) = 144 and pixel_addr / 224 = 143
               report "line-144 flush did not publish cached row143"
               severity failure;
            assert pixel_data = x"123"
               report "line-144 register/VRAM change contaminated cached row143"
               severity failure;
            line144_pixels := line144_pixels + 1;
         end if;

         if track_overlap and pixel_we = '1' then
            assert unsigned(vtime) = 1 and pixel_addr / 224 = 0
               report "simultaneous row-cache test published the wrong row"
               severity failure;
            assert pixel_data = x"135"
               report "row-cache same-address write returned new row data"
               severity failure;
            overlap_pixels := overlap_pixels + 1;
         end if;

         if track_pixels and pixel_we = '1' then
            row := pixel_addr / 224;
            assert row <= 143
               report "pixel publication escaped visible framebuffer" severity failure;
            assert unsigned(vtime) = row + 1
               report "LCD one-line publication delay is wrong: line=" &
                      integer'image(to_integer(unsigned(vtime))) &
                      " row=" & integer'image(row) severity failure;
            assert pixel_addr mod 224 = row_counts(row)
               report "pixel publication was not contiguous within row " &
                      integer'image(row) severity failure;
            row_counts(row) := row_counts(row) + 1;
            pixel_total := pixel_total + 1;
         end if;
      end procedure;

      procedure tick is
      begin
         wait until rising_edge(clk);
         wait for 1 ns;
         observe;
      end procedure;

      procedure write_ss(address : natural; value : std_logic_vector(63 downto 0)) is
      begin
         ce <= '0';
         ss_adr <= std_logic_vector(to_unsigned(address, ss_adr'length));
         ss_din <= value;
         ss_wren <= '1';
         tick;
         ss_wren <= '0';
      end procedure;

      procedure read_ss(address : natural; variable value : out std_logic_vector(63 downto 0)) is
      begin
         ss_adr <= std_logic_vector(to_unsigned(address, ss_adr'length));
         ss_wren <= '0';
         wait for 1 ns;
         value := ss_dout;
      end procedure;

      procedure write_reg(address : natural; value : natural) is
      begin
         ce <= '0';
         reg_adr <= std_logic_vector(to_unsigned(address, reg_adr'length));
         reg_din <= std_logic_vector(to_unsigned(value, reg_din'length));
         reg_wren <= '1';
         tick;
         reg_wren <= '0';
      end procedure;

      procedure restore_raster(
         line_number  : natural;
         cycle_number : natural;
         timer_count  : natural := 0;
         timer_control : natural := 0
      ) is
         variable gpu_state   : std_logic_vector(63 downto 0) := (others => '0');
         variable timer_state : std_logic_vector(63 downto 0) := (others => '0');
      begin
         ce <= '0';
         reset <= '0';
         gpu_state(7 downto 0) := std_logic_vector(to_unsigned(cycle_number, 8));
         gpu_state(15 downto 8) := std_logic_vector(to_unsigned(line_number, 8));
         timer_state(31 downto 16) := std_logic_vector(to_unsigned(timer_count, 16));
         timer_state(35 downto 32) := std_logic_vector(to_unsigned(timer_control, 4));
         write_ss(7, gpu_state);
         write_ss(27, timer_state);
         reset <= '1';
         tick;
         reset <= '0';
         assert unsigned(vtime) = line_number
            report "save-state raster restore did not restore LINE_CUR" severity failure;
      end procedure;

      procedure system_cycle_fast is
      begin
         ce <= '1';
         tick;
         ce <= '0';
         for i in 1 to 3 loop
            tick;
         end loop;
      end procedure;

      procedure expect_transition(
         final_line   : natural;
         current_line : natural;
         expected_line : natural
      ) is
      begin
         write_reg(16#16#, final_line);
         write_reg(16#03#, 0);
         restore_raster(current_line, 254);

         ce <= '1';
         tick;
         assert unsigned(vtime) = current_line
            report "line changed before cycle 255 for final " & integer'image(final_line)
            severity failure;
         if expected_line = 0 then
            assert irq_line_compare = '1'
               report "LINE_CMP=0 missing on programmed wrap for final " &
                      integer'image(final_line) severity failure;
         else
            assert irq_line_compare = '0'
               report "LINE_CMP=0 fired without programmed wrap" severity failure;
         end if;

         tick;
         ce <= '0';
         assert unsigned(vtime) = expected_line
            report "wrong next line for final=" & integer'image(final_line) &
                   " current=" & integer'image(current_line) &
                   " expected=" & integer'image(expected_line) &
                   " actual=" & integer'image(to_integer(unsigned(vtime)))
            severity failure;
         reg_adr <= x"02";
         wait for 1 ns;
         assert reg_dout = vtime
            report "$02 read and exported LINE_CUR disagree" severity failure;
      end procedure;

      procedure clear_pixel_counts is
      begin
         for row in row_counts'range loop
            row_counts(row) := 0;
         end loop;
         pixel_total := 0;
      end procedure;

      procedure run_publication_frame(final_line : natural) is
      begin
         write_reg(16#16#, final_line);
         restore_raster(0, 0);
         clear_pixel_counts;
         track_pixels := true;
         ce <= '1';
         for i in 1 to (final_line + 1) * 256 loop
            tick;
         end loop;
         ce <= '0';
         track_pixels := false;
         assert unsigned(vtime) = 0
            report "publication test did not end at programmed wrap" severity failure;
      end procedure;

      variable timer_state : std_logic_vector(63 downto 0);
   begin
      ce <= '0';
      reset <= '1';
      reg_rst <= '1';
      ss_rst <= '1';
      tick;
      reset <= '0';
      reg_rst <= '0';
      ss_rst <= '0';

      -- Inclusive final-line counter, including the zero and $FF extrema.
      expect_transition(0, 0, 0);
      expect_transition(143, 143, 0);
      expect_transition(144, 144, 0);
      expect_transition(158, 158, 0);
      expect_transition(200, 158, 159); -- no inherited line-158 wrap
      expect_transition(200, 200, 0);
      expect_transition(255, 254, 255);
      expect_transition(255, 255, 0);

      -- A settled live raise extends the current frame. A settled lower below
      -- the current line wraps at the next boundary, as both pinned emulators
      -- do. The same-clock CPU-write ordering remains outside this contract.
      write_reg(16#16#, 158);
      restore_raster(158, 254);
      write_reg(16#16#, 160);
      ce <= '1';
      tick;
      assert irq_line_compare = '0' severity failure;
      tick;
      ce <= '0';
      assert unsigned(vtime) = 159
         report "live final-line raise did not extend current frame" severity failure;

      write_reg(16#16#, 158);
      restore_raster(157, 254);
      write_reg(16#16#, 150);
      ce <= '1';
      tick;
      assert irq_line_compare = '1'
         report "live final-line lower did not retarget LINE_CMP=0" severity failure;
      tick;
      ce <= '0';
      assert unsigned(vtime) = 0
         report "live final-line lower did not wrap next boundary" severity failure;

      -- Holding CE low preserves the restored $FF terminal state; the next CE
      -- performs exactly one explicit $FF -> $00 transition.
      write_reg(16#16#, 255);
      restore_raster(255, 255);
      for i in 1 to 5 loop
         tick;
         assert unsigned(vtime) = 255
            report "LINE_CUR advanced while CE was low" severity failure;
      end loop;
      ce <= '1';
      tick;
      ce <= '0';
      assert unsigned(vtime) = 0
         report "restored final-$FF state did not wrap on CE" severity failure;

      -- Final 143 never enters line 144: no VBlank, vertical-timer comparator,
      -- timer decrement, or OAM copy. Use the real CE/4 fast cadence so every
      -- logical line-144 OAM word would have an arbiter slot if one existed.
      write_reg(16#16#, 143);
      restore_raster(143, 254, 1, 4);
      dma_count := 0;
      track_dma := true;
      system_cycle_fast;
      assert irq_vblank = '0' and irq_vblank_timer = '0'
         report "short final143 frame generated VBlank/timer" severity failure;
      system_cycle_fast;
      track_dma := false;
      assert unsigned(vtime) = 0 and dma_count = 0
         report "short final143 frame entered line144 sprite DMA" severity failure;
      read_ss(27, timer_state);
      assert timer_state(31 downto 16) = x"0001" and timer_state(34) = '1'
         report "short final143 frame ticked vertical timer" severity failure;

      -- Final 144 does enter line 144. It generates one VBlank/timer event and
      -- all 256 line-144 word requests before the programmed wrap.
      write_reg(16#16#, 144);
      restore_raster(143, 254, 1, 4);
      dma_count := 0;
      track_dma := true;
      system_cycle_fast;
      assert irq_vblank = '1' and irq_vblank_timer = '1'
         report "final144 did not advertise entry into VBlank" severity failure;
      system_cycle_fast;
      assert unsigned(vtime) = 144
         report "final144 did not enter line144" severity failure;
      read_ss(27, timer_state);
      assert timer_state(31 downto 16) = x"0000" and timer_state(34) = '0'
         report "final144 did not tick one-shot vertical timer" severity failure;
      for i in 1 to 255 loop
         system_cycle_fast;
      end loop;
      track_dma := false;
      assert dma_count = 256
         report "final144 did not perform exactly 256 OAM word requests" severity failure;

      -- The publication path follows the documented one-line LCD delay.
      -- Final1 proves row0 is computed during line0 and sent during line1;
      -- final143 sends rows 0..142 only; final144 additionally sends row143.
      run_publication_frame(1);
      assert row_counts(0) = 224 and pixel_total = 224
         report "final1 did not publish exactly cached row0" severity failure;
      for row in 1 to 143 loop
         assert row_counts(row) = 0
            report "final1 published a row after row0" severity failure;
      end loop;

      run_publication_frame(143);
      for row in 0 to 142 loop
         assert row_counts(row) = 224
            report "final143 missing published row " & integer'image(row) severity failure;
      end loop;
      assert row_counts(143) = 0 and pixel_total = 143 * 224
         report "final143 incorrectly published row143/full frame" severity failure;

      run_publication_frame(144);
      for row in 0 to 143 loop
         assert row_counts(row) = 224
            report "final144 missing published row " & integer'image(row) severity failure;
      end loop;
      assert pixel_total = 144 * 224
         report "final144 did not publish one complete visible frame" severity failure;

      -- Exercise the RAM's same-address read/write path directly. Row0 is A;
      -- while line1 publishes A it simultaneously overwrites every cache slot
      -- with B. Every observed output must retain OLD_DATA A.
      write_reg(16#16#, 1);
      video_mode <= "110";
      color_dataread <= x"0135";
      restore_raster(0, 0);
      ce <= '1';
      for i in 1 to 256 loop
         tick;
      end loop;
      ce <= '0';
      assert unsigned(vtime) = 1
         report "row-cache A/B test did not enter line1" severity failure;
      color_dataread <= x"0ACE";
      tick;
      overlap_pixels := 0;
      track_overlap := true;
      ce <= '1';
      for i in 1 to 256 loop
         tick;
      end loop;
      ce <= '0';
      track_overlap := false;
      assert overlap_pixels = 224
         report "row-cache A/B test did not publish exactly 224 OLD_DATA pixels"
         severity failure;

      -- Compute row143 with a stable Color-RAM value, then change that value
      -- after entering VBlank. The line-144 flush must read only the cached
      -- row and the background engines must stay idle while OAM sync runs.
      write_reg(16#16#, 144);
      video_mode <= "110";
      color_dataread <= x"0123";
      restore_raster(0, 0);
      ce <= '1';
      for i in 1 to 144 * 256 loop
         tick;
      end loop;
      ce <= '0';
      assert unsigned(vtime) = 144
         report "contamination test did not enter line144" severity failure;
      color_dataread <= x"0ABC";
      tick;
      line144_pixels := 0;
      track_line144 := true;
      ce <= '1';
      for i in 1 to 256 loop
         tick;
      end loop;
      ce <= '0';
      track_line144 := false;
      assert line144_pixels = 224
         report "line144 did not flush exactly 224 cached pixels" severity failure;

      report "PASS GPU live programmable final line, compare0, VBlank/timer, line144 OAM gate, CE/restore, cached one-line publication, final1, and VBlank isolation"
         severity note;
      std.env.stop;
      wait;
   end process;
end architecture;
