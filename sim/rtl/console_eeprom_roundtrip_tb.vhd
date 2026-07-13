-- SPDX-License-Identifier: GPL-2.0-only
-- Wrapper/model integration for Pocket's fixed console EEPROM slots.
--
-- The adjacent SystemVerilog initializer bench proves the real factory writer.
-- This bench applies that writer's complete output and models the APF slot
-- overlay/unloader around the real dual-clock, dual-bank EEPROM backing.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

use work.pRegisterBus.all;
use work.pBus_savestates.all;

entity console_eeprom_roundtrip_tb is
end entity;

architecture test of console_eeprom_roundtrip_tb is
  constant CPU_PERIOD : time := 10 ns;
  constant RAM_PERIOD : time := 7 ns;

  constant REG_DATA_LO : regmap_type := (16#BA#, 7, 0, 1, 0, readwrite);
  constant REG_DATA_HI : regmap_type := (16#BB#, 7, 0, 1, 0, readwrite);
  constant REG_CMD_LO  : regmap_type := (16#BC#, 7, 0, 1, 0, readwrite);
  constant REG_CMD_HI  : regmap_type := (16#BD#, 7, 0, 1, 0, readwrite);
  constant REG_CONTROL : regmap_type := (16#BE#, 7, 0, 1, 0, readwrite);
  constant REG_SS      : savestate_type :=
    (0, 16, 0, 1, x"0000000000000000");

  signal clk_cpu       : std_logic := '0';
  signal clk_ram       : std_logic := '0';
  signal reset         : std_logic := '1';
  signal is_color      : std_logic := '0';
  signal written       : std_logic;
  signal eeprom_bank   : std_logic := '0';
  signal eeprom_addr   : std_logic_vector(9 downto 0) := (others => '0');
  signal eeprom_din    : std_logic_vector(15 downto 0) := (others => '0');
  signal eeprom_dout   : std_logic_vector(15 downto 0);
  signal eeprom_req    : std_logic := '0';
  signal eeprom_rnw    : std_logic := '1';
  signal reg_dout      : std_logic_vector(7 downto 0);
  signal ssbus_dout    : std_logic_vector(63 downto 0);

  function factory_word(bank : std_logic; address : natural)
    return std_logic_vector is
    variable value : natural := 0;
  begin
    if bank = '0' then
      case address is
        when 16#30# => value := 16#1921#;
        when 16#31# => value := 16#0E18#;
        when 16#32# => value := 16#1C0F#;
        when 16#33# => value := 16#211D#;
        when 16#34# => value := 16#180B#;
        when 16#35# => value := 16#190D#;
        when 16#36# => value := 16#1916#;
        when 16#37# => value := 16#001C#;
        when 16#3B# => value := 16#0101#;
        when 16#3C# => value := 16#0027#;
        when 16#3E# => value := 16#0001#;
        when 16#40# => value := 16#0101#;
        when 16#41# => value := 16#0327#;
        when others => null;
      end case;
    else
      case address is
        when 16#30# => value := 16#1921#;
        when 16#31# => value := 16#0E18#;
        when 16#32# => value := 16#1C0F#;
        when 16#33# => value := 16#211D#;
        when 16#34# => value := 16#180B#;
        when 16#3B# => value := 16#0001#;
        when 16#3C# => value := 16#0024#;
        when 16#3E# => value := 16#0001#;
        when others => null;
      end case;
    end if;
    return std_logic_vector(to_unsigned(value, 16));
  end function;

  function slot_byte(bank : std_logic; address : natural) return natural is
  begin
    if bank = '1' then
      return (address * 37 + 16#5A#) mod 256;
    end if;
    return (address * 73 + 16#C3#) mod 256;
  end function;

  function slot_word(bank : std_logic; address : natural)
    return std_logic_vector is
    variable low_byte  : natural;
    variable high_byte : natural;
  begin
    low_byte := slot_byte(bank, address * 2);
    high_byte := slot_byte(bank, address * 2 + 1);
    return std_logic_vector(to_unsigned(low_byte + high_byte * 256, 16));
  end function;
begin
  clk_cpu <= not clk_cpu after CPU_PERIOD / 2;
  clk_ram <= not clk_ram after RAM_PERIOD / 2;

  dut : entity work.eeprom
    generic map (
      isExternal           => '0',
      defaultvalue         => x"0000",
      REG_Data_H           => REG_DATA_LO,
      REG_Data_L           => REG_DATA_HI,
      REG_Addr_H           => REG_CMD_LO,
      REG_Addr_L           => REG_CMD_HI,
      REG_Cmd              => REG_CONTROL,
      REG_SAVESTATE_EEPROM => REG_SS
    )
    port map (
      clk            => clk_cpu,
      clk_ram        => clk_ram,
      ce             => '1',
      reset          => reset,
      isColor        => is_color,
      preserve_on_reset => '1',
      ramtype        => x"00",
      written        => written,
      eeprom_bank    => eeprom_bank,
      eeprom_addr    => eeprom_addr,
      eeprom_din     => eeprom_din,
      eeprom_dout    => eeprom_dout,
      eeprom_req     => eeprom_req,
      eeprom_rnw     => eeprom_rnw,
      RegBus_Din     => (others => '0'),
      RegBus_Adr     => (others => '0'),
      RegBus_wren    => '0',
      RegBus_rst     => reset,
      RegBus_Dout    => reg_dout,
      SSBus_Din      => (others => '0'),
      SSBus_Adr      => (others => '0'),
      SSBus_wren     => '0',
      SSBus_rst      => '0',
      SSBus_Dout     => ssbus_dout
    );

  stimulus : process
    procedure tick_cpu(count : positive := 1) is
    begin
      for index in 1 to count loop
        wait until rising_edge(clk_cpu);
        wait for 1 ns;
      end loop;
    end procedure;

    procedure host_write_word(
      bank : std_logic; address : natural; value : std_logic_vector(15 downto 0)
    ) is
    begin
      wait until falling_edge(clk_ram);
      eeprom_bank <= bank;
      eeprom_addr <= std_logic_vector(to_unsigned(address, eeprom_addr'length));
      eeprom_din <= value;
      eeprom_rnw <= '0';
      eeprom_req <= '1';
      wait until rising_edge(clk_ram);
      wait for 1 ns;
      eeprom_req <= '0';
      eeprom_rnw <= '1';
    end procedure;

    procedure host_read_word(
      bank : std_logic; address : natural;
      variable value : out std_logic_vector(15 downto 0)
    ) is
    begin
      wait until falling_edge(clk_ram);
      eeprom_bank <= bank;
      eeprom_addr <= std_logic_vector(to_unsigned(address, eeprom_addr'length));
      eeprom_rnw <= '1';
      eeprom_req <= '1';
      wait until rising_edge(clk_ram);
      wait for 1 ns;
      value := eeprom_dout;
      eeprom_req <= '0';
    end procedure;

    procedure seed_factory is
    begin
      for address in 0 to 1023 loop
        host_write_word('0', address, factory_word('0', address));
      end loop;
      for address in 0 to 63 loop
        host_write_word('1', address, factory_word('1', address));
      end loop;
    end procedure;

    procedure overlay_slot(bank : std_logic; words : positive) is
    begin
      for address in 0 to words - 1 loop
        host_write_word(bank, address, slot_word(bank, address));
      end loop;
    end procedure;

    procedure unload_and_check(
      bank : std_logic; words : positive; expected_factory : boolean
    ) is
      variable value       : std_logic_vector(15 downto 0);
      variable bytes_read  : natural := 0;
      variable expected    : std_logic_vector(15 downto 0);
    begin
      for address in 0 to words - 1 loop
        host_read_word(bank, address, value);
        if expected_factory then
          expected := factory_word(bank, address);
        else
          expected := slot_word(bank, address);
        end if;
        assert value = expected
          report "console EEPROM unload mismatch bank=" & std_logic'image(bank) &
                 " word=" & integer'image(address)
          severity failure;
        assert to_integer(unsigned(value(7 downto 0))) =
                 (to_integer(unsigned(expected(7 downto 0)))) and
               to_integer(unsigned(value(15 downto 8))) =
                 (to_integer(unsigned(expected(15 downto 8))))
          report "console EEPROM byte order mismatch" severity failure;
        bytes_read := bytes_read + 2;
      end loop;
      if bank = '1' then
        assert bytes_read = 128
          report "mono unloader length was not exactly 128 bytes" severity failure;
      else
        assert bytes_read = 2048
          report "Color unloader length was not exactly 2048 bytes" severity failure;
      end if;
    end procedure;

    variable value : std_logic_vector(15 downto 0);
  begin
    -- Factory creation spans all Color words and exactly 64 mono words.
    seed_factory;
    unload_and_check('0', 1024, true);
    unload_and_check('1', 64, true);
    host_read_word('1', 64, value);
    assert value = x"0000"
      report "factory seed escaped the exact 128-byte mono image" severity failure;

    -- Existing fixed-name APF slots overlay the seed before execution.
    overlay_slot('1', 64);
    overlay_slot('0', 1024);
    unload_and_check('1', 64, false);
    unload_and_check('0', 1024, false);

    -- Both model selections address their own resident bank, and an ordinary
    -- reset must preserve both complete overlaid images.
    reset <= '0';
    tick_cpu(4);
    is_color <= '1';
    tick_cpu(3);
    is_color <= '0';
    tick_cpu(3);
    reset <= '1';
    tick_cpu(3);
    reset <= '0';
    tick_cpu(4);
    unload_and_check('0', 1024, false);
    unload_and_check('1', 64, false);

    report "PASS console EEPROM factory/overlay/dual-clock/exact-unload round trip";
    finish;
  end process;
end architecture;
