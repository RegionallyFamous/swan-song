-- SPDX-License-Identifier: GPL-2.0-only
-- Direct black-box checks for the versioned Sound-DMA save-state extension.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity dma_savestate_tb is
end entity;

architecture test of dma_savestate_tb is
  constant CLK_PERIOD : time := 10 ns;

  constant SS_SDMA_LEGACY : natural := 17;
  constant SS_SDMA_EXT    : natural := 18;

  -- Slot 18 is deliberately versioned: an all-zero slot remains recognizable
  -- as a save made before the extension existed.
  constant EXT_VERSION  : std_logic_vector(2 downto 0) := "001";
  constant STATE_IDLE   : std_logic_vector(2 downto 0) := "000";
  constant STATE_SREAD  : std_logic_vector(2 downto 0) := "101";

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

    procedure cold_reset is
    begin
      wait until falling_edge(clk);
      reset <= '1';
      reg_rst <= '1';
      ssbus_rst <= '1';
      reg_wren <= '0';
      ssbus_wren <= '0';
      sleep_savestate <= '0';
      ce <= '1';
      cpu_idle <= '0';
      tick(3);
      wait until falling_edge(clk);
      reset <= '0';
      reg_rst <= '0';
      ssbus_rst <= '0';
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

    procedure write_ss(address : natural; value : std_logic_vector(63 downto 0)) is
    begin
      wait until falling_edge(clk);
      ssbus_addr <= std_logic_vector(to_unsigned(address, ssbus_addr'length));
      ssbus_din <= value;
      ssbus_wren <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      ssbus_wren <= '0';
    end procedure;

    procedure read_ss(
      address : natural;
      variable value : out std_logic_vector(63 downto 0)
    ) is
    begin
      wait until falling_edge(clk);
      ssbus_addr <= std_logic_vector(to_unsigned(address, ssbus_addr'length));
      ssbus_wren <= '0';
      wait for 1 ns;
      value := ssbus_dout;
    end procedure;

    procedure freeze is
    begin
      wait until falling_edge(clk);
      ce <= '0';
      sleep_savestate <= '1';
      reg_wren <= '0';
      wait for 1 ns;
    end procedure;

    procedure resume is
    begin
      wait until falling_edge(clk);
      sleep_savestate <= '0';
      ce <= '1';
      wait for 1 ns;
    end procedure;

    procedure capture_state(
      variable legacy : out std_logic_vector(63 downto 0);
      variable extension : out std_logic_vector(63 downto 0)
    ) is
    begin
      freeze;
      read_ss(SS_SDMA_LEGACY, legacy);
      read_ss(SS_SDMA_EXT, extension);
      -- Mirror the real save engine: each combinational snapshot is written
      -- into the eReg_SS load buffer that will later feed reset restoration.
      write_ss(SS_SDMA_LEGACY, legacy);
      write_ss(SS_SDMA_EXT, extension);
    end procedure;

    procedure restore_state(
      legacy : std_logic_vector(63 downto 0);
      extension : std_logic_vector(63 downto 0)
    ) is
    begin
      freeze;
      write_ss(SS_SDMA_LEGACY, legacy);
      write_ss(SS_SDMA_EXT, extension);
      wait until falling_edge(clk);
      -- The production load engine performs its final reset after all SS bus
      -- words have been loaded, without asserting the register cold-reset.
      reset <= '1';
      reg_rst <= '0';
      tick;
      reset <= '0';
      wait for 1 ns;
    end procedure;

    function legacy_word(
      live_len : natural;
      live_src : natural;
      control : natural
    ) return std_logic_vector is
      variable result : std_logic_vector(63 downto 0) := (others => '0');
    begin
      result(19 downto 0) := std_logic_vector(to_unsigned(live_len, 20));
      result(51 downto 32) := std_logic_vector(to_unsigned(live_src, 20));
      result(59 downto 52) := std_logic_vector(to_unsigned(control, 8));
      return result;
    end function;

    procedure check_ext_header(
      value : std_logic_vector(63 downto 0);
      description : string
    ) is
    begin
      assert value(63) = '1'
        report description & ": valid flag was not set" severity failure;
      assert value(62 downto 60) = EXT_VERSION
        report description & ": version was not 1" severity failure;
      assert value(59 downto 54) = "000000"
        report description & ": reserved bits were not zero" severity failure;
    end procedure;

    procedure check_ext_payload(
      value : std_logic_vector(63 downto 0);
      reload_len : natural;
      reload_src : natural;
      timer : natural;
      pending : std_logic;
      state_code : std_logic_vector(2 downto 0);
      description : string
    ) is
    begin
      check_ext_header(value, description);
      assert unsigned(value(19 downto 0)) = reload_len
        report description & ": reload length mismatch" severity failure;
      assert unsigned(value(39 downto 20)) = reload_src
        report description & ": reload source mismatch" severity failure;
      assert unsigned(value(49 downto 40)) = timer
        report description & ": timer phase mismatch" severity failure;
      assert value(50) = pending
        report description & ": pending bit mismatch" severity failure;
      assert value(53 downto 51) = state_code
        report description & ": state code mismatch" severity failure;
    end procedure;

    procedure program_sdma(
      source : natural;
      length : natural;
      control : natural
    ) is
    begin
      write_port(16#4A#, source mod 256);
      write_port(16#4B#, (source / 256) mod 256);
      write_port(16#4C#, (source / 65536) mod 16);
      write_port(16#4E#, length mod 256);
      write_port(16#4F#, (length / 256) mod 256);
      write_port(16#50#, (length / 65536) mod 16);
      write_port(16#52#, control);
    end procedure;

    variable saved_legacy       : std_logic_vector(63 downto 0);
    variable saved_extension    : std_logic_vector(63 downto 0);
    variable observed_extension : std_logic_vector(63 downto 0);
    variable malformed          : std_logic_vector(63 downto 0);
    variable seen               : boolean;
    variable reads_before       : natural;
    variable writes_before      : natural;
  begin
    -------------------------------------------------------------------------
    -- Case 1: slot 18 has a self-identifying, fully specified wire layout.
    -------------------------------------------------------------------------
    cold_reset;
    program_sdma(16#12345#, 16#00234#, 16#8B#);
    tick(37);
    capture_state(saved_legacy, saved_extension);
    check_ext_payload(
      saved_extension, 16#00234#, 16#12345#, 37, '0', STATE_IDLE,
      "case 1 versioned slot"
    );
    assert saved_legacy(31 downto 20) = x"000" and
           saved_legacy(63 downto 60) = "0000"
      report "case 1 legacy reserved bits changed" severity failure;

    -------------------------------------------------------------------------
    -- Case 2: restore the exact nonzero timer phase.  From phase 37 at the
    -- fastest rate, 90 clocks merely reach phase 127 and clock 91 requests.
    -------------------------------------------------------------------------
    resume;
    tick(100);
    restore_state(saved_legacy, saved_extension);
    assert sdma_request = '0' and sdma_active = '0' and bus_read = '0'
      report "case 2 restore was not quiescent at phase 37" severity failure;
    resume;
    for index in 1 to 90 loop
      tick;
      assert sdma_request = '0'
        report "case 2 timer request arrived before the exact restored phase"
        severity failure;
    end loop;
    tick;
    assert sdma_request = '1' and sdma_active = '0' and bus_read = '0'
      report "case 2 timer request did not arrive on restored phase clock 91"
      severity failure;

    -------------------------------------------------------------------------
    -- Case 3: live counters can diverge from repeat shadows.  Both halves
    -- survive a restore, and terminal repeat reload uses the saved shadows.
    -------------------------------------------------------------------------
    cold_reset;
    cpu_idle <= '1';
    program_sdma(16#24680#, 3, 16#8B#);
    writes_before := ch2_write_count;
    seen := false;
    for index in 1 to 180 loop
      tick;
      if ch2_write_count = writes_before + 1 then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen report "case 3 first transfer did not complete" severity failure;
    check_port(16#4A#, 16#81#, "case 3 live source did not diverge");
    check_port(16#4E#, 2, "case 3 live length did not diverge");
    capture_state(saved_legacy, saved_extension);
    check_ext_header(saved_extension, "case 3 saved extension");
    assert unsigned(saved_extension(19 downto 0)) = 3 and
           unsigned(saved_extension(39 downto 20)) = 16#24680#
      report "case 3 repeat shadows did not remain at programmed values"
      severity failure;
    assert unsigned(saved_legacy(19 downto 0)) = 2 and
           unsigned(saved_legacy(51 downto 32)) = 16#24681#
      report "case 3 legacy slot did not contain divergent live counters"
      severity failure;

    -- Destroy both live and shadow values, then restore the divergent pair.
    resume;
    write_port(16#52#, 16#03#);
    program_sdma(16#37770#, 7, 16#03#);
    restore_state(saved_legacy, saved_extension);
    check_port(16#4A#, 16#81#, "case 3 live source was not restored");
    check_port(16#4E#, 2, "case 3 live length was not restored");
    writes_before := ch2_write_count;
    resume;
    seen := false;
    for index in 1 to 330 loop
      tick;
      if ch2_write_count = writes_before + 2 then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen report "case 3 terminal repeat did not complete" severity failure;
    check_port(16#4A#, 16#80#, "case 3 repeat did not restore shadow source");
    check_port(16#4B#, 16#46#, "case 3 repeat source middle byte mismatch");
    check_port(16#4C#, 16#02#, "case 3 repeat source high byte mismatch");
    check_port(16#4E#, 3, "case 3 repeat did not restore shadow length");
    check_port(16#52#, 16#8B#, "case 3 repeat unexpectedly disabled SDMA");

    -- The extension is necessary, not redundant.  Restoring the same
    -- divergent legacy word with an old all-zero slot 18 must use the only
    -- information available: the live counters become the reload shadows.
    -- Its next terminal repeat therefore collapses to 0x24681/2 rather than
    -- recovering the versioned 0x24680/3 reload pair proven above.
    restore_state(saved_legacy, (63 downto 0 => '0'));
    read_ss(SS_SDMA_EXT, observed_extension);
    check_ext_payload(
      observed_extension, 2, 16#24681#, 0, '0', STATE_IDLE,
      "case 3 legacy collapse evidence"
    );
    writes_before := ch2_write_count;
    cpu_idle <= '1';
    resume;
    seen := false;
    for index in 1 to 330 loop
      tick;
      if ch2_write_count = writes_before + 2 then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen report "case 3 legacy-collapse repeat did not complete"
      severity failure;
    check_port(16#4A#, 16#81#, "case 3 legacy fallback did not use live source");
    check_port(16#4E#, 2, "case 3 legacy fallback did not use live length");

    -------------------------------------------------------------------------
    -- Case 4: a timer request pending in IDLE remains pending after restore,
    -- but has not silently become an issued bus transaction.
    -------------------------------------------------------------------------
    cold_reset;
    cpu_idle <= '0';
    program_sdma(16#34560#, 2, 16#83#);
    seen := false;
    for index in 1 to 140 loop
      tick;
      if sdma_request = '1' then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen and sdma_active = '0' and bus_read = '0'
      report "case 4 did not reach pending IDLE" severity failure;
    capture_state(saved_legacy, saved_extension);
    check_ext_payload(
      saved_extension, 2, 16#34560#, 0, '1', STATE_IDLE,
      "case 4 pending-IDLE slot"
    );
    resume;
    cpu_idle <= '1';
    tick(4);
    restore_state(saved_legacy, saved_extension);
    cpu_idle <= '0';
    assert sdma_request = '1' and sdma_active = '0' and bus_read = '0'
      report "case 4 pending IDLE was not restored exactly" severity failure;
    reads_before := bus_read_count;
    cpu_idle <= '1';
    resume;
    tick;
    assert bus_read = '0' and sdma_request = '1'
      report "case 4 grant skipped the restored pre-read phase" severity failure;
    tick;
    assert bus_read = '1' and sdma_active = '1' and
           bus_addr = to_unsigned(16#34560#, bus_addr'length)
      report "case 4 restored request did not issue its one expected read"
      severity failure;
    tick(2);
    assert bus_read_count = reads_before + 1 and bus_read = '0' and
           sdma_request = '0' and sdma_active = '0'
      report "case 4 restored pending request did not retire exactly once"
      severity failure;

    -------------------------------------------------------------------------
    -- Case 5: SDMA_READ is the sole legal in-flight save point.  Restoring it
    -- must issue exactly the read that had been granted, neither zero nor two.
    -------------------------------------------------------------------------
    cold_reset;
    cpu_idle <= '0';
    program_sdma(16#45670#, 2, 16#83#);
    seen := false;
    for index in 1 to 140 loop
      tick;
      if sdma_request = '1' then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen report "case 5 did not produce a pending request" severity failure;
    cpu_idle <= '1';
    tick;
    assert sdma_request = '1' and sdma_active = '0' and bus_read = '0'
      report "case 5 did not reach pre-bus SDMA_READ" severity failure;
    capture_state(saved_legacy, saved_extension);
    check_ext_payload(
      saved_extension, 2, 16#45670#, 1, '1', STATE_SREAD,
      "case 5 pre-bus slot"
    );
    resume;
    tick(3);
    restore_state(saved_legacy, saved_extension);
    assert sdma_request = '1' and sdma_active = '0' and bus_read = '0'
      report "case 5 did not restore the pre-bus phase" severity failure;
    reads_before := bus_read_count;
    resume;
    tick;
    assert bus_read = '1' and sdma_active = '1' and
           bus_addr = to_unsigned(16#45670#, bus_addr'length)
      report "case 5 restored pre-bus phase did not issue its read"
      severity failure;
    tick;
    assert bus_read = '0' and sdma_active = '0' and sound_dma_ch2 = '1' and
           sound_dma_value = x"A5"
      report "case 5 restored pre-bus read did not complete its sample"
      severity failure;
    tick;
    assert bus_read_count = reads_before + 1
      report "case 5 restored pre-bus phase did not read exactly once"
      severity failure;
    check_port(16#4A#, 16#71#, "case 5 source did not advance exactly once");
    check_port(16#4E#, 1, "case 5 length did not decrement exactly once");

    -- A control disable is allowed after the request has entered SDMA_READ.
    -- With CE stopped, create and save that precise granted-but-not-issued
    -- state.  Restore must finish the one committed sample even though CTRL
    -- is disabled, then remain disabled with no second transfer.
    cold_reset;
    cpu_idle <= '0';
    program_sdma(16#4A680#, 2, 16#83#);
    seen := false;
    for index in 1 to 140 loop
      tick;
      if sdma_request = '1' then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen report "case 5b did not produce a pending request" severity failure;
    cpu_idle <= '1';
    tick;
    assert sdma_request = '1' and bus_read = '0' and sdma_active = '0'
      report "case 5b did not reach pre-bus SDMA_READ" severity failure;
    wait until falling_edge(clk);
    ce <= '0';
    write_port(16#52#, 16#03#);
    assert sdma_request = '1' and bus_read = '0' and sdma_active = '0'
      report "case 5b disable did not retain the granted pre-bus transfer"
      severity failure;
    check_port(16#52#, 16#03#, "case 5b control did not disable");
    capture_state(saved_legacy, saved_extension);
    check_ext_payload(
      saved_extension, 2, 16#4A680#, 1, '1', STATE_SREAD,
      "case 5b disabled pre-bus slot"
    );
    assert saved_legacy(59) = '0'
      report "case 5b legacy slot did not save disabled control" severity failure;

    -- First consume the original to distinguish the later restored read.
    reads_before := bus_read_count;
    resume;
    tick(4);
    assert bus_read_count = reads_before + 1
      report "case 5b original disabled transfer did not retire once"
      severity failure;
    restore_state(saved_legacy, saved_extension);
    assert sdma_request = '1' and bus_read = '0' and sdma_active = '0'
      report "case 5b disabled pre-bus transfer was not restored"
      severity failure;
    reads_before := bus_read_count;
    writes_before := ch2_write_count;
    resume;
    tick;
    assert bus_read = '1' and sdma_active = '1' and
           bus_addr = to_unsigned(16#4A680#, bus_addr'length)
      report "case 5b restored disabled transfer did not issue its read"
      severity failure;
    tick;
    assert bus_read = '0' and sdma_active = '0' and sound_dma_ch2 = '1' and
           sound_dma_value = x"A5"
      report "case 5b restored disabled transfer did not complete its sample"
      severity failure;
    tick(2);
    assert bus_read_count = reads_before + 1 and
           ch2_write_count = writes_before + 1
      report "case 5b restored disabled transfer did not retire exactly once"
      severity failure;
    check_port(16#4A#, 16#81#, "case 5b source did not advance exactly once");
    check_port(16#4E#, 1, "case 5b length did not decrement exactly once");
    check_port(16#52#, 16#03#, "case 5b control did not remain disabled");
    reads_before := bus_read_count;
    writes_before := ch2_write_count;
    tick(200);
    assert bus_read_count = reads_before and ch2_write_count = writes_before and
           sdma_request = '0' and sdma_active = '0' and bus_read = '0'
      report "case 5b produced a second transfer after disabled completion"
      severity failure;

    -------------------------------------------------------------------------
    -- Case 6: an all-zero slot 18 is an old save, not a version-1 payload.
    -- Live slot-17 counters become repeat shadows; timer/request/FSM restart
    -- safely at zero/clear/IDLE.  A repeat proves the inferred shadows.
    -------------------------------------------------------------------------
    cold_reset;
    saved_legacy := legacy_word(1, 16#56780#, 16#8B#);
    restore_state(saved_legacy, (63 downto 0 => '0'));
    assert sdma_request = '0' and sdma_active = '0' and bus_read = '0'
      report "case 6 legacy fallback did not restore clear IDLE" severity failure;
    read_ss(SS_SDMA_EXT, observed_extension);
    check_ext_payload(
      observed_extension, 1, 16#56780#, 0, '0', STATE_IDLE,
      "case 6 synthesized legacy extension"
    );
    check_port(16#4A#, 16#80#, "case 6 legacy live source low mismatch");
    check_port(16#4B#, 16#67#, "case 6 legacy live source middle mismatch");
    check_port(16#4C#, 16#05#, "case 6 legacy live source high mismatch");
    check_port(16#4E#, 1, "case 6 legacy live length mismatch");
    cpu_idle <= '1';
    writes_before := ch2_write_count;
    resume;
    for index in 1 to 127 loop
      tick;
      assert sdma_request = '0'
        report "case 6 legacy timer did not restart from zero" severity failure;
    end loop;
    tick;
    assert sdma_request = '1'
      report "case 6 legacy timer did not request at phase 128" severity failure;
    seen := false;
    for index in 1 to 8 loop
      tick;
      if ch2_write_count = writes_before + 1 then
        seen := true;
        exit;
      end if;
    end loop;
    assert seen report "case 6 legacy repeat transfer did not finish" severity failure;
    check_port(16#4A#, 16#80#, "case 6 fallback repeat source was not live source");
    check_port(16#4E#, 1, "case 6 fallback repeat length was not live length");

    -------------------------------------------------------------------------
    -- Case 7: invalid header variants select the same legacy fallback, while
    -- a valid header carrying an illegal state only fails that state to IDLE.
    -------------------------------------------------------------------------
    saved_legacy := legacy_word(5, 16#67890#, 16#83#);
    malformed := (others => '0');
    malformed(63) := '1';
    malformed(62 downto 60) := EXT_VERSION;
    malformed(54) := '1';             -- reserved-nonzero invalidates slot
    malformed(19 downto 0) := std_logic_vector(to_unsigned(9, 20));
    malformed(39 downto 20) := std_logic_vector(to_unsigned(16#11111#, 20));
    malformed(50) := '1';
    malformed(53 downto 51) := STATE_SREAD;
    restore_state(saved_legacy, malformed);
    read_ss(SS_SDMA_EXT, observed_extension);
    check_ext_payload(
      observed_extension, 5, 16#67890#, 0, '0', STATE_IDLE,
      "case 7 reserved-bit fallback"
    );

    malformed := (others => '0');
    malformed(63) := '1';
    malformed(62 downto 60) := EXT_VERSION;
    malformed(19 downto 0) := std_logic_vector(to_unsigned(9, 20));
    malformed(39 downto 20) := std_logic_vector(to_unsigned(16#11111#, 20));
    malformed(49 downto 40) := std_logic_vector(to_unsigned(23, 10));
    malformed(50) := '1';
    malformed(53 downto 51) := "111"; -- valid header, illegal FSM code
    restore_state(saved_legacy, malformed);
    read_ss(SS_SDMA_EXT, observed_extension);
    check_ext_payload(
      observed_extension, 9, 16#11111#, 23, '0', STATE_IDLE,
      "case 7 illegal-state fail-safe"
    );
    assert bus_read = '0' and sdma_active = '0'
      report "case 7 illegal state restored an in-flight transaction"
      severity failure;

    -- A set valid bit is insufficient without the exact known version.
    -- Poison every useful payload field and prove version 2 still selects the
    -- slot-17 fallback rather than interpreting a future format as version 1.
    malformed := (others => '0');
    malformed(63) := '1';
    malformed(62 downto 60) := "010";
    malformed(19 downto 0) := std_logic_vector(to_unsigned(9, 20));
    malformed(39 downto 20) := std_logic_vector(to_unsigned(16#11111#, 20));
    malformed(49 downto 40) := std_logic_vector(to_unsigned(23, 10));
    malformed(50) := '1';
    malformed(53 downto 51) := STATE_SREAD;
    restore_state(saved_legacy, malformed);
    read_ss(SS_SDMA_EXT, observed_extension);
    check_ext_payload(
      observed_extension, 5, 16#67890#, 0, '0', STATE_IDLE,
      "case 7 unknown-version fallback"
    );

    -- SDMA_READ exists only after a pending request selected it.  A valid
    -- extension claiming that state with pending clear cannot resume a read.
    malformed := (others => '0');
    malformed(63) := '1';
    malformed(62 downto 60) := EXT_VERSION;
    malformed(19 downto 0) := std_logic_vector(to_unsigned(9, 20));
    malformed(39 downto 20) := std_logic_vector(to_unsigned(16#11111#, 20));
    malformed(49 downto 40) := std_logic_vector(to_unsigned(23, 10));
    malformed(50) := '0';
    malformed(53 downto 51) := STATE_SREAD;
    restore_state(saved_legacy, malformed);
    read_ss(SS_SDMA_EXT, observed_extension);
    check_ext_payload(
      observed_extension, 9, 16#11111#, 23, '0', STATE_IDLE,
      "case 7 pre-read-without-pending fail-safe"
    );
    assert bus_read = '0' and sdma_active = '0'
      report "case 7 pre-read without pending resumed a transaction"
      severity failure;

    -- Conversely, pending is not legal in IDLE when CTRL is disabled.  Keep
    -- the versioned counters/timer but sanitize that orphan request to clear.
    saved_legacy := legacy_word(5, 16#67890#, 16#03#);
    malformed := (others => '0');
    malformed(63) := '1';
    malformed(62 downto 60) := EXT_VERSION;
    malformed(19 downto 0) := std_logic_vector(to_unsigned(9, 20));
    malformed(39 downto 20) := std_logic_vector(to_unsigned(16#11111#, 20));
    malformed(49 downto 40) := std_logic_vector(to_unsigned(23, 10));
    malformed(50) := '1';
    malformed(53 downto 51) := STATE_IDLE;
    restore_state(saved_legacy, malformed);
    read_ss(SS_SDMA_EXT, observed_extension);
    check_ext_payload(
      observed_extension, 9, 16#11111#, 23, '0', STATE_IDLE,
      "case 7 disabled-IDLE pending fail-safe"
    );
    assert bus_read = '0' and sdma_active = '0' and sdma_request = '0'
      report "case 7 disabled IDLE retained an orphan request" severity failure;
    reads_before := bus_read_count;
    resume;
    tick(200);
    assert bus_read_count = reads_before and bus_read = '0' and
           sdma_active = '0' and sdma_request = '0'
      report "case 7 disabled IDLE released sanitized work" severity failure;

    report "PASS dma_savestate_tb versioned and legacy Sound-DMA restore"
      severity note;
    stop;
    wait;
  end process;
end architecture;
