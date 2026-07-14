-- SPDX-License-Identifier: GPL-2.0-only
-- Direct General-DMA eligibility, timing, boundary, and counter regression.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

entity dma_gdma_tb is
end entity;

architecture test of dma_gdma_tb is
  constant CLK_PERIOD : time := 10 ns;

  signal clk                : std_logic := '0';
  signal ce                 : std_logic := '0';
  signal reset              : std_logic := '1';
  signal is_color           : std_logic := '1';
  signal cartridge_rom_word : std_logic := '1';
  signal cartridge_rom_slow : std_logic := '0';
  signal dma_active         : std_logic;
  signal sdma_active        : std_logic;
  signal sdma_request       : std_logic;
  signal cpu_idle           : std_logic := '0';
  signal bus_read           : std_logic;
  signal bus_write          : std_logic;
  signal bus_be             : std_logic_vector(1 downto 0);
  signal bus_addr           : unsigned(19 downto 0);
  signal bus_datawrite      : std_logic_vector(15 downto 0);
  signal bus_dataread       : std_logic_vector(15 downto 0) := x"A55A";
  signal sound_dma_value    : std_logic_vector(7 downto 0);
  signal sound_dma_ch2      : std_logic;
  signal sound_dma_ch5      : std_logic;
  signal reg_din            : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_addr           : std_logic_vector(7 downto 0) := (others => '0');
  signal reg_wren           : std_logic := '0';
  signal reg_rst            : std_logic := '1';
  signal reg_dout           : std_logic_vector(7 downto 0);
  signal sleep_savestate    : std_logic := '0';
  signal ssbus_din          : std_logic_vector(63 downto 0) := (others => '0');
  signal ssbus_addr         : std_logic_vector(6 downto 0) := (others => '0');
  signal ssbus_wren         : std_logic := '0';
  signal ssbus_rst          : std_logic := '1';
  signal ssbus_dout         : std_logic_vector(63 downto 0);
begin
  clk <= not clk after CLK_PERIOD / 2;

  dut : entity work.dma
    generic map (
      is_simu => '0'
    )
    port map (
      clk                => clk,
      ce                 => ce,
      reset              => reset,
      isColor            => is_color,
      cartridge_rom_word => cartridge_rom_word,
      cartridge_rom_slow => cartridge_rom_slow,
      dma_active         => dma_active,
      sdma_active        => sdma_active,
      sdma_request       => sdma_request,
      cpu_idle           => cpu_idle,
      bus_read           => bus_read,
      bus_write          => bus_write,
      bus_be             => bus_be,
      bus_addr           => bus_addr,
      bus_datawrite      => bus_datawrite,
      bus_dataread       => bus_dataread,
      soundDMAvalue      => sound_dma_value,
      soundDMACh2        => sound_dma_ch2,
      soundDMACh5        => sound_dma_ch5,
      RegBus_Din         => reg_din,
      RegBus_Adr         => reg_addr,
      RegBus_wren        => reg_wren,
      RegBus_rst         => reg_rst,
      RegBus_Dout        => reg_dout,
      sleep_savestate    => sleep_savestate,
      SSBUS_Din          => ssbus_din,
      SSBUS_Adr          => ssbus_addr,
      SSBUS_wren         => ssbus_wren,
      SSBUS_rst          => ssbus_rst,
      SSBUS_Dout         => ssbus_dout
    );

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
      ce <= '0';
      reset <= '1';
      reg_rst <= '1';
      ssbus_rst <= '1';
      reg_wren <= '0';
      tick(2);
      reset <= '0';
      reg_rst <= '0';
      ssbus_rst <= '0';
      tick;
      assert dma_active = '0' and sdma_active = '0' and
             bus_read = '0' and bus_write = '0'
        report "reset did not quiesce DMA" severity failure;
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

    procedure expect_port(
      address      : natural;
      expected     : natural;
      message_text : string
    ) is
    begin
      reg_addr <= std_logic_vector(to_unsigned(address, reg_addr'length));
      wait for 1 ns;
      assert reg_dout = std_logic_vector(to_unsigned(expected, reg_dout'length))
        report message_text & ": expected " &
               to_hstring(std_logic_vector(to_unsigned(expected, 8))) &
               ", got " & to_hstring(reg_dout)
        severity failure;
    end procedure;

    procedure program_gdma(
      source_address      : natural;
      destination_address : natural;
      byte_length         : natural
    ) is
    begin
      write_port(16#40#, source_address mod 256);
      write_port(16#41#, (source_address / 256) mod 256);
      write_port(16#42#, (source_address / 65536) mod 16);
      write_port(16#44#, destination_address mod 256);
      write_port(16#45#, (destination_address / 256) mod 256);
      write_port(16#46#, byte_length mod 256);
      write_port(16#47#, (byte_length / 256) mod 256);
    end procedure;

    procedure start_gdma(decrement : boolean) is
    begin
      if decrement then
        write_port(16#48#, 16#C0#);
      else
        write_port(16#48#, 16#80#);
      end if;
    end procedure;

    procedure expect_gdma_registers(
      source_address      : natural;
      destination_address : natural;
      byte_length         : natural;
      control_value       : natural;
      message_text        : string
    ) is
    begin
      expect_port(16#40#, source_address mod 256, message_text & " source low");
      expect_port(16#41#, (source_address / 256) mod 256, message_text & " source middle");
      expect_port(16#42#, (source_address / 65536) mod 16, message_text & " source high");
      expect_port(16#44#, destination_address mod 256, message_text & " destination low");
      expect_port(16#45#, (destination_address / 256) mod 256, message_text & " destination high");
      expect_port(16#46#, byte_length mod 256, message_text & " length low");
      expect_port(16#47#, (byte_length / 256) mod 256, message_text & " length high");
      expect_port(16#48#, control_value, message_text & " control");
    end procedure;

    -- Count DMA-owned CE pulses at the pre-edge point where SwanTop decides
    -- whether ce_cpu may run.  A low-CE cleanup clock between pulses models
    -- production, where one-clock bus strobes retire well before the next CPU
    -- quadrant.  invalidate_kind 1 clears the ROM-word input and kind 2
    -- asserts ROM-slow after the first read; that word must still complete,
    -- while the next source is rejected without consuming another owned CE.
    procedure run_transfer(
      source_start          : natural;
      destination_start     : natural;
      decrement             : boolean;
      expected_words        : natural;
      expected_active_cycles: natural;
      invalidate_kind       : natural;
      message_text          : string
    ) is
      variable active_cycles : natural := 0;
      variable read_count    : natural := 0;
      variable write_count   : natural := 0;
      variable expected_addr : natural := 0;
      variable finished      : boolean := false;
    begin
      ce <= '0';
      for step in 0 to 127 loop
        wait until falling_edge(clk);
        if dma_active = '1' then
          active_cycles := active_cycles + 1;
        end if;
        ce <= '1';
        wait until rising_edge(clk);
        wait for 1 ns;
        ce <= '0';

        if bus_read = '1' then
          if decrement then
            expected_addr := source_start - 2 * read_count;
          else
            expected_addr := source_start + 2 * read_count;
          end if;
          assert bus_addr = to_unsigned(expected_addr, bus_addr'length)
            report message_text & " read address " & integer'image(read_count) &
                   " expected " & to_hstring(to_unsigned(expected_addr, 20)) &
                   ", got " & to_hstring(bus_addr)
            severity failure;
          read_count := read_count + 1;
          if read_count = 1 then
            if invalidate_kind = 1 then
              cartridge_rom_word <= '0';
            elsif invalidate_kind = 2 then
              cartridge_rom_slow <= '1';
            end if;
          end if;
        end if;

        if bus_write = '1' then
          assert dma_active = '1'
            report message_text & " final/current write lost DMA bus ownership"
            severity failure;
          if decrement then
            expected_addr := destination_start - 2 * write_count;
          else
            expected_addr := destination_start + 2 * write_count;
          end if;
          assert bus_addr = to_unsigned(expected_addr, bus_addr'length)
            report message_text & " write address " & integer'image(write_count) &
                   " expected " & to_hstring(to_unsigned(expected_addr, 20)) &
                   ", got " & to_hstring(bus_addr)
            severity failure;
          assert bus_datawrite = bus_dataread and bus_be = "11"
            report message_text & " write data/byte-enable mismatch" severity failure;
          write_count := write_count + 1;
        end if;

        -- Retire one-clock bus strobes without advancing the CE-driven FSM.
        wait until rising_edge(clk);
        wait for 1 ns;
        if dma_active = '0' and bus_read = '0' and bus_write = '0' then
          finished := true;
          exit;
        end if;
      end loop;
      ce <= '0';

      assert finished report message_text & " did not return idle" severity failure;
      assert active_cycles = expected_active_cycles
        report message_text & " active CE count expected " &
               integer'image(expected_active_cycles) & ", got " &
               integer'image(active_cycles)
        severity failure;
      assert read_count = expected_words and write_count = expected_words
        report message_text & " expected " & integer'image(expected_words) &
               " read/write words, got " & integer'image(read_count) & "/" &
               integer'image(write_count)
        severity failure;
    end procedure;

    variable source_address : natural;
    variable expected_valid : boolean;
  begin
    -- Exhaust every source segment and both ROM-width/wait configurations.
    -- Segment 0 is always valid, segment 1 never is, and 2-F require word=1,
    -- slow=0.  Invalid starts must not enter setup or issue any bus access.
    for segment in 0 to 15 loop
      for word_select in 0 to 1 loop
        for slow_select in 0 to 1 loop
          reset_dut;
          if word_select = 0 then
            cartridge_rom_word <= '0';
          else
            cartridge_rom_word <= '1';
          end if;
          if slow_select = 0 then
            cartridge_rom_slow <= '0';
          else
            cartridge_rom_slow <= '1';
          end if;

          source_address := segment * 16#10000# + 16#0200#;
          expected_valid := segment = 0 or
                            (segment >= 2 and word_select = 1 and slow_select = 0);
          program_gdma(source_address, 16#1000#, 2);
          start_gdma(false);

          if expected_valid then
            assert dma_active = '1'
              report "valid start matrix entry did not assert active: segment " &
                     integer'image(segment) severity failure;
            run_transfer(source_address, 16#1000#, false, 1, 7, 0,
                         "valid start matrix segment " & integer'image(segment));
            expect_gdma_registers(source_address + 2, 16#1002#, 0, 0,
                                  "valid start matrix completion");
          else
            assert dma_active = '0'
              report "invalid start matrix entry asserted active: segment " &
                     integer'image(segment) severity failure;
            run_transfer(source_address, 16#1000#, false, 0, 0, 0,
                         "invalid start matrix segment " & integer'image(segment));
            expect_gdma_registers(source_address, 16#1000#, 2, 0,
                                  "invalid start matrix rejection");
          end if;
        end loop;
      end loop;
    end loop;

    -- Zero length is rejected without setup even for otherwise-valid IRAM and
    -- cartridge ROM sources.
    for segment in 0 to 2 loop
      if segment /= 1 then
        reset_dut;
        cartridge_rom_word <= '1';
        cartridge_rom_slow <= '0';
        source_address := segment * 16#10000# + 16#0400#;
        program_gdma(source_address, 16#1200#, 0);
        start_gdma(false);
        assert dma_active = '0' report "zero-length GDMA asserted active" severity failure;
        run_transfer(source_address, 16#1200#, false, 0, 0, 0,
                     "zero-length segment " & integer'image(segment));
        expect_gdma_registers(source_address, 16#1200#, 0, 0,
                              "zero-length rejection");
      end if;
    end loop;

    -- Multiword increment and decrement lock both address sequences and the
    -- exact 5+2*words ownership interval.  The decrement case finishes on the
    -- final valid ROM word even though the post-transfer address is in SRAM.
    reset_dut;
    cartridge_rom_word <= '0';
    cartridge_rom_slow <= '1';
    program_gdma(16#00200#, 16#1000#, 6);
    start_gdma(false);
    run_transfer(16#00200#, 16#1000#, false, 3, 11, 0, "three-word increment");
    expect_gdma_registers(16#00206#, 16#1006#, 0, 0, "increment completion");

    reset_dut;
    cartridge_rom_word <= '1';
    cartridge_rom_slow <= '0';
    program_gdma(16#20004#, 16#1004#, 6);
    start_gdma(true);
    run_transfer(16#20004#, 16#1004#, true, 3, 11, 0, "three-word decrement");
    expect_gdma_registers(16#1FFFE#, 16#0FFE#, 0, 1, "decrement completion");

    -- Incrementing and decrementing into segment 1 stop before the next word;
    -- that unprocessed word remains in the live length counter.
    reset_dut;
    cartridge_rom_word <= '1';
    cartridge_rom_slow <= '0';
    program_gdma(16#0FFFE#, 16#1400#, 4);
    start_gdma(false);
    run_transfer(16#0FFFE#, 16#1400#, false, 1, 7, 0, "increment boundary stop");
    expect_gdma_registers(16#10000#, 16#1402#, 2, 0, "increment boundary state");

    reset_dut;
    cartridge_rom_word <= '1';
    cartridge_rom_slow <= '0';
    program_gdma(16#20000#, 16#1402#, 4);
    start_gdma(true);
    run_transfer(16#20000#, 16#1402#, true, 1, 7, 0, "decrement boundary stop");
    expect_gdma_registers(16#1FFFE#, 16#1400#, 2, 1, "decrement boundary state");

    -- Live $A0 changes after the first source read do not cancel that in-flight
    -- word, but they invalidate the next ROM word without a second read/write,
    -- counter decrement, or abort-only CE.
    reset_dut;
    cartridge_rom_word <= '1';
    cartridge_rom_slow <= '0';
    program_gdma(16#20000#, 16#1800#, 4);
    start_gdma(false);
    run_transfer(16#20000#, 16#1800#, false, 1, 7, 1, "mid-transfer byte-ROM stop");
    expect_gdma_registers(16#20002#, 16#1802#, 2, 0, "byte-ROM stop state");

    reset_dut;
    cartridge_rom_word <= '1';
    cartridge_rom_slow <= '0';
    program_gdma(16#20000#, 16#1A00#, 4);
    start_gdma(false);
    run_transfer(16#20000#, 16#1A00#, false, 1, 7, 2, "mid-transfer slow-ROM stop");
    expect_gdma_registers(16#20002#, 16#1A02#, 2, 0, "slow-ROM stop state");

    -- A pending Sound-DMA request and a valid $48 write can be observed by
    -- the CE-driven IDLE arbitration on the same rising edge.  The accepted
    -- GDMA start must win that edge; otherwise SDMA_READ overwrites WAITING,
    -- leaving dmaOn permanently high after the sound transfer retires.
    reset_dut;
    cpu_idle <= '0';
    write_port(16#4A#, 16#00#);
    write_port(16#4B#, 16#03#);
    write_port(16#4C#, 16#00#);
    write_port(16#4E#, 16#02#);
    write_port(16#4F#, 16#00#);
    write_port(16#50#, 16#00#);
    write_port(16#52#, 16#83#);
    ce <= '1';
    for step in 0 to 159 loop
      tick;
      exit when sdma_request = '1';
    end loop;
    assert sdma_request = '1' and sdma_active = '0' and bus_read = '0'
      report "simultaneous-start case did not establish an ungranted SDMA request"
      severity failure;

    cartridge_rom_word <= '1';
    cartridge_rom_slow <= '0';
    program_gdma(16#00400#, 16#1C00#, 2);
    cpu_idle <= '1';
    start_gdma(false);
    assert dma_active = '1' and sdma_active = '0' and bus_read = '0'
      report "pending SDMA request displaced GDMA on the start edge"
      severity failure;

    -- Hold the CPU non-idle after the collision edge so the retained sound
    -- request cannot begin until the exact GDMA result has been checked.
    cpu_idle <= '0';
    run_transfer(16#00400#, 16#1C00#, false, 1, 7, 0,
                 "pending-SDMA simultaneous GDMA start");
    expect_gdma_registers(16#00402#, 16#1C02#, 0, 0,
                          "pending-SDMA GDMA completion");
    assert sdma_request = '1' and sdma_active = '0' and bus_read = '0'
      report "GDMA did not preserve the deferred SDMA request" severity failure;

    -- Once GDMA has retired, the original request must still execute exactly
    -- once and deliver the latched byte to Channel 2.
    ce <= '1';
    cpu_idle <= '1';
    tick;
    assert sdma_request = '1' and sdma_active = '0' and bus_read = '0'
      report "deferred SDMA request skipped its pre-read phase" severity failure;
    tick;
    assert sdma_active = '1' and bus_read = '1' and
           bus_addr = to_unsigned(16#00300#, bus_addr'length)
      report "deferred SDMA request did not issue its source read" severity failure;
    tick;
    assert sdma_request = '0' and sdma_active = '0' and bus_read = '0' and
           sound_dma_ch2 = '1' and sound_dma_value = x"5A"
      report "deferred SDMA request did not retire exactly once" severity failure;

    assert sdma_active = '0' and sdma_request = '0'
      report "GDMA regression disturbed Sound DMA" severity failure;
    report "PASS dma_gdma_tb exhaustive source/config starts, zero-cost rejection, exact 5+2*words timing, direction, mid-transfer stops, and GDMA/SDMA start arbitration"
      severity note;
    stop;
    wait;
  end process;
end architecture;
