library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

use work.pRegisterBus.all;
use work.pBus_savestates.all;

-- Clean-room timer regression for the documented counter=1 interrupt quirk.
-- No cartridge, firmware, commercial data, or title-derived bytes are used.
--
-- Reference contract:
--   WSdev Timers rev 117 documents an IRQ at counter=1 even when countdown is
--   disabled: https://ws.nesdev.org/w/index.php?title=Timers&oldid=117
--   ares 449b9371: https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/timer.cpp#L1-L8
--   Mesen2 b9fa69dd: https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsTimer.cpp#L11-L35
entity gpu_timer_irq_tb is
end entity;

architecture tb of gpu_timer_irq_tb is
   signal clk       : std_logic := '0';
   signal ce        : std_logic := '0';
   signal reset     : std_logic := '0';

   signal irq_hblank_timer : std_logic;
   signal irq_vblank_timer : std_logic;

   signal reg_din  : std_logic_vector(BUS_buswidth - 1 downto 0) := (others => '0');
   signal reg_adr  : std_logic_vector(BUS_busadr - 1 downto 0) := (others => '0');
   signal reg_wren : std_logic := '0';
   signal reg_rst  : std_logic := '0';

   signal ss_din  : std_logic_vector(SSBUS_buswidth - 1 downto 0) := (others => '0');
   signal ss_adr  : std_logic_vector(SSBUS_busadr - 1 downto 0) := (others => '0');
   signal ss_wren : std_logic := '0';
   signal ss_rst  : std_logic := '0';
   signal ss_dout : std_logic_vector(SSBUS_buswidth - 1 downto 0);
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
         video_mode => "000",
         IRQ_LineComp => open,
         IRQ_VBlankTmr => irq_vblank_timer,
         IRQ_VBlank => open,
         IRQ_HBlankTmr => irq_hblank_timer,
         vertical => open,
         RegBus_Din => reg_din,
         RegBus_Adr => reg_adr,
         RegBus_wren => reg_wren,
         RegBus_rst => reg_rst,
         RegBus_Dout => open,
         RAM_addr => open,
         RAM_dataread => (others => '0'),
         RAM_response_addr => (others => '0'),
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
         export_vtime => open,
         debug_vram_fetch_valid => open,
         debug_vram_fetch_role => open,
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
      procedure tick is
      begin
         wait until rising_edge(clk);
         wait for 1 ns;
      end procedure;

      procedure write_ss(address : natural; value : std_logic_vector(63 downto 0)) is
      begin
         ss_adr <= std_logic_vector(to_unsigned(address, ss_adr'length));
         ss_din <= value;
         ss_wren <= '1';
         tick;
         ss_wren <= '0';
      end procedure;

      procedure seed_raster(x_value : natural; line_value : natural) is
         variable gpu_state : std_logic_vector(63 downto 0) := (others => '0');
         variable timer_state : std_logic_vector(63 downto 0) := (others => '0');
      begin
         ce <= '0';
         reset <= '0';
         reg_wren <= '0';
         gpu_state(7 downto 0) := std_logic_vector(to_unsigned(x_value, 8));
         gpu_state(15 downto 8) := std_logic_vector(to_unsigned(line_value, 8));
         write_ss(7, gpu_state);
         write_ss(27, timer_state);

         -- Load the exact raster position through the existing save-state
         -- restore boundary while resetting the software-visible registers.
         reg_rst <= '1';
         reset <= '1';
         tick;
         reset <= '0';
         reg_rst <= '0';
         ce <= '1';
      end procedure;

      procedure write_reg(address : natural; value : natural) is
      begin
         reg_adr <= std_logic_vector(to_unsigned(address, reg_adr'length));
         reg_din <= std_logic_vector(to_unsigned(value, reg_din'length));
         reg_wren <= '1';
         tick;
         reg_wren <= '0';
      end procedure;

      procedure count_pulses(
         signal irq : in std_logic;
         cycles : natural;
         variable pulses : out natural
      ) is
      begin
         pulses := 0;
         for i in 1 to cycles loop
            tick;
            if irq = '1' then
               pulses := pulses + 1;
            end if;
         end loop;
      end procedure;

      procedure read_timer_state(variable value : out std_logic_vector(63 downto 0)) is
      begin
         ss_adr <= std_logic_vector(to_unsigned(27, ss_adr'length));
         ss_wren <= '0';
         wait for 1 ns;
         value := ss_dout;
      end procedure;

      variable pulses : natural;
      variable timer_state : std_logic_vector(63 downto 0);
   begin
      -- Establish deterministic defaults for every register bank.
      ce <= '0';
      reg_rst <= '1';
      ss_rst <= '1';
      reset <= '1';
      tick;
      reg_rst <= '0';
      ss_rst <= '0';
      reset <= '0';

      -- Disabled HBlank countdown, reload/counter=1: the counter remains at 1,
      -- so the interrupt comparator must fire at each of two HBlank edges.
      seed_raster(240, 0);
      write_reg(16#A4#, 1);
      write_reg(16#A5#, 0);
      write_reg(16#A2#, 0);
      count_pulses(irq_hblank_timer, 280, pulses);
      assert pulses = 2
         report "disabled HBlank reload=1 did not fire at each HBlank" severity failure;

      -- Reload/counter=0 must never manufacture an interrupt.
      seed_raster(240, 0);
      write_reg(16#A4#, 0);
      write_reg(16#A5#, 0);
      write_reg(16#A2#, 0);
      count_pulses(irq_hblank_timer, 280, pulses);
      assert pulses = 0
         report "disabled HBlank reload=0 generated a spurious interrupt" severity failure;

      -- Existing enabled one-shot and repeat countdown behavior remains intact.
      seed_raster(240, 0);
      write_reg(16#A4#, 2);
      write_reg(16#A5#, 0);
      write_reg(16#A2#, 1);
      count_pulses(irq_hblank_timer, 800, pulses);
      assert pulses = 1
         report "enabled HBlank one-shot behavior changed" severity failure;

      seed_raster(240, 0);
      write_reg(16#A4#, 2);
      write_reg(16#A5#, 0);
      write_reg(16#A2#, 3);
      count_pulses(irq_hblank_timer, 800, pulses);
      assert pulses = 2
         report "enabled HBlank repeat behavior changed" severity failure;

      -- The documented counter=1 quirk applies identically to VBlank timer
      -- conditions.  Start immediately before line 143's terminal clock.
      seed_raster(240, 143);
      write_reg(16#A6#, 1);
      write_reg(16#A7#, 0);
      write_reg(16#A2#, 0);
      count_pulses(irq_vblank_timer, 20, pulses);
      assert pulses = 1
         report "disabled VBlank reload=1 did not fire" severity failure;

      seed_raster(240, 143);
      write_reg(16#A6#, 0);
      write_reg(16#A7#, 0);
      write_reg(16#A2#, 0);
      count_pulses(irq_vblank_timer, 20, pulses);
      assert pulses = 0
         report "disabled VBlank reload=0 generated a spurious interrupt" severity failure;

      -- The live state bus distinguishes one-shot from auto-reload immediately
      -- after the interrupt edge without assuming another frame's cadence.
      seed_raster(240, 143);
      write_reg(16#A6#, 1);
      write_reg(16#A7#, 0);
      write_reg(16#A2#, 4);
      count_pulses(irq_vblank_timer, 20, pulses);
      assert pulses = 1
         report "enabled VBlank one-shot behavior changed" severity failure;
      read_timer_state(timer_state);
      assert timer_state(31 downto 16) = x"0000" and timer_state(34) = '0'
         report "enabled VBlank one-shot did not stop at zero" severity failure;

      seed_raster(240, 143);
      write_reg(16#A6#, 1);
      write_reg(16#A7#, 0);
      write_reg(16#A2#, 12);
      count_pulses(irq_vblank_timer, 20, pulses);
      assert pulses = 1
         report "enabled VBlank repeat behavior changed" severity failure;
      read_timer_state(timer_state);
      assert timer_state(31 downto 16) = x"0001" and timer_state(35 downto 34) = "11"
         report "enabled VBlank repeat did not reload and stay enabled: " &
                to_hstring(timer_state(35 downto 0)) severity failure;

      report "PASS GPU timer IRQ disabled-countdown quirk and enabled modes" severity note;
      std.env.stop;
      wait;
   end process;
end architecture;
