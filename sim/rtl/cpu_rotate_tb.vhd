library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

use work.pexport.all;
use work.pRegisterBus.all;
use work.pBus_savestates.all;

entity cpu_rotate_tb is
end entity;

architecture test of cpu_rotate_tb is
   subtype byte_type is std_logic_vector(7 downto 0);

   signal clk             : std_logic := '0';
   signal reset           : std_logic := '1';
   signal test_opcode     : byte_type := x"D0";
   signal test_right      : boolean := false;
   signal test_high_byte  : boolean := false;
   signal test_count      : natural range 0 to 255 := 0;
   signal cpu_idle        : std_logic;
   signal cpu_halt        : std_logic;
   signal cpu_done_signal : std_logic;
   signal cpu_export      : cpu_export_type;
   signal bus_addr        : unsigned(19 downto 0);
   signal bus_dataread    : std_logic_vector(15 downto 0);
   signal regbus_din      : std_logic_vector(BUS_buswidth-1 downto 0);
   signal regbus_adr      : std_logic_vector(BUS_busadr-1 downto 0);
   signal regbus_wren     : std_logic;
   signal regbus_rden     : std_logic;
   signal ssbus_din       : std_logic_vector(SSBUS_buswidth-1 downto 0) := (others => '0');
   signal ssbus_adr       : std_logic_vector(SSBUS_busadr-1 downto 0) := (others => '0');
   signal ssbus_wren      : std_logic := '0';
   signal ssbus_dout      : std_logic_vector(SSBUS_buswidth-1 downto 0);

   type rotate_expected_type is record
      operand  : unsigned(15 downto 0);
      carry    : std_logic;
      overflow : std_logic;
   end record;

   type count_array_type is array (natural range <>) of natural;
   constant byte_counts : count_array_type :=
      (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
       16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
       32, 33, 255);
   constant word_counts : count_array_type :=
      (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
       16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
       32, 33, 255);

   constant byte_operand       : unsigned(15 downto 0) := x"A596";
   constant word_operand       : unsigned(15 downto 0) := x"A55A";
   constant cx_prefix          : unsigned(15 downto 0) := x"BE00";
   constant dx_sentinel        : unsigned(15 downto 0) := x"C35A";
   constant input_flags_a      : unsigned(15 downto 0) := x"8D44";
   constant input_flags_b      : unsigned(15 downto 0) := x"0290";
   constant unaffected_mask    : unsigned(15 downto 0) := x"87D4";
   constant unaffected_a       : unsigned(15 downto 0) := x"8544";
   constant unaffected_b       : unsigned(15 downto 0) := x"0290";

   function current_rotate_model(
      operand_in : unsigned(15 downto 0);
      width      : natural;
      right      : boolean;
      high_byte  : boolean;
      carry_in   : std_logic;
      raw_count  : natural)
      return rotate_expected_type is
      variable expected   : rotate_expected_type;
      variable result     : unsigned(15 downto 0) := operand_in;
      variable carry_work : std_logic := carry_in;
      variable carry_next : std_logic;
      variable count      : natural := raw_count mod 32;
      variable msb_index  : natural;
   begin
      -- This deliberately models the current core, including OF behavior
      -- which is architecturally undefined for counts greater than one and
      -- should ordinarily remain unchanged for an effective count of zero.
      for i in 1 to count loop
         if right then
            if width = 8 and high_byte then
               carry_next := result(8);
               result(15 downto 8) := carry_work & result(15 downto 9);
            elsif width = 8 then
               carry_next := result(0);
               result(7 downto 0) := carry_work & result(7 downto 1);
            else
               carry_next := result(0);
               result := carry_work & result(15 downto 1);
            end if;
         else
            if width = 8 and high_byte then
               carry_next := result(15);
               result(15 downto 8) := result(14 downto 8) & carry_work;
            elsif width = 8 then
               carry_next := result(7);
               result(7 downto 0) := result(6 downto 0) & carry_work;
            else
               carry_next := result(15);
               result := result(14 downto 0) & carry_work;
            end if;
         end if;
         carry_work := carry_next;
      end loop;

      expected.operand  := result;
      expected.carry    := carry_work;
      if width = 8 and high_byte then msb_index := 15; else msb_index := width - 1; end if;
      expected.overflow := operand_in(msb_index) xor result(msb_index);
      return expected;
   end function;

   function program_byte(
      opcode_in : byte_type;
      right     : boolean;
      high_byte : boolean;
      count     : natural;
      address_in : natural)
      return byte_type is
      variable offset : natural;
   begin
      if address_in < 16#FFFF0# or address_in > 16#FFFFF# then
         return x"90";
      end if;

      offset := address_in - 16#FFFF0#;
      case offset is
         when 0 =>
            return opcode_in;
         when 1 =>
            if right and high_byte then
               return x"DC";
            elsif right then
               return x"D8";
            elsif high_byte then
               return x"D4";
            else
               return x"D0";
            end if;
         when 2 =>
            if opcode_in = x"C0" or opcode_in = x"C1" then
               return std_logic_vector(to_unsigned(count, 8));
            else
               return x"F4";
            end if;
         when 3 =>
            return x"F4";
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
      bus_dataread <= program_byte(test_opcode, test_right, test_high_byte, test_count,
                                   (address_value + 1) mod 16#100000#) &
                      program_byte(test_opcode, test_right, test_high_byte, test_count,
                                   address_value);
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
         cpu_irqrequest         => open,
         cpu_prefix             => open,
         dma_active             => '0',
         sdma_request           => '0',
         canSpeedup             => open,
         bus_read               => open,
         bus_write              => open,
         bus_be                 => open,
         bus_addr               => bus_addr,
         bus_datawrite          => open,
         bus_dataread           => bus_dataread,
         irqrequest_in          => '0',
         irqvector_in           => (others => '0'),
         load_savestate         => '0',
         cpu_done               => cpu_done_signal,
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
         SSBUS_Din              => ssbus_din,
         SSBUS_Adr              => ssbus_adr,
         SSBUS_wren             => ssbus_wren,
         SSBUS_rst              => '0',
         SSBUS_Dout             => ssbus_dout
      );

   stimulus : process
      type cycle_array_type is array (0 to 5) of natural;
      variable observed_cycles : cycle_array_type := (others => 0);

      function opcode_slot(opcode : byte_type) return natural is
      begin
         case opcode is
            when x"D0" => return 0;
            when x"D1" => return 1;
            when x"D2" => return 2;
            when x"D3" => return 3;
            when x"C0" => return 4;
            when others => return 5;
         end case;
      end function;

      function expected_cycle_count(opcode : byte_type) return natural is
      begin
         case opcode is
            when x"D0" | x"D1" => return 13;
            when x"D2" | x"D3" => return 15;
            when x"C0" | x"C1" => return 16;
            when others => return 0;
         end case;
      end function;

      procedure run_case(
         opcode    : byte_type;
         width     : natural;
         right     : boolean;
         high_byte : boolean;
         carry_in  : std_logic;
         raw_count : natural;
         flags_b   : boolean) is
         variable operand       : unsigned(15 downto 0);
         variable expected      : rotate_expected_type;
         variable cpu1_image    : std_logic_vector(63 downto 0);
         variable cpu4_image    : std_logic_vector(63 downto 0);
         variable flags_image   : unsigned(15 downto 0);
         variable unaffected_expected : unsigned(15 downto 0);
         variable cycles        : natural := 0;
         variable halt_cycles   : natural := 0;
         variable slot          : natural;
         variable expected_ip   : unsigned(15 downto 0);
      begin
         if width = 8 then operand := byte_operand; else operand := word_operand; end if;
         expected := current_rotate_model(operand, width, right, high_byte,
                                          carry_in, raw_count);
         if flags_b then
            flags_image := input_flags_b;
            unaffected_expected := unaffected_b;
         else
            flags_image := input_flags_a;
            unaffected_expected := unaffected_a;
         end if;
         flags_image(0) := carry_in;

         test_opcode <= opcode;
         test_right  <= right;
         test_high_byte <= high_byte;
         test_count  <= raw_count;
         reset       <= '1';
         ssbus_wren  <= '0';
         wait until rising_edge(clk);
         wait for 1 ns;

         cpu1_image := std_logic_vector(dx_sentinel) &
                       std_logic_vector(cx_prefix or to_unsigned(raw_count, 16)) &
                       std_logic_vector(operand) & x"0000";
         ssbus_din  <= cpu1_image;
         ssbus_adr  <= std_logic_vector(to_unsigned(0, SSBUS_busadr));
         ssbus_wren <= '1';
         wait until rising_edge(clk);
         wait for 1 ns;

         cpu4_image := (others => '0');
         cpu4_image(31 downto 16) := std_logic_vector(flags_image);
         ssbus_din <= cpu4_image;
         ssbus_adr <= std_logic_vector(to_unsigned(3, SSBUS_busadr));
         wait until rising_edge(clk);
         wait for 1 ns;

         ssbus_wren <= '0';
         wait until rising_edge(clk);
         wait for 1 ns;
         reset <= '0';

         while cpu_done_signal /= '1' and cycles < 256 loop
            wait until rising_edge(clk);
            wait for 1 ns;
            cycles := cycles + 1;
         end loop;
         assert cpu_done_signal = '1'
            report "rotate instruction did not retire" severity failure;
         assert cycles = expected_cycle_count(opcode)
            report "rotate retirement timing changed for opcode " &
                   to_hstring(opcode) severity failure;

         slot := opcode_slot(opcode);
         if observed_cycles(slot) = 0 then
            observed_cycles(slot) := cycles;
            report "rotate opcode " & to_hstring(opcode) &
                   " retires in " & natural'image(cycles) & " clocks" severity note;
         else
            assert cycles = observed_cycles(slot)
               report "rotate cycle count varied with direction/count/carry" severity failure;
         end if;

         while cpu_halt /= '1' and halt_cycles < 64 loop
            wait until rising_edge(clk);
            wait for 1 ns;
            halt_cycles := halt_cycles + 1;
         end loop;
         assert cpu_halt = '1' report "terminal HLT was not reached" severity failure;

         if opcode = x"C0" or opcode = x"C1" then
            expected_ip := to_unsigned(4, 16);
         else
            expected_ip := to_unsigned(3, 16);
         end if;
         assert cpu_export.reg_ip = expected_ip
            report "unexpected terminal IP" severity failure;
         assert cpu_export.reg_ax = expected.operand
            report "wrong RCL/RCR result" severity failure;
         assert cpu_export.reg_f(0) = expected.carry
            report "wrong RCL/RCR carry" severity failure;
         assert cpu_export.reg_f(11) = expected.overflow
            report "wrong current-RTL RCL/RCR overflow" severity failure;
         assert (cpu_export.reg_f and unaffected_mask) = unaffected_expected
            report "RCL/RCR changed an unaffected flag" severity failure;
         assert cpu_export.reg_cx = (cx_prefix or to_unsigned(raw_count, 16))
            report "RCL/RCR changed CX/CL" severity failure;
         assert cpu_export.reg_dx = dx_sentinel
            report "RCL/RCR changed neighboring DX" severity failure;
         if width = 8 then
            if high_byte then
               assert cpu_export.reg_ax(7 downto 0) = byte_operand(7 downto 0)
                  report "AH RCL/RCR changed neighboring AL" severity failure;
            else
               assert cpu_export.reg_ax(15 downto 8) = byte_operand(15 downto 8)
                  report "AL RCL/RCR changed neighboring AH" severity failure;
            end if;
         end if;
      end procedure;
   begin
      -- D0/D1 establish both directions and carry inputs for implicit count 1.
      for direction in 0 to 1 loop
         for carry in 0 to 1 loop
            for high_byte in 0 to 1 loop
               if carry = 0 then
                  run_case(x"D0", 8, direction = 1, high_byte = 1, '0', 1,
                           ((direction + high_byte) mod 2) = 1);
               else
                  run_case(x"D0", 8, direction = 1, high_byte = 1, '1', 1,
                           ((direction + high_byte) mod 2) = 0);
               end if;
            end loop;
            if carry = 0 then
               run_case(x"D1", 16, direction = 1, false, '0', 1,
                        (direction mod 2) = 1);
            else
               run_case(x"D1", 16, direction = 1, false, '1', 1,
                        (direction mod 2) = 0);
            end if;
         end loop;
      end loop;

      -- D2/D3 and C0/C1 cover masked count boundaries and the 9/17-bit
      -- through-carry ring periods, including raw values beyond 31.
      for direction in 0 to 1 loop
         for i in byte_counts'range loop
            for carry in 0 to 1 loop
               for high_byte in 0 to 1 loop
                  if carry = 0 then
                     run_case(x"D2", 8, direction = 1, high_byte = 1, '0',
                              byte_counts(i),
                              ((direction + i + high_byte) mod 2) = 1);
                     run_case(x"C0", 8, direction = 1, high_byte = 1, '0',
                              byte_counts(i),
                              ((direction + i + high_byte) mod 2) = 0);
                  else
                     run_case(x"D2", 8, direction = 1, high_byte = 1, '1',
                              byte_counts(i),
                              ((direction + i + high_byte) mod 2) = 0);
                     run_case(x"C0", 8, direction = 1, high_byte = 1, '1',
                              byte_counts(i),
                              ((direction + i + high_byte) mod 2) = 1);
                  end if;
               end loop;
            end loop;
         end loop;
         for i in word_counts'range loop
            for carry in 0 to 1 loop
               if carry = 0 then
                  run_case(x"D3", 16, direction = 1, false, '0', word_counts(i),
                           ((direction + i) mod 2) = 1);
                  run_case(x"C1", 16, direction = 1, false, '0', word_counts(i),
                           ((direction + i) mod 2) = 0);
               else
                  run_case(x"D3", 16, direction = 1, false, '1', word_counts(i),
                           ((direction + i) mod 2) = 0);
                  run_case(x"C1", 16, direction = 1, false, '1', word_counts(i),
                           ((direction + i) mod 2) = 1);
               end if;
            end loop;
         end loop;
      end loop;

      report "PASS cpu_rotate_tb D0/D1/D2/D3/C0/C1 RCL/RCR compatibility matrix"
         severity note;
      std.env.stop;
      wait;
   end process;
end architecture;
