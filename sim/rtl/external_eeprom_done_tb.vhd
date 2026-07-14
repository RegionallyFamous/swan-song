-- SPDX-License-Identifier: GPL-2.0-only
-- Bandai 2001 cartridge EEPROM DONE-bit protocol checks.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

use work.pRegisterBus.all;
use work.pBus_savestates.all;

entity external_eeprom_done_tb is
end entity;

architecture test of external_eeprom_done_tb is
  constant CLK_PERIOD : time := 10 ns;

  constant REG_DATA_LO : regmap_type := (16#C4#, 7, 0, 1, 0, readwrite);
  constant REG_DATA_HI : regmap_type := (16#C5#, 7, 0, 1, 0, readwrite);
  constant REG_ADDR_LO : regmap_type := (16#C6#, 7, 0, 1, 0, readwrite);
  constant REG_ADDR_HI : regmap_type := (16#C7#, 7, 0, 1, 0, readwrite);
  constant REG_CONTROL : regmap_type := (16#C8#, 7, 0, 1, 0, readwrite);
  constant REG_SS      : savestate_type :=
    (0, 16, 0, 1, x"0000000000000000");

  signal clk        : std_logic := '0';
  signal reset      : std_logic := '1';
  signal ramtype    : std_logic_vector(7 downto 0) := x"10";
  signal reg_din    : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_addr   : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_wren   : std_logic := '0';
  signal reg_rst    : std_logic := '1';
  signal reg_dout   : std_logic_vector(7 downto 0);
  signal state_out  : std_logic_vector(127 downto 0);
  signal written    : std_logic;
begin
  clk <= not clk after CLK_PERIOD / 2;

  dut : entity work.eeprom
    generic map (
      isExternal           => '1',
      defaultvalue         => x"FFFF",
      REG_Data_H           => REG_DATA_LO,
      REG_Data_L           => REG_DATA_HI,
      REG_Addr_H           => REG_ADDR_LO,
      REG_Addr_L           => REG_ADDR_HI,
      REG_Cmd              => REG_CONTROL,
      REG_SAVESTATE_EEPROM => REG_SS
    )
    port map (
      clk               => clk,
      clk_ram           => clk,
      ce                => '1',
      reset             => reset,
      isColor           => '1',
      preserve_on_reset => '0',
      ramtype           => ramtype,
      written           => written,
      eeprom_bank       => '0',
      eeprom_addr       => (others => '0'),
      eeprom_din        => (others => '0'),
      eeprom_dout       => open,
      eeprom_req        => '0',
      eeprom_rnw        => '1',
      RegBus_Din        => reg_din,
      RegBus_Adr        => reg_addr,
      RegBus_wren       => reg_wren,
      RegBus_rst        => reg_rst,
      RegBus_Dout       => reg_dout,
      SSBus_Din         => (others => '0'),
      SSBus_Adr         => (others => '0'),
      SSBus_wren        => '0',
      SSBus_rst         => '0',
      SSBus_Dout        => open,
      state_out         => state_out
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

    procedure read_port(address : natural; variable value : out natural) is
    begin
      wait until falling_edge(clk);
      reg_addr <= std_logic_vector(to_unsigned(address, reg_addr'length));
      reg_wren <= '0';
      wait for 1 ns;
      value := to_integer(unsigned(reg_dout));
    end procedure;

    procedure set_command(command : natural) is
    begin
      write_port(16#C6#, command mod 256);
      write_port(16#C7#, command / 256);
    end procedure;

    procedure set_write_data(value : natural) is
    begin
      write_port(16#C4#, value mod 256);
      write_port(16#C5#, value / 256);
    end procedure;

    function masked(value : natural; mask : natural) return natural is
    begin
      return to_integer(to_unsigned(value, 8) and to_unsigned(mask, 8));
    end function;

    function read_command(size_words : natural; address : natural)
      return natural is
    begin
      if size_words = 64 then
        return 16#80# + address;
      end if;
      return 16#800# + address;
    end function;

    function write_command(size_words : natural; address : natural)
      return natural is
    begin
      if size_words = 64 then
        return 16#40# + address;
      end if;
      return 16#400# + address;
    end function;

    function write_enable_command(size_words : natural) return natural is
    begin
      if size_words = 64 then
        return 16#30#;
      end if;
      return 16#300#;
    end function;

    procedure wait_ready is
      variable status : natural;
    begin
      for index in 0 to 31 loop
        read_port(16#C8#, status);
        if masked(status, 2) /= 0 then
          return;
        end if;
        tick;
      end loop;
      assert false report "cartridge EEPROM did not become ready"
        severity failure;
    end procedure;

    procedure wait_read_complete(
      pending_done : natural;
      label_text   : string
    ) is
      variable status : natural;
      variable seen   : boolean := false;
    begin
      for index in 0 to 31 loop
        read_port(16#C8#, status);
        if masked(status, 2) /= 0 then
          assert masked(status, 1) = 1
            report label_text & ": completed READ did not set DONE"
            severity failure;
          seen := true;
          exit;
        end if;
        assert masked(status, 1) = pending_done
          report label_text & ": READ changed retained DONE while busy"
          severity failure;
        tick;
      end loop;
      assert seen report label_text & ": READ did not complete"
        severity failure;
    end procedure;

    variable ramtype_value : natural;
    variable size_words    : natural;
    variable last_address  : natural;
    variable status        : natural;
  begin
    for type_index in 0 to 2 loop
      case type_index is
        when 0 =>
          ramtype_value := 16#10#;
          size_words := 64;
        when 1 =>
          ramtype_value := 16#20#;
          size_words := 1024;
        when others =>
          ramtype_value := 16#50#;
          size_words := 512;
      end case;
      last_address := size_words - 1;

      wait until falling_edge(clk);
      ramtype <= std_logic_vector(to_unsigned(ramtype_value, ramtype'length));
      reset <= '1';
      reg_rst <= '1';
      tick(3);
      reset <= '0';
      reg_rst <= '0';
      tick(2);

      assert to_integer(unsigned(state_out(76 downto 66))) = size_words
        report "cartridge EEPROM type selected the wrong word capacity"
        severity failure;
      read_port(16#C8#, status);
      assert masked(status, 3) = 3
        report "cartridge EEPROM reset status is not READY|DONE"
        severity failure;

      -- A cartridge READ retains DONE=1 for its complete busy interval.
      set_command(read_command(size_words, last_address));
      write_port(16#C8#, 16#10#);
      assert state_out(61) = '1'
        report "cartridge READ cleared a previously-set DONE bit"
        severity failure;
      wait_read_complete(1, "retained-one cartridge READ");

      -- A valid WRITE clears DONE even while write protection suppresses the
      -- backing mutation. A following READ retains zero until it completes.
      set_write_data(16#A500# + type_index);
      set_command(write_command(size_words, last_address));
      write_port(16#C8#, 16#20#);
      assert state_out(61) = '0'
        report "cartridge WRITE did not clear DONE"
        severity failure;
      wait_ready;
      set_command(read_command(size_words, last_address));
      write_port(16#C8#, 16#10#);
      assert state_out(61) = '0'
        report "cartridge READ did not retain a previously-cleared DONE bit"
        severity failure;
      wait_read_complete(0, "retained-zero cartridge READ");

      -- SHORT/other commands clear DONE independently of their write-enable
      -- side effect.
      set_command(write_enable_command(size_words));
      write_port(16#C8#, 16#40#);
      assert state_out(61) = '0'
        report "cartridge SHORT/other command did not clear DONE"
        severity failure;
      wait_ready;
    end loop;

    report "PASS external EEPROM DONE protocol types=10/20/50 read=retained write/other=clear"
      severity note;
    stop;
    wait;
  end process;
end architecture;
