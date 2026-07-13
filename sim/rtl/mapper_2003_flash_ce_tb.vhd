-- SPDX-License-Identifier: GPL-2.0-only
-- Black-box coverage for the first volatile Bandai 2003 self-flash slice.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

use work.pRegisterBus.all;
use work.pBus_savestates.all;

entity mapper_2003_flash_ce_tb is
end entity;

architecture test of mapper_2003_flash_ce_tb is
  constant CLK_PERIOD : time := 10 ns;

  signal clk           : std_logic := '0';
  signal reset         : std_logic := '1';
  signal reg_rst       : std_logic := '1';
  signal romtype       : std_logic_vector(7 downto 0) := x"01";
  signal ramtype       : std_logic_vector(7 downto 0) := x"01";
  signal reg_din       : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_addr      : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_wren      : std_logic := '0';
  signal reg_dout      : std_logic_vector(7 downto 0);
  signal cpu_read      : std_logic := '0';
  signal cpu_write     : std_logic := '0';
  signal cpu_be        : std_logic_vector(1 downto 0) := "00";
  signal cpu_addr      : unsigned(19 downto 0) := (others => '0');
  signal cpu_datawrite : std_logic_vector(15 downto 0) := (others => '0');
  signal ext_read      : std_logic;
  signal ext_write     : std_logic;
  signal ext_be        : std_logic_vector(1 downto 0);
  signal ext_addr      : std_logic_vector(24 downto 0);
  signal ext_datawrite : std_logic_vector(15 downto 0);
  signal debug_space   : std_logic_vector(3 downto 0);
  signal debug_off     : std_logic_vector(23 downto 0);
  signal debug_valid   : std_logic;
begin
  clk <= not clk after CLK_PERIOD / 2;

  dut : entity work.memorymux
    port map (
      clk                    => clk,
      clk_ram                => clk,
      ce                     => '1',
      reset                  => reset,
      isColor                => '1',
      preserve_internal_eeprom => '0',
      maskAddr               => x"07FFFF",
      romtype                => romtype,
      ramtype                => ramtype,
      eepromWrite            => open,
      eeprom_addr            => (others => '0'),
      eeprom_din             => (others => '0'),
      eeprom_dout            => open,
      eeprom_req             => '0',
      eeprom_rnw             => '1',
      internal_eeprom_bank   => '0',
      internal_eeprom_addr   => (others => '0'),
      internal_eeprom_din    => (others => '0'),
      internal_eeprom_dout   => open,
      internal_eeprom_req    => '0',
      internal_eeprom_rnw    => '1',
      cpu_read               => cpu_read,
      cpu_write              => cpu_write,
      cpu_be                 => cpu_be,
      cpu_addr               => cpu_addr,
      cpu_datawrite          => cpu_datawrite,
      cpu_dataread           => open,
      debug_mem_space        => debug_space,
      debug_mem_offset       => debug_off,
      debug_mem_offset_valid => debug_valid,
      debug_gpu_collision    => open,
      GPU_addr               => (others => '0'),
      GPU_dataread           => open,
      Color_addr             => (others => '0'),
      Color_dataread         => open,
      bios_wraddr            => (others => '0'),
      bios_wrdata            => (others => '0'),
      bios_wr                => '0',
      bios_wrcolor           => '0',
      RegBus_Din             => reg_din,
      RegBus_Adr             => reg_addr,
      RegBus_wren            => reg_wren,
      RegBus_rst             => reg_rst,
      RegBus_Dout            => reg_dout,
      EXTRAM_read            => ext_read,
      EXTRAM_write           => ext_write,
      EXTRAM_be              => ext_be,
      EXTRAM_addr            => ext_addr,
      EXTRAM_datawrite       => ext_datawrite,
      EXTRAM_dataread        => (others => '0'),
      sleep_savestate        => '0',
      SSBus_Din              => (others => '0'),
      SSBus_Adr              => (others => '0'),
      SSBus_wren             => '0',
      SSBus_rst              => '0',
      SSBus_Dout             => open,
      SSMEM_Addr             => (others => '0'),
      SSMEM_RdEn             => (others => '0'),
      SSMEM_WrEn             => (others => '0'),
      SSMEM_WriteData        => (others => '0'),
      SSMEM_ReadData_REG     => open,
      SSMEM_ReadData_RAM     => open,
      SSMEM_ReadData_SRAM    => open
    );

  stimulus : process
    procedure tick(count : positive := 1) is
    begin
      for index in 1 to count loop
        wait until rising_edge(clk);
        wait for 1 ns;
      end loop;
    end procedure;

    procedure write_port(address : natural; value : natural) is
    begin
      wait until falling_edge(clk);
      -- An I/O-register write is not a memory request. Keep the two paths
      -- mutually exclusive and assert that changing CE cannot itself write
      -- either the ordinary SRAM backing or the ROM/flash backing.
      cpu_read <= '0';
      cpu_write <= '0';
      cpu_be <= "00";
      reg_addr <= std_logic_vector(to_unsigned(address, reg_addr'length));
      reg_din <= std_logic_vector(to_unsigned(value, reg_din'length));
      reg_wren <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert ext_read = '0' and ext_write = '0'
        report "register write leaked onto the external memory bus"
        severity failure;
      reg_wren <= '0';
    end procedure;

    procedure expect_port(address : natural; expected : natural) is
    begin
      wait until falling_edge(clk);
      reg_addr <= std_logic_vector(to_unsigned(address, reg_addr'length));
      reg_wren <= '0';
      wait for 1 ns;
      assert to_integer(unsigned(reg_dout)) = expected
        report "CE register readback mismatch at port " & integer'image(address)
        severity failure;
    end procedure;

    procedure expect_route(
      expected_addr  : natural;
      expected_space : natural;
      expected_off   : natural;
      expected_read  : std_logic;
      expected_write : std_logic;
      expected_be    : std_logic_vector(1 downto 0);
      expected_data  : std_logic_vector(15 downto 0)
    ) is
    begin
      wait for 1 ns;
      assert to_integer(unsigned(ext_addr)) = expected_addr
        report "external byte address mismatch" severity failure;
      assert to_integer(unsigned(debug_space)) = expected_space
        report "debug memory-space mismatch" severity failure;
      assert debug_valid = '1'
        report "debug memory offset is not valid" severity failure;
      assert to_integer(unsigned(debug_off)) = expected_off
        report "debug memory offset mismatch" severity failure;
      assert ext_read = expected_read
        report "external read strobe mismatch" severity failure;
      assert ext_write = expected_write
        report "external write strobe mismatch" severity failure;
      assert ext_be = expected_be
        report "external byte enables mismatch" severity failure;
      assert ext_datawrite = expected_data
        report "external write data mismatch" severity failure;
    end procedure;
  begin
    tick(3);
    reset <= '0';
    reg_rst <= '0';
    tick(2);

    -- D0h is the accepted low-byte alias for the SRAM/flash bank register.
    write_port(16#D0#, 3);
    expect_port(16#CE#, 0);

    -- CE=0 preserves the inherited SRAM route and uses the SRAM-size mask.
    cpu_addr <= to_unsigned(16#10020#, cpu_addr'length);
    cpu_read <= '1';
    cpu_write <= '0';
    cpu_be <= "00";
    cpu_datawrite <= x"1234";
    expect_route(16#1000020#, 2, 16#000020#, '1', '0', "00", x"1234");

    cpu_addr <= to_unsigned(16#10020#, cpu_addr'length);
    cpu_read <= '0';
    cpu_write <= '1';
    cpu_be <= "01";
    cpu_datawrite <= x"12A5";
    expect_route(16#1000020#, 2, 16#000020#, '0', '1', "01", x"12A5");

    cpu_addr <= to_unsigned(16#10021#, cpu_addr'length);
    cpu_datawrite <= x"34C7";
    expect_route(16#1000021#, 2, 16#000021#, '0', '1', "10", x"C700");

    -- The ordinary ROM windows remain read-only; CE controls only the bank-1
    -- window at 10000h-1FFFFh.
    cpu_addr <= to_unsigned(16#20020#, cpu_addr'length);
    cpu_read <= '0';
    cpu_write <= '1';
    cpu_be <= "01";
    cpu_datawrite <= x"91D3";
    expect_route(16#0070020#, 3, 16#070020#, '0', '0', "00", x"91D3");

    -- Only bit 0 exists. High bits neither enable the route nor read back.
    write_port(16#CE#, 16#FE#);
    expect_port(16#CE#, 0);
    write_port(16#CE#, 16#FF#);
    expect_port(16#CE#, 1);

    -- CE=1 moves the same banked window to the ROM/flash half of SDRAM and
    -- uses the ROM mask. Reads and writes are deliberately exposed so a NOR
    -- command controller can be layered on this volatile routing contract.
    cpu_addr <= to_unsigned(16#10020#, cpu_addr'length);
    cpu_read <= '1';
    cpu_write <= '0';
    cpu_be <= "00";
    cpu_datawrite <= x"5678";
    expect_route(16#0030020#, 9, 16#030020#, '1', '0', "00", x"5678");

    cpu_read <= '0';
    cpu_write <= '1';
    cpu_be <= "01";
    cpu_datawrite <= x"56A9";
    expect_route(16#0030020#, 9, 16#030020#, '0', '1', "01", x"56A9");

    cpu_addr <= to_unsigned(16#10021#, cpu_addr'length);
    cpu_datawrite <= x"78CB";
    expect_route(16#0030021#, 9, 16#030021#, '0', '1', "10", x"CB00");

    cpu_addr <= to_unsigned(16#10022#, cpu_addr'length);
    cpu_be <= "11";
    cpu_datawrite <= x"CDEF";
    expect_route(16#0030022#, 9, 16#030022#, '0', '1', "11", x"CDEF");

    -- Flash routing is selected by CE, not by the save-RAM type.
    ramtype <= x"00";
    cpu_addr <= to_unsigned(16#10024#, cpu_addr'length);
    cpu_read <= '1';
    cpu_write <= '0';
    cpu_be <= "00";
    expect_route(16#0030024#, 9, 16#030024#, '1', '0', "00", x"CDEF");

    -- Bandai 2001 and unknown selectors cannot read, write, or activate CE.
    ramtype <= x"01";
    romtype <= x"00";
    tick;
    expect_port(16#CE#, 0);
    write_port(16#CE#, 1);
    expect_port(16#CE#, 0);
    cpu_addr <= to_unsigned(16#10020#, cpu_addr'length);
    cpu_read <= '1';
    cpu_write <= '0';
    cpu_be <= "00";
    expect_route(16#1000020#, 2, 16#000020#, '1', '0', "00", x"CDEF");

    romtype <= x"03";
    tick;
    write_port(16#CE#, 1);
    expect_port(16#CE#, 0);
    cpu_addr <= to_unsigned(16#10020#, cpu_addr'length);
    cpu_read <= '1';
    cpu_write <= '0';
    cpu_be <= "00";
    expect_route(16#1000020#, 2, 16#000020#, '1', '0', "00", x"CDEF");

    -- Returning to mapper 01 must not resurrect a bit written under another
    -- selector, and RegBus reset must restore CE to its hardware default.
    romtype <= x"01";
    tick;
    expect_port(16#CE#, 0);
    write_port(16#CE#, 1);
    expect_port(16#CE#, 1);
    reg_rst <= '1';
    tick;
    reg_rst <= '0';
    tick;
    expect_port(16#CE#, 0);
    cpu_addr <= to_unsigned(16#10020#, cpu_addr'length);
    cpu_read <= '1';
    cpu_write <= '0';
    cpu_be <= "00";
    expect_route(16#1000020#, 2, 16#000020#, '1', '0', "00", x"CDEF");

    report "PASS Bandai 2003 CE volatile flash routing" severity note;
    stop;
    wait;
  end process;
end architecture;
