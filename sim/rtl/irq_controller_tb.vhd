library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

use work.pRegisterBus.all;
use work.pBus_savestates.all;

-- Clean-room controller regression for the eight documented WonderSwan
-- hardware interrupt sources.  No cartridge, firmware, or title data is used.
--
-- Reference contract:
--   WSdev Interrupts rev 553:
--   https://ws.nesdev.org/w/index.php?title=Interrupts&oldid=553
--   ares 449b9371 interrupt controller:
--   https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cpu/interrupt.cpp#L1-L27
--   Mesen2 b9fa69dd controller:
--   https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsMemoryManager.cpp#L400-L428
entity irq_controller_tb is
end entity;

architecture tb of irq_controller_tb is
   signal clk        : std_logic := '0';
   signal ce         : std_logic := '1';
   signal reset      : std_logic := '0';
   signal irqrequest : std_logic;
   signal irqvector  : unsigned(9 downto 0);
   signal sources    : std_logic_vector(7 downto 0) := (others => '0');

   signal reg_din  : std_logic_vector(BUS_buswidth - 1 downto 0) := (others => '0');
   signal reg_adr  : std_logic_vector(BUS_busadr - 1 downto 0) := (others => '0');
   signal reg_wren : std_logic := '0';
   signal reg_rst  : std_logic := '0';
   signal reg_dout : std_logic_vector(BUS_buswidth - 1 downto 0);

   signal ss_din  : std_logic_vector(SSBUS_buswidth - 1 downto 0) := (others => '0');
   signal ss_adr  : std_logic_vector(SSBUS_busadr - 1 downto 0) := (others => '0');
   signal ss_wren : std_logic := '0';
   signal ss_rst  : std_logic := '0';
   signal ss_dout : std_logic_vector(SSBUS_buswidth - 1 downto 0);

   signal export_irq : std_logic_vector(7 downto 0);
begin
   clk <= not clk after 5 ns;

   dut : entity work.IRQ
      port map (
         clk => clk,
         ce => ce,
         reset => reset,
         isColor => '1',
         irqrequest => irqrequest,
         irqvector => irqvector,
         IRQ_LineComp => sources(4),
         IRQ_VBlankTmr => sources(5),
         IRQ_VBlank => sources(6),
         IRQ_HBlankTmr => sources(7),
         IRQ_SerialTX => sources(0),
         IRQ_Key => sources(1),
         IRQ_Cartridge => sources(2),
         IRQ_SerialRX => sources(3),
         RegBus_Din => reg_din,
         RegBus_Adr => reg_adr,
         RegBus_wren => reg_wren,
         RegBus_rst => reg_rst,
         RegBus_Dout => reg_dout,
         export_irq => export_irq,
         SSBus_Din => ss_din,
         SSBus_Adr => ss_adr,
         SSBus_wren => ss_wren,
         SSBus_rst => ss_rst,
         SSBus_Dout => ss_dout
      );

   stimulus : process
      procedure tick is
      begin
         wait until rising_edge(clk);
         wait for 1 ns;
      end procedure;

      procedure write_reg(address : natural; value : natural) is
      begin
         reg_adr <= std_logic_vector(to_unsigned(address, reg_adr'length));
         reg_din <= std_logic_vector(to_unsigned(value, reg_din'length));
         reg_wren <= '1';
         tick;
         reg_wren <= '0';
      end procedure;

      procedure expect_reg(address : natural; value : natural; message_text : string) is
      begin
         reg_adr <= std_logic_vector(to_unsigned(address, reg_adr'length));
         wait for 1 ns;
         assert reg_dout = std_logic_vector(to_unsigned(value, reg_dout'length))
            report message_text & ": expected " &
                   to_hstring(std_logic_vector(to_unsigned(value, reg_dout'length))) &
                   ", got " & to_hstring(reg_dout)
            severity failure;
      end procedure;

      procedure expect_vector(vector_number : natural; message_text : string) is
      begin
         wait for 1 ns;
         assert irqvector = to_unsigned(vector_number * 4, irqvector'length)
            report message_text & ": expected address " &
                   to_hstring(std_logic_vector(to_unsigned(vector_number * 4, irqvector'length))) &
                   ", got " & to_hstring(std_logic_vector(irqvector))
            severity failure;
      end procedure;

      procedure clear_pending is
      begin
         sources <= (others => '0');
         write_reg(16#B2#, 0);
         write_reg(16#B6#, 16#FF#);
         expect_reg(16#B4#, 0, "clear_pending");
         assert irqrequest = '0'
            report "clear_pending left CPU request asserted" severity failure;
      end procedure;

      variable bit_value : natural;
   begin
      -- Establish deterministic register and save-state defaults.
      reg_rst <= '1';
      ss_rst <= '1';
      reset <= '1';
      tick;
      reg_rst <= '0';
      ss_rst <= '0';
      reset <= '0';

      -- B0 masks an unaligned base immediately and the no-pending vector is the
      -- aligned base.  The CPU address is combinationally identical to B0 * 4.
      write_reg(16#B0#, 16#87#);
      expect_reg(16#B0#, 16#80#, "unaligned empty B0");
      expect_vector(16#80#, "unaligned empty CPU vector");

      -- A pulse that occurs while disabled must not be remembered, and later
      -- enabling the controller must not resurrect the missed pulse.
      sources <= (others => '1');
      tick;
      sources <= (others => '0');
      tick;
      expect_reg(16#B4#, 0, "disabled source pulse");
      write_reg(16#B2#, 16#FF#);
      tick;
      expect_reg(16#B4#, 0, "enable after disabled pulse");
      clear_pending;

      -- Exercise every documented source-to-status bit in isolation.  Checking
      -- the vector after the first event CE catches the former registered lag.
      for source_index in 0 to 7 loop
         bit_value := 2 ** source_index;
         write_reg(16#B2#, bit_value);
         sources(source_index) <= '1';
         tick;
         sources(source_index) <= '0';
         expect_reg(16#B4#, bit_value, "source mapping " & integer'image(source_index));
         expect_reg(16#B0#, 16#80# + source_index,
                    "B0 source mapping " & integer'image(source_index));
         expect_vector(16#80# + source_index,
                       "CPU source mapping " & integer'image(source_index));
         assert irqrequest = '1'
            report "source mapping did not request CPU for bit " & integer'image(source_index)
            severity failure;
         write_reg(16#B6#, bit_value);
         expect_reg(16#B4#, 0, "source ACK " & integer'image(source_index));
      end loop;

      -- With every source pending, bit 7 is highest priority.  Acknowledging
      -- each winner must hand off immediately through all lower priorities.
      write_reg(16#B2#, 16#FF#);
      sources <= (others => '1');
      tick;
      sources <= (others => '0');
      expect_reg(16#B4#, 16#FF#, "all sources pending");
      for source_index in 7 downto 0 loop
         expect_reg(16#B0#, 16#80# + source_index,
                    "priority B0 " & integer'image(source_index));
         expect_vector(16#80# + source_index,
                       "priority CPU vector " & integer'image(source_index));
         write_reg(16#B6#, 2 ** source_index);
      end loop;
      expect_reg(16#B4#, 0, "priority ACK drain");
      assert irqrequest = '0'
         report "priority ACK drain left request asserted" severity failure;

      -- W1C is a bit mask, not a single-winner acknowledgement.
      sources <= (others => '1');
      tick;
      sources <= (others => '0');
      write_reg(16#B6#, 16#A5#);
      expect_reg(16#B4#, 16#5A#, "masked W1C");
      write_reg(16#B6#, 16#5A#);
      expect_reg(16#B4#, 0, "masked W1C remainder");

      -- B4 is read-only.  Writes of both polarities must leave pending status
      -- untouched; only B6 owns software acknowledgement.
      sources(4) <= '1';
      tick;
      sources(4) <= '0';
      expect_reg(16#B4#, 16#10#, "B4 setup");
      write_reg(16#B4#, 0);
      expect_reg(16#B4#, 16#10#, "B4 zero write");
      write_reg(16#B4#, 16#FF#);
      expect_reg(16#B4#, 16#10#, "B4 ones write");
      write_reg(16#B6#, 16#10#);

      -- Clearing B2 after an enabled edge preserves not only B4/B0 but the
      -- actual CPU request and vector.  This is the critical dispatch case
      -- missed by the existing ROM probe.
      write_reg(16#B2#, 16#02#);
      sources(1) <= '1';
      tick;
      sources(1) <= '0';
      write_reg(16#B2#, 0);
      expect_reg(16#B4#, 16#02#, "pending survives enable clear");
      expect_reg(16#B0#, 16#81#, "B0 survives enable clear");
      expect_vector(16#81#, "CPU vector survives enable clear");
      assert irqrequest = '1'
         report "pending request was masked by cleared B2" severity failure;
      write_reg(16#B6#, 16#02#);
      assert irqrequest = '0'
         report "ACK did not cancel enable-cleared pending request" severity failure;

      -- TX, cartridge, and RX are level sources.  ACK cannot keep a live,
      -- enabled condition clear; it is requested again on the next controller
      -- CE.  Once B2 is clear, the same held level cannot relatch after ACK.
      for source_index in 0 to 3 loop
         if source_index /= 1 then
            bit_value := 2 ** source_index;
            write_reg(16#B2#, bit_value);
            sources(source_index) <= '1';
            tick;
            write_reg(16#B6#, bit_value);
            tick;
            expect_reg(16#B4#, bit_value,
                       "level reassert " & integer'image(source_index));
            write_reg(16#B2#, 0);
            write_reg(16#B6#, bit_value);
            expect_reg(16#B4#, 0,
                       "disabled level ACK " & integer'image(source_index));
            tick;
            expect_reg(16#B4#, 0,
                       "disabled held level " & integer'image(source_index));
            sources(source_index) <= '0';
         end if;
      end loop;

      report "PASS IRQ controller eight-source mapping, priority, persistence, W1C, and levels" severity note;
      std.env.stop;
      wait;
   end process;
end architecture;
