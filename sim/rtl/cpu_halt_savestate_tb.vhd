library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

use work.pexport.all;
use work.pRegisterBus.all;
use work.pBus_savestates.all;
use work.pReg_savestates.all;

entity cpu_halt_savestate_tb is
end entity;

architecture test of cpu_halt_savestate_tb is
   signal clk             : std_logic := '0';
   signal ce              : std_logic := '1';
   signal ce_4x           : std_logic := '1';
   signal reset           : std_logic := '1';
   signal cpu_halt        : std_logic;
   signal cpu_done        : std_logic;
   signal cpu_export      : cpu_export_type;
   signal bus_read        : std_logic;
   signal bus_write       : std_logic;
   signal bus_be          : std_logic_vector(1 downto 0);
   signal bus_addr        : unsigned(19 downto 0);
   signal bus_datawrite   : std_logic_vector(15 downto 0);
   signal bus_dataread    : std_logic_vector(15 downto 0);
   signal irqrequest_in   : std_logic := '0';
   signal regbus_din      : std_logic_vector(BUS_buswidth-1 downto 0);
   signal regbus_adr      : std_logic_vector(BUS_busadr-1 downto 0);
   signal regbus_wren     : std_logic;
   signal regbus_rden     : std_logic;
   signal ssbus_din       : std_logic_vector(SSBUS_buswidth-1 downto 0) := (others => '0');
   signal ssbus_adr       : std_logic_vector(SSBUS_busadr-1 downto 0) := (others => '0');
   signal ssbus_wren      : std_logic := '0';
   signal ssbus_rst       : std_logic := '0';
   signal ssbus_dout      : std_logic_vector(SSBUS_buswidth-1 downto 0);
   signal debug_id        : std_logic_vector(31 downto 0);

   function memory_word(address_in : unsigned(19 downto 0))
      return std_logic_vector is
   begin
      case to_integer(address_in) is
         -- Reset vector: STI; HLT; NOP; NOP. Words are little-endian.
         when 16#ffff0# => return x"f4fb";
         when 16#ffff2# => return x"9090";
         -- External interrupt vector at 20h: 0000:0100.
         when 16#00020# => return x"0100";
         when 16#00022# => return x"0000";
         when others     => return x"9090";
      end case;
   end function;
begin
   clk <= not clk after 5 ns;
   bus_dataread <= memory_word(bus_addr);

   dut : entity work.cpu
      generic map
      (
         is_simu => '1'
      )
      port map
      (
         clk                    => clk,
         ce                     => ce,
         ce_4x                  => ce_4x,
         reset                  => reset,
         turbo                  => '0',
         SLOWTIMING             => '0',
         cpu_idle               => open,
         cpu_halt               => cpu_halt,
         cpu_irqrequest         => open,
         cpu_prefix             => open,
         dma_active             => '0',
         sdma_request           => '0',
         canSpeedup             => open,
         bus_read               => bus_read,
         bus_write              => bus_write,
         bus_be                 => bus_be,
         bus_addr               => bus_addr,
         bus_datawrite          => bus_datawrite,
         bus_dataread           => bus_dataread,
         irqrequest_in          => irqrequest_in,
         irqvector_in           => to_unsigned(16#20#, 10),
         load_savestate         => '0',
         cpu_done               => cpu_done,
         cpu_export             => cpu_export,
         debug_bus_fetch        => open,
         debug_bus_origin_exact => open,
         debug_instruction_id   => debug_id,
         debug_instruction_pc   => open,
         RegBus_Din             => regbus_din,
         RegBus_Adr             => regbus_adr,
         RegBus_wren            => regbus_wren,
         RegBus_rden            => regbus_rden,
         RegBus_Dout            => (others => '0'),
         sleep_savestate        => '0',
         SSBUS_Din              => ssbus_din,
         SSBUS_Adr              => ssbus_adr,
         SSBUS_wren             => ssbus_wren,
         SSBUS_rst              => ssbus_rst,
         SSBUS_Dout             => ssbus_dout
      );

   stimulus : process
      type state_words is array (0 to 3) of
         std_logic_vector(SSBUS_buswidth-1 downto 0);
      variable saved_state : state_words;
      variable halted_ip   : unsigned(15 downto 0);
      variable halted_id   : std_logic_vector(31 downto 0);
      variable cycles      : natural;
   begin
      wait until rising_edge(clk);
      wait until rising_edge(clk);
      reset <= '0';

      cycles := 0;
      while cpu_halt /= '1' and cycles < 512 loop
         wait until rising_edge(clk);
         cycles := cycles + 1;
      end loop;
      assert cpu_halt = '1'
         report "reset-vector STI/HLT program did not halt" severity failure;
      assert cpu_export.reg_ip = x"0002"
         report "HLT did not leave IP at the following instruction" severity failure;
      assert cpu_export.reg_f(9) = '1'
         report "STI did not set IF before HLT" severity failure;

      for i in saved_state'range loop
         ssbus_adr <= std_logic_vector(to_unsigned(i, SSBUS_busadr));
         wait for 1 ns;
         saved_state(i) := ssbus_dout;
      end loop;
      assert saved_state(3)(REG_SAVESTATE_CPU4_HALT_BIT) = '1'
         report "CPU4 did not serialize HALT in the compatible FLAGS bit" severity failure;

      -- A reset against the legacy/default CPU4 word clears HALT. This also
      -- proves old state images, whose reserved FLAGS bit is zero, remain
      -- compatible.
      reset <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert cpu_halt = '0'
         report "legacy CPU4 default unexpectedly restored HALT" severity failure;

      -- Refill the four CPU register words exactly as the state manager does,
      -- then give the CPU a reset edge to restore them.
      for i in saved_state'range loop
         ssbus_adr  <= std_logic_vector(to_unsigned(i, SSBUS_busadr));
         ssbus_din  <= saved_state(i);
         ssbus_wren <= '1';
         wait until rising_edge(clk);
      end loop;
      ssbus_wren <= '0';
      wait until rising_edge(clk);
      wait for 1 ns;
      assert cpu_halt = '1'
         report "saved HALT did not restore" severity failure;
      assert cpu_export.reg_ip = x"0002"
         report "saved IP did not restore with HALT" severity failure;

      reset     <= '0';
      halted_ip := cpu_export.reg_ip;
      halted_id := debug_id;
      for i in 1 to 64 loop
         wait until rising_edge(clk);
         wait for 1 ns;
         assert cpu_halt = '1'
            report "restored CPU left HALT without an interrupt" severity failure;
         assert cpu_export.reg_ip = halted_ip
            report "restored halted CPU executed an instruction" severity failure;
         assert debug_id = halted_id
            report "restored halted CPU advanced its instruction identity" severity failure;
      end loop;

      irqrequest_in <= '1';
      wait until rising_edge(clk);
      irqrequest_in <= '0';
      cycles := 0;
      while cpu_halt /= '0' and cycles < 8 loop
         wait until rising_edge(clk);
         cycles := cycles + 1;
      end loop;
      assert cpu_halt = '0'
         report "maskable interrupt did not wake restored HALT" severity failure;

      report "PASS cpu_halt_savestate_tb legacy-compatible HALT round-trip and IRQ wake"
         severity note;
      std.env.stop;
      wait;
   end process;
end architecture;
