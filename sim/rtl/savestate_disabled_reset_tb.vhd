library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

use work.pBus_savestates.all;

entity savestate_disabled_reset_tb is
end entity;

architecture test of savestate_disabled_reset_tb is
   signal clk                  : std_logic := '0';
   signal reset_in             : std_logic := '0';
   signal reset_out            : std_logic;
   signal regbus_rst           : std_logic;
   signal load_done            : std_logic;
   signal savestate_busy       : std_logic;
   signal savestate_slow       : std_logic;
   signal bus_din              : std_logic_vector(SSBUS_buswidth-1 downto 0);
   signal bus_adr              : std_logic_vector(SSBUS_busadr-1 downto 0);
   signal bus_wren             : std_logic;
   signal bus_rst              : std_logic;
   signal loading_savestate    : std_logic;
   signal saving_savestate     : std_logic;
   signal sleep_savestate      : std_logic;
   signal save_ram_addr        : std_logic_vector(18 downto 0);
   signal save_ram_rden        : std_logic_vector(2 downto 0);
   signal save_ram_wren        : std_logic_vector(2 downto 0);
   signal save_ram_write_data  : std_logic_vector(15 downto 0);
   signal state_bus_din        : std_logic_vector(63 downto 0);
   signal state_bus_addr       : std_logic_vector(25 downto 0);
   signal state_bus_rnw        : std_logic;
   signal state_bus_ena        : std_logic;
   signal state_bus_be         : std_logic_vector(7 downto 0);
   signal hostile_bus_dout     : std_logic_vector(63 downto 0) := (others => '0');
   signal hostile_bus_done     : std_logic := '0';
begin
   clk <= not clk after 5 ns;

   dut : entity work.savestates
      port map
      (
         clk                   => clk,
         ce                    => '1',
         reset_in              => reset_in,
         reset_out             => reset_out,
         RegBus_rst            => regbus_rst,
         ramtype               => x"00",
         load_done             => load_done,
         increaseSSHeaderCount => '1',
         save                  => '0',
         load                  => '0',
         savestate_address     => 0,
         savestate_busy        => savestate_busy,
         system_idle           => '1',
         savestate_slow        => savestate_slow,
         BUS_Din               => bus_din,
         BUS_Adr               => bus_adr,
         BUS_wren              => bus_wren,
         BUS_rst               => bus_rst,
         BUS_Dout              => (others => '0'),
         loading_savestate     => loading_savestate,
         saving_savestate      => saving_savestate,
         sleep_savestate       => sleep_savestate,
         Save_busy             => '0',
         Save_RAMAddr          => save_ram_addr,
         Save_RAMRdEn          => save_ram_rden,
         Save_RAMWrEn          => save_ram_wren,
         Save_RAMWriteData     => save_ram_write_data,
         Save_RAMReadData_REG  => (others => '0'),
         Save_RAMReadData_RAM  => (others => '0'),
         Save_RAMReadData_SRAM => (others => '0'),
         bus_out_Din           => state_bus_din,
         bus_out_Dout          => hostile_bus_dout,
         bus_out_Adr           => state_bus_addr,
         bus_out_rnw           => state_bus_rnw,
         bus_out_ena           => state_bus_ena,
         bus_out_be            => state_bus_be,
         bus_out_done          => hostile_bus_done
      );

   stimulus : process
      procedure assert_idle is
      begin
         assert savestate_busy = '0'
            report "disabled state manager became busy" severity failure;
         assert state_bus_ena = '0'
            report "disabled state manager issued an external bus request" severity failure;
         assert loading_savestate = '0' and saving_savestate = '0'
            report "disabled state manager entered a transfer phase" severity failure;
         assert sleep_savestate = '0'
            report "disabled state manager halted the console" severity failure;
      end procedure;
   begin
      -- The APF transport stub holds save/load low. Even adversarial activity
      -- on its now-unreachable return bus must not start the state engine.
      for i in 1 to 4 loop
         wait until rising_edge(clk);
         wait for 1 ns;
         assert_idle;
      end loop;

      hostile_bus_dout <= (others => '1');
      hostile_bus_done <= '1';
      for i in 1 to 4 loop
         wait until rising_edge(clk);
         wait for 1 ns;
         assert_idle;
      end loop;
      hostile_bus_done <= '0';

      -- SwanTop relies on this manager for the ordinary console reset. The
      -- APF controller may be absent, but reset_in must still propagate.
      reset_in <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert reset_out = '1'
         report "disabled manager did not propagate reset_out" severity failure;
      assert regbus_rst = '1'
         report "disabled manager did not reset the register bus" severity failure;
      assert bus_rst = '1'
         report "disabled manager did not reset the savestate register bus" severity failure;
      assert_idle;

      reset_in <= '0';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert reset_out = '0' and regbus_rst = '0' and bus_rst = '0'
         report "reset outputs did not release synchronously" severity failure;
      assert_idle;

      -- A second pulse catches one-shot initialization masquerading as reset
      -- propagation and confirms the engine stayed in IDLE throughout.
      reset_in <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert reset_out = '1' and regbus_rst = '1' and bus_rst = '1'
         report "second reset pulse did not propagate" severity failure;
      assert_idle;

      report "PASS savestate_disabled_reset_tb fail-closed idle and reset propagation"
         severity note;
      std.env.stop;
      wait;
   end process;
end architecture;
