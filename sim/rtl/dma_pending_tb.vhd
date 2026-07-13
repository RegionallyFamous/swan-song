-- SPDX-License-Identifier: GPL-2.0-only
-- Direct black-box checks for Sound-DMA pending-request cancellation.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity dma_pending_tb is
end entity;

architecture test of dma_pending_tb is
  constant CLK_PERIOD : time := 10 ns;

  signal clk             : std_logic := '0';
  signal ce              : std_logic := '1';
  signal reset           : std_logic := '1';
  signal is_color        : std_logic := '1';
  signal dma_active      : std_logic;
  signal sdma_active     : std_logic;
  signal sdma_request    : std_logic;
  signal cpu_idle        : std_logic := '0';
  signal bus_read        : std_logic;
  signal bus_write       : std_logic;
  signal bus_be          : std_logic_vector(1 downto 0);
  signal bus_addr        : unsigned(19 downto 0);
  signal bus_datawrite   : std_logic_vector(15 downto 0);
  signal bus_dataread    : std_logic_vector(15 downto 0) := x"5AA5";
  signal sound_dma_value : std_logic_vector(7 downto 0);
  signal sound_dma_ch2   : std_logic;
  signal sound_dma_ch5   : std_logic;
  signal reg_din         : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_addr        : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_wren        : std_logic := '0';
  signal reg_rst         : std_logic := '1';
  signal reg_dout        : std_logic_vector(7 downto 0);
  signal sleep_savestate : std_logic := '0';
  signal ssbus_din       : std_logic_vector(63 downto 0) := (others => '0');
  signal ssbus_addr      : std_logic_vector(6 downto 0) := (others => '0');
  signal ssbus_wren      : std_logic := '0';
  signal ssbus_rst       : std_logic := '0';
  signal ssbus_dout      : std_logic_vector(63 downto 0);

  signal bus_read_count  : natural := 0;
  signal sdma_busy_count : natural := 0;
  signal ch2_write_count : natural := 0;
begin
  clk <= not clk after CLK_PERIOD / 2;

  dut : entity work.dma
    generic map (
      is_simu => '0'
    )
    port map (
      clk              => clk,
      ce               => ce,
      reset            => reset,
      isColor          => is_color,
      dma_active       => dma_active,
      sdma_active      => sdma_active,
      sdma_request     => sdma_request,
      cpu_idle         => cpu_idle,
      bus_read         => bus_read,
      bus_write        => bus_write,
      bus_be           => bus_be,
      bus_addr         => bus_addr,
      bus_datawrite    => bus_datawrite,
      bus_dataread     => bus_dataread,
      soundDMAvalue    => sound_dma_value,
      soundDMACh2      => sound_dma_ch2,
      soundDMACh5      => sound_dma_ch5,
      RegBus_Din       => reg_din,
      RegBus_Adr       => reg_addr,
      RegBus_wren      => reg_wren,
      RegBus_rst       => reg_rst,
      RegBus_Dout      => reg_dout,
      sleep_savestate  => sleep_savestate,
      SSBUS_Din        => ssbus_din,
      SSBUS_Adr        => ssbus_addr,
      SSBUS_wren       => ssbus_wren,
      SSBUS_rst        => ssbus_rst,
      SSBUS_Dout       => ssbus_dout
    );

  monitor : process (clk)
  begin
    if rising_edge(clk) then
      if bus_read = '1' then
        bus_read_count <= bus_read_count + 1;
      end if;
      if sdma_active = '1' then
        sdma_busy_count <= sdma_busy_count + 1;
      end if;
      if sound_dma_ch2 = '1' then
        ch2_write_count <= ch2_write_count + 1;
      end if;
    end if;
  end process;

  stimulus : process
    procedure tick(count : positive := 1) is
    begin
      for index in 1 to count loop
        wait until rising_edge(clk);
        wait for 1 ns;
      end loop;
    end procedure;

    procedure reset_dut is
    begin
      reset <= '1';
      reg_rst <= '1';
      reg_wren <= '0';
      cpu_idle <= '0';
      tick(3);
      reset <= '0';
      reg_rst <= '0';
      tick(2);
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

    procedure check_port(
      address : natural;
      expected : natural;
      description : string
    ) is
    begin
      wait until falling_edge(clk);
      reg_addr <= std_logic_vector(to_unsigned(address, reg_addr'length));
      reg_wren <= '0';
      wait for 1 ns;
      assert reg_dout = std_logic_vector(to_unsigned(expected, reg_dout'length))
        report description severity failure;
    end procedure;

    variable seen                 : boolean;
    variable reads_before         : natural;
    variable sdma_busy_before     : natural;
    variable ch2_writes_before    : natural;
  begin
    -- Case 1: a timer request is pending in IDLE because the CPU never grants
    -- the bus. A direct disable must consume that request without a transfer.
    reset_dut;
    write_port(16#4A#, 16#45#);
    write_port(16#4B#, 16#23#);
    write_port(16#4C#, 16#01#);
    write_port(16#4E#, 16#02#);
    write_port(16#4F#, 16#00#);
    write_port(16#50#, 16#00#);
    write_port(16#52#, 16#83#);

    seen := false;
    for index in 1 to 160 loop
      tick;
      if sdma_request = '1' then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen report "case 1 never produced a pending SDMA request" severity failure;
    assert sdma_active = '0' and bus_read = '0'
      report "case 1 transferred before the pending request was granted"
      severity failure;

    reads_before := bus_read_count;
    sdma_busy_before := sdma_busy_count;
    write_port(16#52#, 16#03#);
    assert sdma_request = '0'
      report "case 1 direct disable retained the pending request" severity failure;
    cpu_idle <= '1';
    tick(200);
    assert bus_read_count = reads_before and sdma_busy_count = sdma_busy_before
      report "case 1 released a canceled SDMA transfer" severity failure;
    assert sdma_request = '0' and sdma_active = '0' and bus_read = '0'
      report "case 1 did not remain quiescent after cancellation" severity failure;
    check_port(16#4A#, 16#45#, "case 1 changed the live source counter");
    check_port(16#4E#, 16#02#, "case 1 changed the live length counter");
    check_port(16#52#, 16#03#, "case 1 control did not remain disabled");

    -- Case 1b: rejecting an enabled write with live length zero is a separate
    -- cancellation path. It must also consume an already-pending request.
    reset_dut;
    write_port(16#4A#, 16#56#);
    write_port(16#4B#, 16#34#);
    write_port(16#4C#, 16#00#);
    write_port(16#4E#, 16#02#);
    write_port(16#4F#, 16#00#);
    write_port(16#50#, 16#00#);
    write_port(16#52#, 16#83#);

    seen := false;
    for index in 1 to 160 loop
      tick;
      if sdma_request = '1' then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen report "case 1b never produced a pending SDMA request" severity failure;
    assert sdma_active = '0' and bus_read = '0'
      report "case 1b transferred before zero-length rejection" severity failure;

    write_port(16#4E#, 16#00#);
    reads_before := bus_read_count;
    sdma_busy_before := sdma_busy_count;
    write_port(16#52#, 16#83#);
    assert sdma_request = '0'
      report "case 1b zero-length enable rejection retained the pending request"
      severity failure;
    check_port(16#52#, 16#03#, "case 1b zero-length enable was not rejected");
    cpu_idle <= '1';
    tick(200);
    assert bus_read_count = reads_before and sdma_busy_count = sdma_busy_before
      report "case 1b released a rejected zero-length SDMA transfer"
      severity failure;
    assert sdma_request = '0' and sdma_active = '0' and bus_read = '0'
      report "case 1b did not remain quiescent after rejection" severity failure;
    check_port(16#4A#, 16#56#, "case 1b changed the live source counter");
    check_port(16#4E#, 16#00#, "case 1b underflowed the live length counter");

    -- Case 2: let the SDMA timer expire while a long GDMA transfer owns the
    -- shared FSM. Disable in that non-SDMA state, finish GDMA, and prove the
    -- stale request cannot launch after the FSM returns to IDLE.
    reset_dut;
    write_port(16#4A#, 16#89#);
    write_port(16#4B#, 16#67#);
    write_port(16#4C#, 16#00#);
    write_port(16#4E#, 16#03#);
    write_port(16#4F#, 16#00#);
    write_port(16#50#, 16#00#);
    write_port(16#52#, 16#83#);

    write_port(16#40#, 16#00#);
    write_port(16#41#, 16#20#);
    write_port(16#42#, 16#00#);
    write_port(16#44#, 16#00#);
    write_port(16#45#, 16#10#);
    write_port(16#46#, 16#00#);
    write_port(16#47#, 16#02#);
    write_port(16#48#, 16#80#);
    assert dma_active = '1' report "case 2 GDMA did not start" severity failure;

    seen := false;
    for index in 1 to 180 loop
      tick;
      if sdma_request = '1' then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen report "case 2 never produced SDMA pending behind GDMA" severity failure;
    assert dma_active = '1' and sdma_active = '0'
      report "case 2 did not observe the request in the GDMA-owned FSM"
      severity failure;

    -- First exercise zero-length enable rejection while GDMA (not IDLE) owns
    -- the FSM, then restore and wait for a second pending request so the
    -- direct-disable branch is covered in the same GDMA transaction.
    write_port(16#4E#, 16#00#);
    write_port(16#52#, 16#83#);
    assert dma_active = '1'
      report "case 2 GDMA ended before zero-length rejection" severity failure;
    assert sdma_request = '0' and sdma_active = '0'
      report "case 2 zero-length rejection retained the GDMA-blocked request"
      severity failure;
    check_port(16#52#, 16#03#, "case 2 zero-length enable was not rejected");

    write_port(16#4E#, 16#03#);
    write_port(16#52#, 16#83#);
    seen := false;
    for index in 1 to 180 loop
      tick;
      if sdma_request = '1' then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen report "case 2 never produced the second pending request" severity failure;
    assert dma_active = '1' and sdma_active = '0'
      report "case 2 second request was not blocked behind GDMA" severity failure;

    sdma_busy_before := sdma_busy_count;
    write_port(16#52#, 16#03#);
    assert dma_active = '1'
      report "case 2 GDMA ended before the direct SDMA disable" severity failure;
    assert sdma_request = '0' and sdma_active = '0'
      report "case 2 direct disable retained the second GDMA-blocked request"
      severity failure;
    cpu_idle <= '1';

    seen := false;
    for index in 1 to 700 loop
      tick;
      if dma_active = '0' then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen report "case 2 GDMA did not finish" severity failure;
    reads_before := bus_read_count;
    tick(200);
    assert bus_read_count = reads_before and sdma_busy_count = sdma_busy_before
      report "case 2 launched stale SDMA work after GDMA returned IDLE"
      severity failure;
    assert sdma_request = '0' and sdma_active = '0' and bus_read = '0'
      report "case 2 did not remain quiescent after GDMA" severity failure;
    check_port(16#4A#, 16#89#, "case 2 changed the live SDMA source");
    check_port(16#4E#, 16#03#, "case 2 changed the live SDMA length");
    check_port(16#52#, 16#03#, "case 2 control did not remain disabled");

    -- Case 3: cancellation is not retroactive once a pending request has been
    -- granted into SDMA_READ. Observe the request, grant one CE, then apply
    -- disable on the following rising edge while SDMA_READ is current. That
    -- one issued read/sample must finish; no second transfer may begin.
    reset_dut;
    write_port(16#4A#, 16#A0#);
    write_port(16#4B#, 16#34#);
    write_port(16#4C#, 16#00#);
    write_port(16#4E#, 16#02#);
    write_port(16#4F#, 16#00#);
    write_port(16#50#, 16#00#);
    cpu_idle <= '0';
    reads_before := bus_read_count;
    sdma_busy_before := sdma_busy_count;
    ch2_writes_before := ch2_write_count;
    write_port(16#52#, 16#83#);

    seen := false;
    for index in 1 to 160 loop
      tick;
      if sdma_request = '1' then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen and sdma_active = '0' and bus_read = '0'
      report "case 3 never observed an ungranted pending request" severity failure;

    cpu_idle <= '1';
    tick;
    assert sdma_request = '1' and sdma_active = '0' and bus_read = '0'
      report "case 3 grant did not enter the pre-read FSM phase" severity failure;

    write_port(16#52#, 16#03#);
    assert sdma_active = '1' and bus_read = '1'
      report "case 3 disable prevented the already-granted read"
      severity failure;

    tick;
    assert sdma_active = '0' and bus_read = '0'
      report "case 3 issued read did not retire exactly once" severity failure;
    assert sound_dma_ch2 = '1' and sound_dma_value = x"A5"
      report "case 3 did not complete the issued Channel 2 sample" severity failure;
    assert bus_read_count = reads_before + 1 and
           sdma_busy_count = sdma_busy_before + 1
      report "case 3 did not execute exactly one issued SDMA read" severity failure;
    check_port(16#4A#, 16#A1#, "case 3 source did not advance exactly once");
    check_port(16#4E#, 16#01#, "case 3 length did not decrement exactly once");
    check_port(16#52#, 16#03#, "case 3 control did not remain disabled");

    tick;
    assert ch2_write_count = ch2_writes_before + 1
      report "case 3 did not produce exactly one Channel 2 write" severity failure;
    reads_before := bus_read_count;
    sdma_busy_before := sdma_busy_count;
    ch2_writes_before := ch2_write_count;
    tick(200);
    assert bus_read_count = reads_before and
           sdma_busy_count = sdma_busy_before and
           ch2_write_count = ch2_writes_before
      report "case 3 produced a second transfer after in-flight completion"
      severity failure;
    assert sdma_request = '0' and sdma_active = '0' and bus_read = '0'
      report "case 3 did not remain quiescent" severity failure;

    report "PASS dma_pending_tb pending cancellation and in-flight completion"
      severity note;
    stop;
    wait;
  end process;
end architecture;
