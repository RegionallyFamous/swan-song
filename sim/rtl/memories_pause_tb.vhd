library IEEE;
use IEEE.std_logic_1164.all;

entity memories_pause_tb is
end entity;

architecture test of memories_pause_tb is
   signal clk           : std_logic := '0';
   signal reset         : std_logic := '1';
   signal request       : std_logic := '0';
   signal safe_boundary : std_logic := '0';
   signal resume_ready  : std_logic := '0';
   signal pause_gate    : std_logic;
   signal pause_ack     : std_logic;
   signal issue_enable  : std_logic := '0';
   signal console_pulse : std_logic := '0';
begin
   clk <= not clk after 5 ns;

   dut : entity work.memories_pause
   port map
   (
      clk           => clk,
      reset         => reset,
      request       => request,
      safe_boundary => safe_boundary,
      resume_ready  => resume_ready,
      pause_gate    => pause_gate,
      pause_ack     => pause_ack
   );

   -- Model the relevant SwanTop clock-generator behavior: a requested enable
   -- becomes visible to the console after this edge unless the broker's gate
   -- is already high before the edge.  This catches a registered-only gate,
   -- which can otherwise acknowledge a snapshot after one extra CE pulse.
   process (clk)
   begin
      if rising_edge(clk) then
         console_pulse <= issue_enable and not pause_gate;
      end if;
   end process;

   process
      procedure tick is
      begin
         wait until rising_edge(clk);
         wait for 1 ns;
      end procedure;
   begin
      tick;
      tick;
      assert pause_gate = '0' and pause_ack = '0'
         report "reset did not leave pause broker idle" severity failure;

      reset <= '0';

      -- This is the production configuration today.  Boundary and resume
      -- activity must be completely transparent while request is tied low.
      for count in 0 to 15 loop
         if (count mod 2) = 0 then
            safe_boundary <= '1';
         else
            safe_boundary <= '0';
         end if;
         if (count mod 3) = 0 then
            resume_ready <= '1';
         else
            resume_ready <= '0';
         end if;
         tick;
         assert pause_gate = '0' and pause_ack = '0'
            report "disabled request changed normal-run pause outputs"
            severity failure;
      end loop;
      safe_boundary <= '0';
      resume_ready <= '0';

      -- A request is harmless until the console reports an exact boundary.
      request <= '1';
      tick;
      tick;
      assert pause_gate = '0' and pause_ack = '0'
         report "pause was acquired before a safe boundary" severity failure;

      -- Cancellation before acquisition has no runtime effect.
      request <= '0';
      tick;
      assert pause_gate = '0' and pause_ack = '0'
         report "pre-boundary cancellation was not inert" severity failure;

      -- A safe boundary first raises the gate.  Ack follows only after one
      -- complete gated interval.
      request <= '1';
      tick;
      assert pause_gate = '0' and pause_ack = '0'
         report "WAIT_BOUNDARY entry acquired too early" severity failure;

      safe_boundary <= '1';
      issue_enable <= '1';
      wait for 1 ns;
      assert pause_gate = '1'
         report "acquisition gate was not visible before the boundary edge"
         severity failure;
      tick;
      assert pause_gate = '1' and pause_ack = '0'
         report "safe boundary did not arm the held gate before ack" severity failure;
      assert console_pulse = '0'
         report "clock generator issued a console pulse on acquisition edge"
         severity failure;
      issue_enable <= '0';
      safe_boundary <= '0';
      tick;
      assert pause_gate = '1' and pause_ack = '1'
         report "pause was not acknowledged after one gated interval" severity failure;

      -- Boundary loss cannot release an owned pause; only request release can.
      tick;
      assert pause_gate = '1' and pause_ack = '1'
         report "owned pause did not remain stable" severity failure;

      request <= '0';
      tick;
      assert pause_gate = '0' and pause_ack = '1'
         report "release did not drop the gate while retaining ack" severity failure;
      tick;
      assert pause_ack = '1'
         report "ack fell before runtime warm-up" severity failure;

      -- A request during warm-up cannot reacquire behind the owner's back.
      request <= '1';
      safe_boundary <= '1';
      tick;
      assert pause_gate = '0' and pause_ack = '1'
         report "request was accepted before release completed" severity failure;

      safe_boundary <= '0';
      resume_ready <= '1';
      tick;
      assert pause_gate = '0' and pause_ack = '0'
         report "resume-ready did not complete release" severity failure;
      resume_ready <= '0';

      -- The still-held request is admitted as a fresh transaction only after
      -- the owner observed ack low.
      tick;
      assert pause_gate = '0' and pause_ack = '0'
         report "fresh request skipped boundary-wait state" severity failure;

      safe_boundary <= '1';
      issue_enable <= '1';
      wait for 1 ns;
      assert pause_gate = '1'
         report "fresh request did not pre-gate its boundary edge"
         severity failure;
      tick;
      assert pause_gate = '1' and pause_ack = '0'
         report "fresh request did not reacquire at safe boundary" severity failure;
      assert console_pulse = '0'
         report "fresh acquisition leaked a console pulse" severity failure;
      issue_enable <= '0';
      safe_boundary <= '0';
      tick;
      assert pause_gate = '1' and pause_ack = '1'
         report "fresh request was not acknowledged" severity failure;

      -- Lifecycle reset is the unconditional escape hatch shared with the
      -- future owner.
      reset <= '1';
      tick;
      assert pause_gate = '0' and pause_ack = '0'
         report "reset did not clear an owned pause" severity failure;

      report "PASS memories_pause_tb boundary/gate/ack/release/reset"
         severity note;
      wait;
   end process;
end architecture;
