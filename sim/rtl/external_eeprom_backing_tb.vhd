-- SPDX-License-Identifier: GPL-2.0-only
-- Elaborate and exercise the bankless 1024x16 cartridge EEPROM backing.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

use work.pRegisterBus.all;
use work.pBus_savestates.all;

entity external_eeprom_backing_tb is
end entity;

architecture test of external_eeprom_backing_tb is
  constant CPU_PERIOD : time := 10 ns;
  constant RAM_PERIOD : time := 7 ns;
  constant REG_DATA_LO : regmap_type := (16#BA#, 7, 0, 1, 0, readwrite);
  constant REG_DATA_HI : regmap_type := (16#BB#, 7, 0, 1, 0, readwrite);
  constant REG_CMD_LO  : regmap_type := (16#BC#, 7, 0, 1, 0, readwrite);
  constant REG_CMD_HI  : regmap_type := (16#BD#, 7, 0, 1, 0, readwrite);
  constant REG_CONTROL : regmap_type := (16#BE#, 7, 0, 1, 0, readwrite);
  constant REG_SS      : savestate_type :=
    (0, 16, 0, 1, x"0000000000000000");

  signal clk_cpu     : std_logic := '0';
  signal clk_ram     : std_logic := '0';
  signal reset       : std_logic := '1';
  signal bank        : std_logic := '0';
  signal address     : std_logic_vector(9 downto 0) := (others => '0');
  signal data_in     : std_logic_vector(15 downto 0) := (others => '0');
  signal data_out    : std_logic_vector(15 downto 0);
  signal request     : std_logic := '0';
  signal read_not_write : std_logic := '1';
  signal written     : std_logic;
  signal reg_out     : std_logic_vector(7 downto 0);
  signal ss_out      : std_logic_vector(63 downto 0);
begin
  clk_cpu <= not clk_cpu after CPU_PERIOD / 2;
  clk_ram <= not clk_ram after RAM_PERIOD / 2;

  dut : entity work.eeprom
    generic map (
      isExternal           => '1',
      defaultvalue         => x"FFFF",
      REG_Data_H           => REG_DATA_LO,
      REG_Data_L           => REG_DATA_HI,
      REG_Addr_H           => REG_CMD_LO,
      REG_Addr_L           => REG_CMD_HI,
      REG_Cmd              => REG_CONTROL,
      REG_SAVESTATE_EEPROM => REG_SS
    )
    port map (
      clk => clk_cpu, clk_ram => clk_ram, ce => '1', reset => reset,
      isColor => '0', preserve_on_reset => '0', ramtype => x"00",
      written => written, eeprom_bank => bank, eeprom_addr => address,
      eeprom_din => data_in, eeprom_dout => data_out,
      eeprom_req => request, eeprom_rnw => read_not_write,
      RegBus_Din => (others => '0'), RegBus_Adr => (others => '0'),
      RegBus_wren => '0', RegBus_rst => reset, RegBus_Dout => reg_out,
      SSBus_Din => (others => '0'), SSBus_Adr => (others => '0'),
      SSBus_wren => '0', SSBus_rst => '0', SSBus_Dout => ss_out
    );

  stimulus : process
    procedure host_write(
      bank_value : std_logic; word_address : natural; value : natural
    ) is
    begin
      wait until falling_edge(clk_ram);
      bank <= bank_value;
      address <= std_logic_vector(to_unsigned(word_address, address'length));
      data_in <= std_logic_vector(to_unsigned(value, data_in'length));
      read_not_write <= '0';
      request <= '1';
      wait until rising_edge(clk_ram);
      wait for 1 ns;
      request <= '0';
      read_not_write <= '1';
    end procedure;

    procedure host_read(
      bank_value : std_logic; word_address : natural; expected : natural
    ) is
    begin
      wait until falling_edge(clk_ram);
      bank <= bank_value;
      address <= std_logic_vector(to_unsigned(word_address, address'length));
      read_not_write <= '1';
      request <= '1';
      wait until rising_edge(clk_ram);
      wait for 1 ns;
      assert data_out = std_logic_vector(to_unsigned(expected, data_out'length))
        report "external EEPROM backing mismatch at word " &
               integer'image(word_address)
        severity failure;
      request <= '0';
    end procedure;
  begin
    wait until rising_edge(clk_cpu);
    wait until rising_edge(clk_cpu);
    reset <= '0';

    host_write('0', 0, 16#1020#);
    host_write('1', 63, 16#3040#);
    host_write('0', 511, 16#5060#);
    host_write('1', 1023, 16#7080#);

    -- The generic's bank input is intentionally ignored for cartridge EEPROM;
    -- opposite-bank reads must see the same single 1024-word allocation.
    host_read('1', 0, 16#1020#);
    host_read('0', 63, 16#3040#);
    host_read('1', 511, 16#5060#);
    host_read('0', 1023, 16#7080#);

    report "PASS external cartridge EEPROM remains bankless 1024x16";
    finish;
  end process;
end architecture;
