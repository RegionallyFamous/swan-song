-- SPDX-License-Identifier: GPL-2.0-only
-- Exact RTC device-state capture/restore contract for Memories v2.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

use work.pRegisterBus.all;

entity rtc_state_tb is
end entity;

architecture test of rtc_state_tb is
  constant CLK_PERIOD : time := 10 ns;

  signal clk                 : std_logic := '0';
  signal reset               : std_logic := '1';
  signal timestamp_new       : std_logic := '0';
  signal timestamp_in        : std_logic_vector(31 downto 0) := x"DEADBEEF";
  signal timestamp_saved     : std_logic_vector(31 downto 0) := x"00000000";
  signal saved_time_in       : std_logic_vector(41 downto 0) := (others => '0');
  signal save_loaded         : std_logic := '0';
  signal timestamp_out       : std_logic_vector(31 downto 0);
  signal saved_time_out      : std_logic_vector(41 downto 0);
  signal state_freeze        : std_logic := '0';
  signal state_frozen        : std_logic;
  signal state_load          : std_logic := '0';
  signal state_data_in       : std_logic_vector(255 downto 0) := (others => '0');
  signal state_data_out      : std_logic_vector(255 downto 0);
  signal reg_din             : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_addr            : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_wren            : std_logic := '0';
  signal reg_rden            : std_logic := '0';
  signal reg_rst             : std_logic := '1';
  signal reg_dout            : std_logic_vector(7 downto 0);

  function clean(value : std_logic_vector) return boolean is
  begin
    for bit_index in value'range loop
      if value(bit_index) /= '0' and value(bit_index) /= '1' then
        return false;
      end if;
    end loop;
    return true;
  end function;

  function seed_image return std_logic_vector is
    variable image : std_logic_vector(255 downto 0) := (others => '0');
  begin
    image(255 downto 248) := x"15"; -- buffered read command
    image(247 downto 240) := x"A5"; -- exact read latch at capture
    image(234 downto 232) := "010"; -- buffer day is currently selected
    image(225) := '1';              -- read was high at the capture edge
    image(226) := '1';              -- host timestamp input was already high
    image(227) := '1';              -- do not refresh the buffer on release
    image(228) := '1';              -- legacy save input was already high
    image(223 downto 192) := x"10203040";
    image(191 downto 160) := x"00000000";
    image(159 downto 128) := std_logic_vector(to_unsigned(36863998, 32));

    -- Live calendar: 2026-07-13 weekday 3, 21:59:58.
    image(127 downto 120) := x"26";
    image(116 downto 112) := "00111";
    image(109 downto 104) := "010011";
    image(98 downto 96)   := "011";
    image(93 downto 88)   := "100001";
    image(86 downto 80)   := "1011001";
    image(78 downto 72)   := "1011000";

    -- Distinct buffered calendar: 2024-12-31 weekday 6, 23:58:57.
    image(71 downto 64) := x"24";
    image(60 downto 56) := "10010";
    image(53 downto 48) := "110001";
    image(42 downto 40) := "110";
    image(37 downto 32) := "100011";
    image(30 downto 24) := "1011000";
    image(22 downto 16) := "1010111";
    return image;
  end function;
begin
  clk <= not clk after CLK_PERIOD / 2;

  dut : entity work.rtc
    port map (
      clk                => clk,
      ce                 => '1',
      reset              => reset,
      hasRTC             => '1',
      RTC_timestampNew   => timestamp_new,
      RTC_timestampIn    => timestamp_in,
      RTC_timestampSaved => timestamp_saved,
      RTC_savedtimeIn    => saved_time_in,
      RTC_saveLoaded     => save_loaded,
      RTC_timestampOut   => timestamp_out,
      RTC_savedtimeOut   => saved_time_out,
      sleep_savestate    => '0',
      state_freeze       => state_freeze,
      state_frozen       => state_frozen,
      state_load         => state_load,
      state_data_in      => state_data_in,
      state_data_out     => state_data_out,
      RegBus_Din         => reg_din,
      RegBus_Adr         => reg_addr,
      RegBus_wren        => reg_wren,
      RegBus_rden        => reg_rden,
      RegBus_rst         => reg_rst,
      RegBus_Dout        => reg_dout
    );

  stimulus : process
    variable seed             : std_logic_vector(255 downto 0);
    variable captured_cut     : std_logic_vector(255 downto 0);
    variable rollover_result  : std_logic_vector(255 downto 0);
    variable transient_image  : std_logic_vector(255 downto 0);
    variable transient_cut    : std_logic_vector(255 downto 0);
    variable normalized_result : std_logic_vector(255 downto 0);
    variable command_10_image : std_logic_vector(255 downto 0);

    procedure tick(count : positive := 1) is
    begin
      for tick_index in 1 to count loop
        wait until rising_edge(clk);
        wait for 1 ns;
      end loop;
    end procedure;

    procedure request_freeze is
    begin
      wait until falling_edge(clk);
      state_freeze <= '1';
      tick;
      assert state_frozen = '1'
        report "RTC did not acknowledge a held capture edge" severity failure;
    end procedure;

    procedure release_for_one_edge is
    begin
      wait until falling_edge(clk);
      state_freeze <= '0';
      tick;
      assert state_frozen = '0'
        report "RTC freeze acknowledge did not release" severity failure;
    end procedure;

    procedure load_frozen(image : std_logic_vector(255 downto 0)) is
    begin
      assert state_frozen = '1'
        report "test attempted state load before freeze acknowledge" severity failure;
      wait until falling_edge(clk);
      state_data_in <= image;
      state_load <= '1';
      tick;
      state_load <= '0';
      assert state_data_out = image
        report "frozen RTC image did not round-trip exactly" severity failure;
    end procedure;
  begin
    -- Every exported bit is deterministic before Pocket's first 0090 seed.
    wait for 1 ns;
    assert clean(state_data_out)
      report "RTC export contains X/U before host timestamp seed" severity failure;
    assert timestamp_out = x"00000000"
      report "RTC epoch is not deterministic zero before host seed" severity failure;
    assert state_data_out(223 downto 192) = x"00000000"
      report "RTC state epoch is not deterministic zero before host seed" severity failure;

    -- Preserve the existing 0090 rising-edge contract even while the console
    -- reset is held: one host pulse seeds once, a held level does not follow.
    timestamp_in <= x"11223344";
    timestamp_new <= '1';
    tick;
    assert timestamp_out = x"11223344"
      report "first 0090 edge did not seed deterministic RTC epoch" severity failure;
    timestamp_in <= x"55667788";
    tick;
    assert timestamp_out = x"11223344"
      report "held 0090 level incorrectly followed the host epoch" severity failure;
    timestamp_new <= '0';
    tick;
    timestamp_in <= x"99AABBCC";
    timestamp_new <= '1';
    tick;
    assert timestamp_out = x"99AABBCC"
      report "later 0090 rising edge behavior was not preserved" severity failure;

    reset <= '0';
    reg_rst <= '0';

    seed := seed_image;
    state_data_in <= seed;
    state_load <= '1';
    request_freeze;

    -- The documented handshake rejects a load presented on the first request
    -- edge: only the next edge, after state_frozen is visible, may mutate.
    state_load <= '0';
    assert state_data_out /= seed
      report "RTC accepted state load before freeze acknowledge" severity failure;
    load_frozen(seed);
    assert state_data_out(239 downto 235) = "00000" and
           state_data_out(231 downto 229) = "000" and
           state_data_out(159 downto 154) = "000000" and
           state_data_out(119 downto 117) = "000" and
           state_data_out(111 downto 110) = "00" and
           state_data_out(103 downto 99) = "00000" and
           state_data_out(95 downto 94) = "00" and
           state_data_out(87) = '0' and state_data_out(79) = '0' and
           state_data_out(63 downto 61) = "000" and
           state_data_out(55 downto 54) = "00" and
           state_data_out(47 downto 43) = "00000" and
           state_data_out(39 downto 38) = "00" and
           state_data_out(31) = '0' and state_data_out(23) = '0' and
           state_data_out(15 downto 0) = x"0000"
      report "RTC byte image emitted non-canonical padding" severity failure;

    -- Host and CPU activity cannot mutate any RTC-owned sequential state while
    -- frozen, including its hidden eReg writeback flops.
    timestamp_new <= '1';
    save_loaded <= '1';
    reg_addr <= x"CA";
    reg_din <= x"10";
    reg_wren <= '1';
    reg_rden <= '1';
    reset <= '1';
    reg_rst <= '1';
    tick(3);
    assert state_data_out = seed
      report "RTC state changed under frozen bus/reset interruption" severity failure;
    reg_wren <= '0';
    reg_rden <= '0';
    reset <= '0';
    reg_rst <= '0';
    reg_addr <= x"CB";

    -- Resume the captured falling edge of an in-progress buffered read.  The
    -- edge history advances index 2 -> 3 while the old day byte is returned.
    release_for_one_edge;
    request_freeze;
    assert state_data_out(247 downto 240) = x"31"
      report "restored buffered read did not return captured day" severity failure;
    assert state_data_out(234 downto 232) = "011"
      report "restored buffered read did not advance to weekday" severity failure;
    assert state_data_out(223 downto 192) = x"10203040"
      report "restored timestamp edge history caused a false 0090 update" severity failure;
    assert state_data_out(159 downto 128) =
           std_logic_vector(to_unsigned(36863999, 32))
      report "restored RTC subsecond phase advanced by the wrong amount" severity failure;
    assert state_data_out(127 downto 72) = seed(127 downto 72)
      report "restored save edge history replayed legacy calendar load" severity failure;
    captured_cut := state_data_out;

    -- One more emulated edge must perform exactly the captured phase rollover:
    -- timestamp +1, phase zero, seconds 58 -> 59, and change latch set.
    release_for_one_edge;
    request_freeze;
    assert state_data_out(223 downto 192) = x"10203041"
      report "RTC timestamp did not increment at restored subsecond rollover" severity failure;
    assert state_data_out(159 downto 128) = x"00000000"
      report "RTC subsecond phase did not wrap to zero" severity failure;
    assert state_data_out(78 downto 72) = "1011001" and
           state_data_out(227) = '1'
      report "RTC live seconds/change latch did not resume at rollover" severity failure;
    rollover_result := state_data_out;

    -- Mutate, restore the prior cut, then replay the same edge.  Full-vector
    -- equality proves all protocol/live/buffer/subsecond fields are restored.
    release_for_one_edge;
    request_freeze;
    assert state_data_out /= rollover_result
      report "unfrozen RTC mutation phase did not alter the image" severity failure;
    load_frozen(captured_cut);
    release_for_one_edge;
    request_freeze;
    assert state_data_out = rollover_result
      report "RTC restore did not reproduce the exact rollover trajectory" severity failure;

    -- Software can write every implemented-width calendar value, and the RTL
    -- exposes a real transient between terminal tick and normalization.  A
    -- 0x59 second at terminal phase first becomes 0x5A; only the following
    -- emulated edge normalizes it to 0x60.  Capture/restore must preserve that
    -- non-BCD intermediate exactly rather than sanitizing it at the boundary.
    transient_image := seed;
    transient_image(255 downto 240) := x"0000";
    transient_image(239 downto 224) := (others => '0');
    transient_image(226) := '1';
    transient_image(228) := '1';
    transient_image(223 downto 192) := x"01020304";
    transient_image(159 downto 128) :=
      std_logic_vector(to_unsigned(36863999, 32));
    transient_image(78 downto 72) := "1011001"; -- 0x59
    load_frozen(transient_image);
    release_for_one_edge;
    request_freeze;
    assert state_data_out(78 downto 72) = "1011010" and
           state_data_out(223 downto 192) = x"01020305" and
           state_data_out(159 downto 128) = x"00000000" and
           state_data_out(227) = '1'
      report "RTC did not expose exact post-tick 0x5A transient" severity failure;
    transient_cut := state_data_out;

    release_for_one_edge;
    request_freeze;
    assert state_data_out(78 downto 72) = "1100000"
      report "RTC did not normalize restored-width 0x5A to 0x60" severity failure;
    normalized_result := state_data_out;

    load_frozen(transient_cut);
    assert state_data_out(78 downto 72) = "1011010"
      report "RTC state load sanitized the captured 0x5A transient" severity failure;
    release_for_one_edge;
    request_freeze;
    assert state_data_out = normalized_result
      report "RTC transient restore did not reproduce normalization edge" severity failure;

    -- Direct state loading of command 0x10 must not synthesize the command's
    -- software-write side effect.  Custom phase/calendar values survive the
    -- first released edge instead of being reset to 00-01-01 00:00:01.
    command_10_image := seed;
    command_10_image(255 downto 248) := x"10";
    command_10_image(247 downto 240) := x"00";
    command_10_image(234 downto 232) := "000";
    command_10_image(225) := '0';
    command_10_image(159 downto 128) := std_logic_vector(to_unsigned(123, 32));
    command_10_image(127 downto 120) := x"42";
    command_10_image(78 downto 72) := "0100110"; -- BCD 26
    load_frozen(command_10_image);
    release_for_one_edge;
    request_freeze;
    assert state_data_out(255 downto 248) = x"10" and
           state_data_out(127 downto 120) = x"42" and
           state_data_out(78 downto 72) = "0100110" and
           state_data_out(159 downto 128) =
             std_logic_vector(to_unsigned(124, 32))
      report "state load replayed RTC command-register side effects" severity failure;

    report "PASS rtc_state_tb" severity note;
    finish;
    wait;
  end process;
end architecture;
