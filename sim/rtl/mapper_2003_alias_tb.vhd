-- SPDX-License-Identifier: GPL-2.0-only
-- Black-box coverage for the Bandai 2003 low-byte mapper aliases.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

use work.pRegisterBus.all;
use work.pBus_savestates.all;

entity mapper_2003_alias_tb is
end entity;

architecture test of mapper_2003_alias_tb is
  constant CLK_PERIOD : time := 10 ns;

  signal clk         : std_logic := '0';
  signal reset       : std_logic := '1';
  signal reg_rst     : std_logic := '1';
  signal romtype     : std_logic_vector(7 downto 0) := x"00";
  signal reg_din     : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_addr    : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_wren    : std_logic := '0';
  signal reg_dout    : std_logic_vector(7 downto 0);
  signal cpu_addr    : unsigned(19 downto 0) := (others => '0');
  signal debug_space : std_logic_vector(3 downto 0);
  signal debug_off   : std_logic_vector(23 downto 0);
  signal debug_valid : std_logic;
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
      maskAddr               => x"FFFFFF",
      romtype                => romtype,
      ramtype                => x"05",
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
      cpu_read               => '0',
      cpu_write              => '0',
      cpu_be                 => "00",
      cpu_addr               => cpu_addr,
      cpu_datawrite          => (others => '0'),
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
      EXTRAM_read            => open,
      EXTRAM_write           => open,
      EXTRAM_be              => open,
      EXTRAM_addr            => open,
      EXTRAM_datawrite       => open,
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
      reg_addr <= std_logic_vector(to_unsigned(address, reg_addr'length));
      reg_din <= std_logic_vector(to_unsigned(value, reg_din'length));
      reg_wren <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      reg_wren <= '0';
    end procedure;

    procedure expect_port(address : natural; expected : natural) is
    begin
      wait until falling_edge(clk);
      reg_addr <= std_logic_vector(to_unsigned(address, reg_addr'length));
      reg_wren <= '0';
      wait for 1 ns;
      assert to_integer(unsigned(reg_dout)) = expected
        report "mapper register readback mismatch at port " & integer'image(address)
        severity failure;
    end procedure;

    procedure expect_mapping(
      address        : natural;
      expected_space : natural;
      expected_off   : natural
    ) is
    begin
      cpu_addr <= to_unsigned(address, cpu_addr'length);
      wait for 1 ns;
      assert debug_valid = '1' report "mapper debug offset is not valid" severity failure;
      assert to_integer(unsigned(debug_space)) = expected_space
        report "mapper debug space mismatch" severity failure;
      assert to_integer(unsigned(debug_off)) = expected_off
        report "mapper debug offset mismatch" severity failure;
    end procedure;
  begin
    tick(3);
    reset <= '0';
    reg_rst <= '0';
    tick(2);

    -- Bandai 2001 must retain the inherited C0-C3-only decode.
    write_port(16#C0#, 1);
    write_port(16#CF#, 2);
    expect_port(16#C0#, 1);
    expect_port(16#CF#, 0);
    expect_mapping(16#40000#, 5, 16#140000#);

    -- Unknown footer values are not permission to decode Bandai 2003 ports.
    -- The independent ROM-size byte is intentionally 03h in this bench. An
    -- unsupported mapper selector must not be inferred from that byte.
    romtype <= x"03";
    reg_rst <= '1';
    tick;
    reg_rst <= '0';
    tick;
    write_port(16#C0#, 3);
    write_port(16#CF#, 4);
    expect_port(16#C0#, 3);
    expect_port(16#CF#, 0);
    expect_mapping(16#40000#, 5, 16#340000#);

    -- Select Bandai 2003 through the footer byte, then prove each alias has
    -- the same storage and resolved memory effect as its standard register.
    romtype <= x"01";
    reg_rst <= '1';
    tick;
    reg_rst <= '0';
    tick;

    expect_port(16#C0#, 16#FF#);
    expect_port(16#CF#, 16#FF#);
    expect_port(16#C1#, 16#FF#);
    expect_port(16#D0#, 16#FF#);
    expect_port(16#C2#, 16#FF#);
    expect_port(16#D2#, 16#FF#);
    expect_port(16#C3#, 16#FF#);
    expect_port(16#D4#, 16#FF#);

    write_port(16#CF#, 5);
    expect_port(16#CF#, 5);
    expect_port(16#C0#, 5);
    expect_mapping(16#40000#, 5, 16#540000#);

    write_port(16#D0#, 3);
    write_port(16#D1#, 0);
    expect_port(16#D0#, 3);
    expect_port(16#D1#, 0);
    expect_port(16#C1#, 3);
    expect_mapping(16#10000#, 2, 16#030000#);

    write_port(16#D2#, 6);
    write_port(16#D3#, 0);
    expect_port(16#D2#, 6);
    expect_port(16#D3#, 0);
    expect_port(16#C2#, 6);
    expect_mapping(16#20000#, 3, 16#060000#);

    write_port(16#D4#, 7);
    write_port(16#D5#, 0);
    expect_port(16#D4#, 7);
    expect_port(16#D5#, 0);
    expect_port(16#C3#, 7);
    expect_mapping(16#30000#, 4, 16#070000#);

    -- Writes through the original ports must also appear through aliases.
    write_port(16#C0#, 9);
    write_port(16#C1#, 2);
    write_port(16#C2#, 10);
    write_port(16#C3#, 11);
    expect_port(16#CF#, 9);
    expect_port(16#D0#, 2);
    expect_port(16#D2#, 10);
    expect_port(16#D4#, 11);

    report "PASS Bandai 2003 low-byte mapper aliases" severity note;
    stop;
    wait;
  end process;
end architecture;
