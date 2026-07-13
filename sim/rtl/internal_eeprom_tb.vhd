-- SPDX-License-Identifier: GPL-2.0-only
-- Focused black-box checks for the WonderSwan internal EEPROM controller.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

use work.pRegisterBus.all;
use work.pBus_savestates.all;

entity internal_eeprom_tb is
end entity;

architecture test of internal_eeprom_tb is
  constant CLK_PERIOD : time := 10 ns;

  constant REG_DATA_LO : regmap_type := (16#BA#, 7, 0, 1, 0, readwrite);
  constant REG_DATA_HI : regmap_type := (16#BB#, 7, 0, 1, 0, readwrite);
  constant REG_CMD_LO  : regmap_type := (16#BC#, 7, 0, 1, 0, readwrite);
  constant REG_CMD_HI  : regmap_type := (16#BD#, 7, 0, 1, 0, readwrite);
  constant REG_CONTROL : regmap_type := (16#BE#, 7, 0, 1, 0, readwrite);
  constant REG_SS      : savestate_type :=
    (0, 16, 0, 1, x"0000000000000000");

  signal clk           : std_logic := '0';
  signal reset         : std_logic := '1';
  signal reg_din       : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_addr      : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_wren      : std_logic := '0';
  signal reg_rst       : std_logic := '1';
  signal reg_dout      : std_logic_vector(7 downto 0);
  signal written       : std_logic;
  signal ssbus_din     : std_logic_vector(63 downto 0) := (others => '0');
  signal ssbus_addr    : std_logic_vector(6 downto 0) := (others => '0');
  signal ssbus_wren    : std_logic := '0';
  signal ssbus_rst     : std_logic := '0';
  signal ssbus_dout    : std_logic_vector(63 downto 0);

  function masked(value : natural; mask : natural) return natural is
  begin
    return to_integer(to_unsigned(value, 8) and to_unsigned(mask, 8));
  end function;
begin
  clk <= not clk after CLK_PERIOD / 2;

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
      clk            => clk,
      clk_ram        => clk,
      ce             => '1',
      reset          => reset,
      isColor        => '0',
      ramtype        => x"00",
      written        => written,
      eeprom_addr    => (others => '0'),
      eeprom_din     => (others => '0'),
      eeprom_dout    => open,
      eeprom_req     => '0',
      eeprom_rnw     => '1',
      RegBus_Din     => reg_din,
      RegBus_Adr     => reg_addr,
      RegBus_wren    => reg_wren,
      RegBus_rst     => reg_rst,
      RegBus_Dout    => reg_dout,
      SSBus_Din      => ssbus_din,
      SSBus_Adr      => ssbus_addr,
      SSBus_wren     => ssbus_wren,
      SSBus_rst      => ssbus_rst,
      SSBus_Dout     => ssbus_dout
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
      write_port(16#BC#, command mod 256);
      write_port(16#BD#, command / 256);
    end procedure;

    procedure set_write_data(value : natural) is
    begin
      write_port(16#BA#, value mod 256);
      write_port(16#BB#, value / 256);
    end procedure;

    procedure wait_ready is
      variable status : natural;
    begin
      for index in 0 to 199 loop
        read_port(16#BE#, status);
        if masked(status, 2) /= 0 then
          return;
        end if;
        tick;
      end loop;
      assert false report "EEPROM controller did not become ready" severity failure;
    end procedure;

    procedure issue(command : natural; control : natural) is
    begin
      set_command(command);
      write_port(16#BE#, control);
      wait_ready;
    end procedure;

    procedure write_word(address : natural; value : natural) is
    begin
      set_write_data(value);
      issue(16#140# + address, 16#20#);
    end procedure;

    procedure read_word(
      address : natural;
      variable value : out natural;
      check_done_edge : boolean := false
    ) is
      variable lo     : natural;
      variable hi     : natural;
      variable status : natural;
      variable seen   : boolean := false;
    begin
      set_command(16#180# + address);
      write_port(16#BE#, 16#10#);
      if check_done_edge then
        read_port(16#BE#, status);
        assert masked(status, 1) = 0
          report "READ did not clear DONE immediately" severity failure;
      end if;
      for index in 0 to 15 loop
        read_port(16#BE#, status);
        if masked(status, 3) = 3 then
          seen := true;
          exit;
        end if;
        tick;
      end loop;
      assert seen report "READ did not set READY and DONE" severity failure;
      read_port(16#BA#, lo);
      read_port(16#BB#, hi);
      value := lo + hi * 256;
    end procedure;

    variable value  : natural;
    variable status : natural;
  begin
    reset <= '1';
    reg_rst <= '1';
    tick(3);
    reset <= '0';
    reg_rst <= '0';
    tick(72);

    read_port(16#BE#, status);
    assert masked(status, 16#7F#) = 3
      report "idle internal EEPROM status is not READY|DONE" severity failure;

    -- The deterministic mono initialization contains the protected
    -- WONDERSWAN signature beginning at byte offset 0x60 (word 0x30).
    read_word(16#30#, value, true);
    assert value = 16#1921#
      report "mono internal EEPROM signature was not initialized" severity failure;

    -- A write leaves the read-result latch untouched.
    write_word(0, 16#AA55#);
    read_port(16#BA#, value);
    assert value = 16#21#
      report "write data leaked into the low read-result latch" severity failure;
    read_word(0, value, true);
    assert value = 16#AA55# report "single-word write/read failed" severity failure;

    -- EWDS and EWEN are opcode-00 mode commands selected by OTHER.
    issue(16#100#, 16#40#);
    write_word(0, 16#55AA#);
    read_word(0, value);
    assert value = 16#AA55# report "EWDS did not lock writes" severity failure;
    issue(16#130#, 16#40#);
    write_word(0, 16#55AA#);
    read_word(0, value);
    assert value = 16#55AA# report "EWEN did not unlock writes" severity failure;

    -- WRAL consumes the write-data latch through WRITE; ERAL uses OTHER and
    -- writes erased words, not the stale write-data value.
    set_write_data(16#0F0F#);
    issue(16#110#, 16#20#);
    read_word(0, value);
    assert value = 16#0F0F# report "WRAL did not write the data latch" severity failure;
    read_word(1, value);
    assert value = 16#0F0F# report "WRAL did not cover the next word" severity failure;
    issue(16#120#, 16#40#);
    read_word(0, value);
    assert value = 16#FFFF# report "ERAL did not erase word zero" severity failure;
    read_word(1, value);
    assert value = 16#FFFF# report "ERAL did not erase word one" severity failure;

    -- Internal protection is sticky, reports bit 7, protects words at and
    -- above 0x30, and still permits the user area below that boundary.
    issue(0, 16#80#);
    read_port(16#BE#, status);
    assert masked(status, 16#83#) = 16#83#
      report "internal protection/status bits are incorrect" severity failure;
    read_word(16#30#, value);
    assert value = 16#FFFF# report "protected baseline read failed" severity failure;
    write_word(16#30#, 16#1234#);
    read_word(16#30#, value);
    assert value = 16#FFFF# report "protected word was modified" severity failure;
    write_word(0, 16#1234#);
    read_word(0, value);
    assert value = 16#1234# report "protection incorrectly covered user words" severity failure;

    -- Multi-operation control values are invalid and must leave the
    -- controller idle with reserved status bits clear.
    issue(0, 16#30#);
    read_port(16#BE#, status);
    assert masked(status, 16#7E#) = 2
      report "invalid control command changed READY/reserved status" severity failure;

    -- Loading a saved disabled-write latch before reset must not be replaced
    -- by the open-bootstrap initial state.
    issue(16#100#, 16#40#);
    wait until falling_edge(clk);
    ssbus_addr <= (others => '0');
    ssbus_din <= (others => '0');
    ssbus_wren <= '1';
    tick;
    ssbus_wren <= '0';
    reset <= '1';
    tick;
    reset <= '0';
    tick(72);
    write_word(0, 16#4321#);
    read_word(0, value);
    assert value = 0 report "savestate load did not restore EWDS" severity failure;
    issue(16#130#, 16#40#);
    write_word(0, 16#4321#);
    read_word(0, value);
    assert value = 16#4321# report "EWEN failed after savestate restore" severity failure;

    report "PASS internal EEPROM protocol checks" severity note;
    stop;
    wait;
  end process;
end architecture;
