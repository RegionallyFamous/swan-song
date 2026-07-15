-- SPDX-License-Identifier: GPL-2.0-only
-- Exact EEPROM-controller freeze/export/load behavioral and synthesis probe.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.env.all;

use work.pRegisterBus.all;
use work.pBus_savestates.all;

entity eeprom_state_tb is
end entity;

architecture test of eeprom_state_tb is
   constant CPU_PERIOD : time := 10 ns;
   constant RAM_PERIOD : time := 14 ns;
   -- Must match apf_savestate_v2_load_settle_guard's default. The canonical
   -- path consumes one raw-low sample; hidden legacy-state normalization below
   -- proves the defensive two-sample maximum used at the native boundary.
   constant MAX_V2_LOAD_ACK_LOW_CYCLES : natural := 2;

   constant REG_DATA_LO : regmap_type := (16#BA#, 7, 0, 1, 0, readwrite);
   constant REG_DATA_HI : regmap_type := (16#BB#, 7, 0, 1, 0, readwrite);
   constant REG_ADDR_LO : regmap_type := (16#BC#, 7, 0, 1, 0, readwrite);
   constant REG_ADDR_HI : regmap_type := (16#BD#, 7, 0, 1, 0, readwrite);
   constant REG_COMMAND : regmap_type := (16#BE#, 7, 0, 1, 0, readwrite);
   constant REG_SS      : savestate_type :=
      (0, 16, 0, 1, x"0000000000000000");

   signal clk       : std_logic := '0';
   signal clk_ram   : std_logic := '0';
   signal reset     : std_logic := '1';
   signal reg_din   : std_logic_vector(7 downto 0) := (others => '0');
   signal reg_addr  : std_logic_vector(7 downto 0) := (others => '0');
   signal reg_wren  : std_logic := '0';
   signal reg_rst   : std_logic := '0';
   signal reg_dout  : std_logic_vector(7 downto 0);
   signal ss_din    : std_logic_vector(63 downto 0) := (others => '0');
   signal ss_addr   : std_logic_vector(6 downto 0) := (others => '0');
   signal ss_wren   : std_logic := '0';
   signal ss_rst    : std_logic := '0';
   signal ss_dout   : std_logic_vector(63 downto 0);
   signal host_addr : std_logic_vector(9 downto 0) := (others => '0');
   signal host_din  : std_logic_vector(15 downto 0) := (others => '0');
   signal host_dout : std_logic_vector(15 downto 0);
   signal host_req  : std_logic := '0';
   signal host_rnw  : std_logic := '1';
   signal written   : std_logic;
   signal freeze    : std_logic := '0';
   signal ack       : std_logic;
   signal load      : std_logic := '0';
   signal state_in  : std_logic_vector(127 downto 0) := (others => '0');
   signal state_out : std_logic_vector(127 downto 0);

   function make_image(fsm : natural) return std_logic_vector is
      variable result : std_logic_vector(127 downto 0) := (others => '0');
   begin
      result(15 downto 0)   := x"BEEF";
      result(31 downto 16)  := x"1234";
      result(47 downto 32)  := x"4567";
      result(55 downto 48)  := x"20";
      result(58 downto 56)  := std_logic_vector(to_unsigned(fsm, 3));
      result(59)            := '1';
      result(60)            := '1';
      result(61)            := '1';
      result(65 downto 62)  := std_logic_vector(to_unsigned(7, 4));
      result(76 downto 66)  := std_logic_vector(to_unsigned(64, 11));
      result(87 downto 77)  := std_logic_vector(to_unsigned(17, 11));
      result(98 downto 88)  := std_logic_vector(to_unsigned(5, 11));
      result(114 downto 99) := x"CAFE";
      result(117)           := '1';
      return result;
   end function;
begin
   clk <= not clk after CPU_PERIOD / 2;
   clk_ram <= not clk_ram after RAM_PERIOD / 2;

   dut : entity work.eeprom
      generic map (
         isExternal           => '1',
         defaultvalue         => x"FFFF",
         REG_Data_H           => REG_DATA_LO,
         REG_Data_L           => REG_DATA_HI,
         REG_Addr_H           => REG_ADDR_LO,
         REG_Addr_L           => REG_ADDR_HI,
         REG_Cmd              => REG_COMMAND,
         REG_SAVESTATE_EEPROM => REG_SS
      )
      port map (
         clk => clk, clk_ram => clk_ram, ce => '1', reset => reset,
         isColor => '0', preserve_on_reset => '0', ramtype => x"10",
         written => written, eeprom_bank => '0', eeprom_addr => host_addr,
         eeprom_din => host_din, eeprom_dout => host_dout,
         eeprom_req => host_req, eeprom_rnw => host_rnw,
         RegBus_Din => reg_din, RegBus_Adr => reg_addr,
         RegBus_wren => reg_wren, RegBus_rst => reg_rst,
         RegBus_Dout => reg_dout,
         SSBus_Din => ss_din, SSBus_Adr => ss_addr,
         SSBus_wren => ss_wren, SSBus_rst => ss_rst, SSBus_Dout => ss_dout,
         state_freeze => freeze, frozen_ack => ack,
         state_load => load, state_in => state_in, state_out => state_out
      );

   stimulus : process
      procedure load_frozen(constant image : std_logic_vector(127 downto 0)) is
         variable ack_low_samples : natural := 0;
      begin
         freeze <= '1';
         -- Cooperative ordering: observe a prior-cycle frozen_ack before
         -- pulsing state_load.  The first freeze edge may drain RAMWrEn.
         for drain_cycle in 0 to 2 loop
            wait until rising_edge(clk);
            wait for 1 ns;
            exit when ack = '1';
         end loop;
         assert ack = '1'
            report "controller did not reach pre-load frozen boundary"
            severity failure;
         wait until falling_edge(clk);
         state_in <= image;
         load <= '1';
         wait until rising_edge(clk);
         wait for 1 ns;
         assert ack = '0'
            report "state load was acknowledged before RAM settle" severity failure;
         ack_low_samples := ack_low_samples + 1;
         wait until falling_edge(clk);
         load <= '0';
         wait until rising_edge(clk);
         wait for 1 ns;
         assert ack = '1'
            report "state load did not acknowledge after RAM settle" severity failure;
         assert ack_low_samples <= MAX_V2_LOAD_ACK_LOW_CYCLES
            report "canonical EEPROM load exceeded settle-guard bound"
            severity failure;
         assert state_out(115) = '0' and state_out(116) = '0'
            report "acknowledged state is not canonical" severity failure;
         assert state_out(127 downto 118) = (127 downto 118 => '0')
            report "reserved controller-state bits are not zero" severity failure;
      end procedure;

      procedure release_frozen is
      begin
         wait until falling_edge(clk);
         freeze <= '0';
         wait until rising_edge(clk);
         wait for 1 ns;
         assert ack = '0'
            report "freeze acknowledgment did not clear" severity failure;
      end procedure;

      procedure bus_write(constant address : natural; constant value : natural) is
      begin
         wait until falling_edge(clk);
         reg_addr <= std_logic_vector(to_unsigned(address, reg_addr'length));
         reg_din <= std_logic_vector(to_unsigned(value, reg_din'length));
         reg_wren <= '1';
         wait until rising_edge(clk);
         wait for 1 ns;
         wait until falling_edge(clk);
         reg_wren <= '0';
      end procedure;

      procedure host_write(constant address : natural; constant value : natural) is
      begin
         wait until falling_edge(clk_ram);
         host_addr <= std_logic_vector(to_unsigned(address, host_addr'length));
         host_din <= std_logic_vector(to_unsigned(value, host_din'length));
         host_rnw <= '0';
         host_req <= '1';
         wait until rising_edge(clk_ram);
         wait for 1 ns;
         host_req <= '0';
         host_rnw <= '1';
      end procedure;

      procedure host_expect(constant address : natural; constant value : natural) is
      begin
         wait until falling_edge(clk_ram);
         host_addr <= std_logic_vector(to_unsigned(address, host_addr'length));
         host_rnw <= '1';
         host_req <= '1';
         wait until rising_edge(clk_ram);
         wait for 1 ns;
         assert host_dout = std_logic_vector(to_unsigned(value, host_dout'length))
            report "EEPROM backing mismatch at word " & integer'image(address)
            severity failure;
         host_req <= '0';
      end procedure;

      variable image  : std_logic_vector(127 downto 0);
      variable stable : std_logic_vector(127 downto 0);
      variable reset_reference : std_logic_vector(127 downto 0);
   begin
      -- Device reset alone must deterministically initialize every exported
      -- field, even when the independent register-bus reset is low.
      wait until rising_edge(clk);
      wait until rising_edge(clk);
      wait for 1 ns;
      assert not is_x(state_out)
         report "reset controller image contains U/X" severity failure;
      assert state_out(15 downto 0) = x"0000" and
             state_out(31 downto 16) = x"0000" and
             state_out(47 downto 32) = x"0000" and
             state_out(55 downto 48) = x"00"
         report "reset did not initialize register latches" severity failure;
      assert state_out(58 downto 56) = "001" and
             unsigned(state_out(76 downto 66)) = 64 and
             unsigned(state_out(87 downto 77)) = 0 and
             unsigned(state_out(98 downto 88)) = 0 and
             state_out(114 downto 99) = x"FFFF"
         report "reset did not initialize controller pipeline" severity failure;
      reset <= '0';

      -- A state_load coincident with the first freeze edge is rejected.  It
      -- may only be retried after frozen_ack was high in a prior cycle.
      stable := state_out;
      image := make_image(7);
      wait until falling_edge(clk);
      freeze <= '1';
      state_in <= image;
      load <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert ack = '1' and state_out = stable
         report "first-edge state load was not rejected" severity failure;
      wait until falling_edge(clk);
      load <= '0';

      -- Every FSM value has a stable, exact, exhaustively checked encoding.
      for fsm in 0 to 7 loop
         image := make_image(fsm);
         load_frozen(image);
         assert state_out = image
            report "controller image mismatch for FSM " & integer'image(fsm)
            severity failure;
         stable := state_out;
         reg_rst <= '1';
         for hold_cycle in 0 to 2 loop
            wait until rising_edge(clk);
            wait for 1 ns;
            assert ack = '1' and state_out = stable
               report "acknowledged image changed during freeze/register reset"
               severity failure;
         end loop;
         reg_rst <= '0';
      end loop;

      -- clearCounter retains inclusive terminal 1024; addrCounter is a real
      -- ten-bit backing address and its exact upper bound is 1023.
      image := make_image(1);
      image(87 downto 77) := std_logic_vector(to_unsigned(1024, 11));
      image(98 downto 88) := std_logic_vector(to_unsigned(1023, 11));
      image(117) := '0';
      load_frozen(image);
      assert state_out = image and not is_x(state_out)
         report "terminal EEPROM counters did not restore exactly"
         severity failure;

      -- Loading a write command restores Cmd without creating Cmd_written.
      image := make_image(1);
      image(47 downto 32) := x"0042";
      image(117) := '0';
      load_frozen(image);
      release_frozen;
      for quiet_cycle in 0 to 2 loop
         wait until rising_edge(clk);
         wait for 1 ns;
         assert state_out(58 downto 56) = "001"
            report "state load synthesized an EEPROM command" severity failure;
      end loop;

      -- state_load while running is a complete no-op and must not steal a
      -- simultaneous, otherwise-valid CPU register write.
      image := make_image(7);
      wait until falling_edge(clk);
      state_in <= image;
      load <= '1';
      reg_addr <= x"BA";
      reg_din <= x"A5";
      reg_wren <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert state_out(58 downto 56) = "001" and
             state_out(7 downto 0) = x"A5"
         report "invalid running load perturbed or stole CPU write"
         severity failure;
      wait until falling_edge(clk);
      load <= '0';
      reg_wren <= '0';
      bus_write(16#BA#, 16#EF#);
      host_expect(2, 0);

      -- A naturally pending single-word write commits on the freeze edge.
      bus_write(16#BE#, 16#20#);
      wait until rising_edge(clk);
      wait for 1 ns;
      assert state_out(58 downto 56) = "101" and state_out(116) = '1'
         report "write did not reach pending WRITEWAIT" severity failure;
      wait until falling_edge(clk);
      freeze <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert ack = '1' and state_out(116) = '0'
         report "freeze acknowledged before pending write committed" severity failure;
      host_expect(2, 16#BEEF#);
      stable := state_out;
      host_write(2, 16#CAFE#);
      wait until rising_edge(clk);
      wait for 1 ns;
      assert state_out = stable
         report "pending-write snapshot changed while frozen" severity failure;
      release_frozen;
      wait until rising_edge(clk);
      host_expect(2, 16#CAFE#);

      -- A restored pending write is also committed exactly once during the
      -- mandatory settle edge, before frozen_ack rises.
      image := make_image(5);
      image(98 downto 88) := std_logic_vector(to_unsigned(10, 11));
      image(114 downto 99) := x"7777";
      image(116) := '1';
      image(117) := '0';
      host_write(10, 16#0000#);
      load_frozen(image);
      host_expect(10, 16#7777#);
      host_write(10, 16#8888#);
      release_frozen;
      wait until rising_edge(clk);
      host_expect(10, 16#8888#);

      -- OVERWRITE has a write in flight while its counter still names the
      -- committed word.  Freeze must drain word zero, and resume must advance
      -- to word one instead of replaying zero.
      image := make_image(1);
      image(15 downto 0) := x"5A5A";
      image(47 downto 32) := x"0010";
      image(117) := '0';
      load_frozen(image);
      release_frozen;
      bus_write(16#BE#, 16#20#);
      wait until rising_edge(clk);
      wait for 1 ns;
      assert state_out(58 downto 56) = "100" and state_out(116) = '1'
         report "write-all did not reach pending OVERWRITE" severity failure;
      wait until falling_edge(clk);
      freeze <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert ack = '1' and state_out(116) = '0' and
             unsigned(state_out(98 downto 88)) = 0
         report "OVERWRITE pending word did not drain before ack"
         severity failure;
      host_expect(0, 16#5A5A#);
      host_write(0, 16#C0DE#);
      release_frozen;
      for overwrite_cycle in 0 to 66 loop
         wait until rising_edge(clk);
      end loop;
      host_expect(0, 16#C0DE#);
      host_expect(1, 16#5A5A#);
      host_expect(63, 16#5A5A#);

      -- Resume the final CLEAR word.  Address zero must not receive the old
      -- implementation's wrapped extra write on the terminal cycle.
      host_write(0, 16#A000#);
      host_write(62, 16#A062#);
      host_write(63, 16#A063#);
      image := make_image(3);
      image(87 downto 77) := std_logic_vector(to_unsigned(63, 11));
      image(98 downto 88) := std_logic_vector(to_unsigned(62, 11));
      image(114 downto 99) := x"FFFF";
      image(117) := '0';
      load_frozen(image);
      release_frozen;
      wait until rising_edge(clk);
      wait until rising_edge(clk);
      wait until rising_edge(clk);
      host_expect(0, 16#A000#);
      host_expect(62, 16#A062#);
      host_expect(63, 16#FFFF#);

      -- The load-settle cycle primes synchronous q_a before READONE resumes.
      host_write(5, 16#1357#);
      image := make_image(6);
      image(31 downto 16) := x"0000";
      image(47 downto 32) := x"0085";
      image(61) := '0';
      image(65 downto 62) := std_logic_vector(to_unsigned(9, 4));
      image(98 downto 88) := std_logic_vector(to_unsigned(5, 11));
      image(117) := '0';
      load_frozen(image);
      release_frozen;
      wait until rising_edge(clk);
      wait until rising_edge(clk);
      wait for 1 ns;
      assert state_out(31 downto 16) = x"1357" and
             state_out(61) = '1' and state_out(58 downto 56) = "001"
         report "READWAIT/READONE did not resume exactly" severity failure;

      -- A pending legacy register restore must be consumed before canonical
      -- v2 acknowledgment, with its writeEnable value retained.
      image := make_image(1);
      image(117) := '0';
      load_frozen(image);
      release_frozen;
      wait until falling_edge(clk);
      ss_din <= x"0000000000012468";
      ss_addr <= (others => '0');
      ss_wren <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert state_out(115) = '1'
         report "legacy ssLoaded history was not captured" severity failure;
      wait until falling_edge(clk);
      ss_wren <= '0';
      freeze <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert ack = '0' and state_out(115) = '0' and
             state_out(59) = '1' and state_out(31 downto 16) = x"2468"
         report "legacy restore was not consumed before v2 ack" severity failure;
      wait until rising_edge(clk);
      wait for 1 ns;
      assert ack = '1' and state_out(115) = '0' and state_out(116) = '0'
         report "canonical v2 ack invariants failed" severity failure;

      -- Prove SSBus_rst is truly deferred, not merely absent from state_out:
      -- preserve the nondefault hidden legacy register while frozen, then use
      -- a deliberately noncanonical direct load to request its consumption.
      stable := state_out;
      ss_rst <= '1';
      for hidden_reset_cycle in 0 to 1 loop
         wait until rising_edge(clk);
         wait for 1 ns;
         assert ack = '1' and state_out = stable
            report "SSBus_rst changed acknowledged state" severity failure;
      end loop;
      wait until falling_edge(clk);
      ss_rst <= '0';
      image := make_image(1);
      image(31 downto 16) := x"0000";
      image(59) := '0';
      image(115) := '1';
      image(117) := '0';
      state_in <= image;
      load <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert ack = '0'
         report "noncanonical direct load skipped settle" severity failure;
      wait until falling_edge(clk);
      load <= '0';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert ack = '0' and state_out(115) = '0' and
             state_out(31 downto 16) = x"2468" and state_out(59) = '1'
         report "frozen SSBus_rst destroyed hidden legacy register"
         severity failure;
      assert 2 <= MAX_V2_LOAD_ACK_LOW_CYCLES
         report "legacy normalization exceeded settle-guard bound"
         severity failure;
      wait until rising_edge(clk);
      wait for 1 ns;
      assert ack = '1'
         report "controller did not re-ack after hidden-state consumption"
         severity failure;

      -- After canonical consumption, an ordinary reset must use declared
      -- controller defaults rather than consulting hidden SS_EEPROM again.
      release_frozen;
      wait until falling_edge(clk);
      reset <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert state_out(31 downto 16) = x"0000" and state_out(59) = '0'
         report "ordinary reset reused consumed hidden legacy state"
         severity failure;
      wait until falling_edge(clk);
      reset <= '0';

      -- Identical canonical images must reset identically even when the
      -- hidden legacy SS register contains different historical values.
      image := make_image(1);
      image(31 downto 16) := x"A1B2";
      image(60) := '0';
      image(117) := '0';
      load_frozen(image);

      -- A bus-only reset is deferred alongside bus writes for the complete
      -- acknowledged freeze interval.
      stable := state_out;
      ss_rst <= '1';
      for ss_reset_cycle in 0 to 2 loop
         wait until rising_edge(clk);
         wait for 1 ns;
         assert ack = '1' and state_out = stable
            report "SSBus_rst changed acknowledged EEPROM state"
            severity failure;
      end loop;
      ss_rst <= '0';
      release_frozen;

      wait until falling_edge(clk);
      reset <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      reset_reference := state_out;
      assert reset_reference(31 downto 16) = x"0000" and
             reset_reference(59) = '0'
         report "ordinary reset did not restore external controller defaults"
         severity failure;
      wait until falling_edge(clk);
      reset <= '0';

      -- Replace the hidden legacy register with a distinct value, let freeze
      -- consume it, then overwrite the architectural state with the exact
      -- same canonical image used above.
      ss_din <= x"000000000001DEAD";
      ss_wren <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert state_out(115) = '1'
         report "second hidden legacy history was not staged" severity failure;
      wait until falling_edge(clk);
      ss_wren <= '0';
      load_frozen(image);
      release_frozen;

      wait until falling_edge(clk);
      reset <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert state_out = reset_reference
         report "identical v2 restore diverged after different hidden SS history"
         severity failure;
      wait until falling_edge(clk);
      reset <= '0';

      -- Device reset explicitly interrupts an existing freeze and produces a
      -- fresh deterministic image; unlike reg_rst it is never deferred.
      freeze <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert ack = '1'
         report "controller did not refreeze before reset interruption"
         severity failure;
      reset <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert ack = '0' and not is_x(state_out)
         report "device reset did not interrupt freeze deterministically"
         severity failure;

      report "PASS EEPROM exact controller freeze/export/load state; max load ack-low samples=" &
             integer'image(MAX_V2_LOAD_ACK_LOW_CYCLES);
      finish;
   end process;
end architecture;

library ieee;
use ieee.std_logic_1164.all;
use work.pRegisterBus.all;
use work.pBus_savestates.all;

entity eeprom_state_synth is
   port (
      clk          : in  std_logic;
      reset        : in  std_logic;
      state_freeze : in  std_logic;
      frozen_ack   : out std_logic;
      state_load   : in  std_logic;
      state_in     : in  std_logic_vector(127 downto 0);
      state_out    : out std_logic_vector(127 downto 0)
   );
end entity;

architecture rtl of eeprom_state_synth is
   constant REG_DATA_LO : regmap_type := (16#BA#, 7, 0, 1, 0, readwrite);
   constant REG_DATA_HI : regmap_type := (16#BB#, 7, 0, 1, 0, readwrite);
   constant REG_ADDR_LO : regmap_type := (16#BC#, 7, 0, 1, 0, readwrite);
   constant REG_ADDR_HI : regmap_type := (16#BD#, 7, 0, 1, 0, readwrite);
   constant REG_COMMAND : regmap_type := (16#BE#, 7, 0, 1, 0, readwrite);
   constant REG_SS      : savestate_type :=
      (0, 16, 0, 1, x"0000000000000000");
begin
   instance : entity work.eeprom
      generic map (
         isExternal => '1', defaultvalue => x"FFFF",
         REG_Data_H => REG_DATA_LO, REG_Data_L => REG_DATA_HI,
         REG_Addr_H => REG_ADDR_LO, REG_Addr_L => REG_ADDR_HI,
         REG_Cmd => REG_COMMAND, REG_SAVESTATE_EEPROM => REG_SS
      )
      port map (
         clk => clk, clk_ram => clk, ce => '1', reset => reset,
         isColor => '0', preserve_on_reset => '0', ramtype => x"10",
         written => open, eeprom_bank => '0', eeprom_addr => (others => '0'),
         eeprom_din => (others => '0'), eeprom_dout => open,
         eeprom_req => '0', eeprom_rnw => '1',
         RegBus_Din => (others => '0'), RegBus_Adr => (others => '0'),
         RegBus_wren => '0', RegBus_rst => '0', RegBus_Dout => open,
         SSBus_Din => (others => '0'), SSBus_Adr => (others => '0'),
         SSBus_wren => '0', SSBus_rst => '0', SSBus_Dout => open,
         state_freeze => state_freeze, frozen_ack => frozen_ack,
         state_load => state_load, state_in => state_in, state_out => state_out
      );
end architecture;
