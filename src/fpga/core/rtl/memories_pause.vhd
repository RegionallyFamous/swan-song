library IEEE;
use IEEE.std_logic_1164.all;

-- Cooperative runtime pause boundary for the future Memories v2 owner.
--
-- A request cannot gate the emulated clock enables until SwanTop reports an
-- instruction/HALT boundary with DMA and IRQ dispatch quiescent.  The
-- acknowledgement is delayed for one complete gated clock so the owner never
-- treats the acquisition edge itself as a frozen snapshot.  On release the
-- acknowledgement remains asserted until SwanTop's normal clock-enable
-- warm-up has completed.
entity memories_pause is
   port
   (
      clk             : in  std_logic;
      reset           : in  std_logic;
      request         : in  std_logic;
      safe_boundary   : in  std_logic;
      resume_ready    : in  std_logic;
      pause_gate      : out std_logic := '0';
      pause_ack       : out std_logic := '0'
   );
end entity;

architecture rtl of memories_pause is
   type tstate is
   (
      IDLE,
      WAIT_BOUNDARY,
      ARM_ACK,
      PAUSED,
      WAIT_RESUME
   );

   signal state : tstate := IDLE;
   signal pause_gate_held : std_logic := '0';
begin
   -- The acquisition term is deliberately combinational.  SwanTop's clock
   -- generator and this state machine sample their inputs on the same edge;
   -- waiting until that edge to register the gate would let the generator
   -- schedule one final CE/CE_4x pulse after safe_boundary was sampled.  Once
   -- WAIT_BOUNDARY observes a safe interval, expose the gate before the edge
   -- and retain it in pause_gate_held until release.
   pause_gate <= pause_gate_held or
      (request and safe_boundary) when
         state = WAIT_BOUNDARY else
      pause_gate_held;

   process (clk)
   begin
      if rising_edge(clk) then
         if reset = '1' then
            state           <= IDLE;
            pause_gate_held <= '0';
            pause_ack       <= '0';
         else
            case state is
               when IDLE =>
                  pause_gate_held <= '0';
                  pause_ack       <= '0';
                  if request = '1' then
                     state <= WAIT_BOUNDARY;
                  end if;

               when WAIT_BOUNDARY =>
                  pause_gate_held <= '0';
                  pause_ack       <= '0';
                  if request = '0' then
                     state <= IDLE;
                  elsif safe_boundary = '1' then
                     pause_gate_held <= '1';
                     state           <= ARM_ACK;
                  end if;

               when ARM_ACK =>
                  if request = '1' then
                     -- pause_gate was already high for the complete prior
                     -- clock interval, so the runtime is now frozen.
                     pause_gate_held <= '1';
                     pause_ack       <= '1';
                     state           <= PAUSED;
                  else
                     -- A cancelled acquisition still observes the normal
                     -- resume warm-up before admitting another request.
                     pause_gate_held <= '0';
                     pause_ack       <= '0';
                     state           <= WAIT_RESUME;
                  end if;

               when PAUSED =>
                  pause_gate_held <= '1';
                  pause_ack       <= '1';
                  if request = '0' then
                     pause_gate_held <= '0';
                     state           <= WAIT_RESUME;
                  end if;

               when WAIT_RESUME =>
                  pause_gate_held <= '0';
                  if resume_ready = '1' then
                     pause_ack <= '0';
                     state     <= IDLE;
                  end if;
            end case;
         end if;
      end if;
   end process;
end architecture;
