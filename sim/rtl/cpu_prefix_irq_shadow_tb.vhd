library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

use work.pexport.all;
use work.pRegisterBus.all;
use work.pBus_savestates.all;

entity cpu_prefix_irq_shadow_tb is
end entity;

architecture test of cpu_prefix_irq_shadow_tb is
   subtype byte_type is std_logic_vector(7 downto 0);

   signal clk             : std_logic := '0';
   signal reset           : std_logic := '1';
   signal scenario        : natural range 1 to 5 := 1;
   signal cpu_idle        : std_logic;
   signal cpu_halt        : std_logic;
   signal cpu_irqrequest  : std_logic;
   signal cpu_prefix      : std_logic;
   signal cpu_export      : cpu_export_type;
   signal bus_addr        : unsigned(19 downto 0);
   signal bus_dataread    : std_logic_vector(15 downto 0);
   signal irqrequest_in   : std_logic := '0';
   signal regbus_din      : std_logic_vector(BUS_buswidth-1 downto 0);
   signal regbus_adr      : std_logic_vector(BUS_busadr-1 downto 0);
   signal regbus_wren     : std_logic;
   signal regbus_rden     : std_logic;
   signal ssbus_dout      : std_logic_vector(SSBUS_buswidth-1 downto 0);

   function program_byte(test_id : natural; address_in : natural)
      return byte_type is
      variable offset : natural := 0;
   begin
      if address_in = 16#02000# then
         return x"11";
      elsif address_in = 16#03000# then
         return x"22";
      elsif address_in < 16#ffff0# or address_in > 16#fffff# then
         return x"90";
      end if;

      offset := address_in - 16#ffff0#;
      case test_id is
         when 1 | 2 | 3 =>
            -- STI; NOP consumes the STI shadow; MOV Sreg; INC BX; HLT.
            case offset is
               when 0 => return x"fb";
               when 1 => return x"90";
               when 2 => return x"b8";
               when 3 => return x"00";
               when 4 => return x"00";
               when 5 =>
                  if test_id = 3 then return x"8c"; else return x"8e"; end if;
               when 6 =>
                  if test_id = 1 then
                     return x"d0"; -- MOV SS, AX (/2)
                  elsif test_id = 2 then
                     return x"d8"; -- MOV DS, AX (/3)
                  else
                     return x"d0"; -- MOV AX, SS (/2)
                  end if;
               when 7 => return x"43";
               when 8 => return x"f4";
               when others => return x"90";
            end case;

         when 4 =>
            -- DS=0000, ES=0100; ES:HLT must not leak ES into the MOV below.
            case offset is
               when  0 => return x"b8";
               when  1 => return x"00";
               when  2 => return x"00";
               when  3 => return x"8e";
               when  4 => return x"d8"; -- MOV DS, AX
               when  5 => return x"b8";
               when  6 => return x"00";
               when  7 => return x"01";
               when  8 => return x"8e";
               when  9 => return x"c0"; -- MOV ES, AX
               when 10 => return x"26"; -- ES prefix
               when 11 => return x"f4"; -- direct-to-IDLE HLT
               when 12 => return x"a0";
               when 13 => return x"00";
               when 14 => return x"20"; -- MOV AL, [2000h]
               when 15 => return x"f4";
               when others => return x"90";
            end case;

         when 5 =>
            -- LOCK is a prefix too: it must return to IDLE for the following
            -- harmless direct-address memory instruction.
            case offset is
               when 0 => return x"f0";
               when 1 => return x"8b";
               when 2 => return x"06";
               when 3 => return x"00";
               when 4 => return x"20"; -- MOV AX, [2000h]
               when 5 => return x"43"; -- terminal INC BX marker
               when 6 => return x"f4";
               when others => return x"90";
            end case;

         when others =>
            return x"90";
      end case;
   end function;
begin
   clk <= not clk after 5 ns;

   memory : process(all)
      variable address_value : natural;
   begin
      address_value := to_integer(bus_addr);
      bus_dataread <= program_byte(scenario, (address_value + 1) mod 16#100000#) &
                      program_byte(scenario, address_value);
   end process;

   dut : entity work.cpu
      generic map
      (
         is_simu => '1'
      )
      port map
      (
         clk                    => clk,
         ce                     => '1',
         ce_4x                  => '1',
         reset                  => reset,
         turbo                  => '0',
         SLOWTIMING             => '0',
         cpu_idle               => cpu_idle,
         cpu_halt               => cpu_halt,
         cpu_irqrequest         => cpu_irqrequest,
         cpu_prefix             => cpu_prefix,
         dma_active             => '0',
         sdma_request           => '0',
         canSpeedup             => open,
         bus_read               => open,
         bus_write              => open,
         bus_be                 => open,
         bus_addr               => bus_addr,
         bus_datawrite          => open,
         bus_dataread           => bus_dataread,
         irqrequest_in          => irqrequest_in,
         irqvector_in           => to_unsigned(16#20#, 10),
         load_savestate         => '0',
         cpu_done               => open,
         cpu_export             => cpu_export,
         debug_bus_fetch        => open,
         debug_bus_origin_exact => open,
         debug_instruction_id   => open,
         debug_instruction_pc   => open,
         RegBus_Din             => regbus_din,
         RegBus_Adr             => regbus_adr,
         RegBus_wren            => regbus_wren,
         RegBus_rden            => regbus_rden,
         RegBus_Dout            => (others => '0'),
         sleep_savestate        => '0',
         SSBUS_Din              => (others => '0'),
         SSBUS_Adr              => (others => '0'),
         SSBUS_wren             => '0',
         SSBUS_rst              => '0',
         SSBUS_Dout             => ssbus_dout
      );

   stimulus : process
      procedure start_case(test_id : natural) is
      begin
         scenario      <= test_id;
         irqrequest_in <= '0';
         reset         <= '1';
         wait until rising_edge(clk);
         wait until rising_edge(clk);
         wait until rising_edge(clk);
         reset <= '0';
      end procedure;

      procedure wait_for_boundary(ip_value : natural; description : string) is
         variable cycles : natural := 0;
      begin
         while not (cpu_idle = '1' and
                    cpu_export.reg_ip = to_unsigned(ip_value, 16)) and
               cycles < 1024 loop
            wait until rising_edge(clk);
            wait for 1 ns;
            cycles := cycles + 1;
         end loop;
         assert cpu_idle = '1' and cpu_export.reg_ip = to_unsigned(ip_value, 16)
            report description severity failure;
      end procedure;

      procedure wait_for_irq(description : string) is
         variable cycles : natural := 0;
      begin
         while cpu_irqrequest /= '1' and cycles < 128 loop
            wait until rising_edge(clk);
            wait for 1 ns;
            cycles := cycles + 1;
         end loop;
         assert cpu_irqrequest = '1' report description severity failure;
      end procedure;

      variable cycles : natural;
   begin
      -- MOV SS must delay an already-pending maskable interrupt until the
      -- following INC BX has retired.
      start_case(1);
      wait_for_boundary(7, "MOV SS boundary was not reached");
      irqrequest_in <= '1';
      wait_for_irq("IRQ was not accepted after the MOV SS shadow instruction");
      assert cpu_export.reg_bx = x"0001"
         report "MOV SS failed to inhibit IRQ for exactly one instruction" severity failure;

      -- MOV DS must not inherit MOV SS shadow behavior.
      start_case(2);
      wait_for_boundary(7, "MOV DS boundary was not reached");
      irqrequest_in <= '1';
      wait_for_irq("IRQ was not accepted immediately after MOV DS");
      assert cpu_export.reg_bx = x"0000"
         report "MOV DS incorrectly inhibited IRQ" severity failure;

      -- Opcode 8C moves from Sreg and must never create an interrupt shadow.
      start_case(3);
      wait_for_boundary(7, "MOV from Sreg boundary was not reached");
      irqrequest_in <= '1';
      wait_for_irq("IRQ was not accepted immediately after MOV from Sreg");
      assert cpu_export.reg_bx = x"0000"
         report "opcode 8C incorrectly inhibited IRQ" severity failure;

      -- A segment prefix before a direct-to-IDLE HLT is consumed by HLT. Wake
      -- with a masked IRQ and prove the following load still uses DS, not ES.
      start_case(4);
      cycles := 0;
      while not (cpu_halt = '1' and cpu_export.reg_ip = x"000c") and
            cycles < 1024 loop
         wait until rising_edge(clk);
         wait for 1 ns;
         cycles := cycles + 1;
      end loop;
      assert cpu_halt = '1' and cpu_export.reg_ip = x"000c"
         report "ES-prefixed HLT did not reach its idle boundary" severity failure;
      assert cpu_prefix = '0'
         report "prefix identity remained active after HLT completed" severity failure;
      irqrequest_in <= '1';
      wait until rising_edge(clk);
      wait for 1 ns;
      irqrequest_in <= '0';
      cycles := 0;
      while cpu_export.reg_ax(7 downto 0) = x"00" and cycles < 256 loop
         wait until rising_edge(clk);
         wait for 1 ns;
         cycles := cycles + 1;
      end loop;
      assert cpu_export.reg_ax(7 downto 0) = x"11"
         report "segment prefix leaked past direct-to-IDLE HLT" severity failure;

      -- LOCK must itself complete as a prefix so the following memory
      -- instruction retires and reaches the terminal marker.
      start_case(5);
      cycles := 0;
      while cpu_halt /= '1' and cycles < 512 loop
         wait until rising_edge(clk);
         wait for 1 ns;
         cycles := cycles + 1;
      end loop;
      assert cpu_halt = '1'
         report "LOCK prefix did not advance to its following instruction" severity failure;
      assert cpu_export.reg_ip = x"0007" and cpu_export.reg_bx = x"0001"
         report "LOCK-prefixed memory instruction did not reach its marker" severity failure;
      assert cpu_export.reg_ax = x"9011"
         report "LOCK-prefixed memory instruction returned the wrong value" severity failure;
      assert cpu_prefix = '0'
         report "LOCK prefix identity remained active at the completed boundary" severity failure;

      report "PASS cpu_prefix_irq_shadow_tb MOV-SS shadow, MOV-DS/8C negatives, and prefix cleanup"
         severity note;
      std.env.stop;
      wait;
   end process;
end architecture;
