library IEEE;
use IEEE.std_logic_1164.all;  
use IEEE.numeric_std.all; 

use work.pRegisterBus.all;  
use work.pBus_savestates.all;
use work.pReg_savestates.all; 
use work.pReg_swan.all;

entity memorymux is
   port 
   (
      clk                  : in  std_logic;
      clk_ram              : in  std_logic;
      ce                   : in  std_logic;
      reset                : in  std_logic;
      isColor              : in  std_logic;
      preserve_internal_eeprom : in std_logic;
      
      maskAddr             : in  std_logic_vector(23 downto 0);
      romtype              : in  std_logic_vector(7 downto 0);
      ramtype              : in  std_logic_vector(7 downto 0);
      
      eepromWrite          : out std_logic;
      eeprom_addr          : in  std_logic_vector(9 downto 0);
      eeprom_din           : in  std_logic_vector(15 downto 0);
      eeprom_dout          : out std_logic_vector(15 downto 0);
      eeprom_req           : in  std_logic;
      eeprom_rnw           : in  std_logic;

      internal_eeprom_bank : in  std_logic;
      internal_eeprom_addr : in  std_logic_vector(9 downto 0);
      internal_eeprom_din  : in  std_logic_vector(15 downto 0);
      internal_eeprom_dout : out std_logic_vector(15 downto 0);
      internal_eeprom_req  : in  std_logic;
      internal_eeprom_rnw  : in  std_logic;
      
      cpu_read             : in  std_logic;
      cpu_write            : in  std_logic;
      cpu_be               : in  std_logic_vector(1 downto 0) := "00";
      cpu_addr             : in  unsigned(19 downto 0);
      cpu_datawrite        : in  std_logic_vector(15 downto 0);
      cpu_dataread         : out std_logic_vector(15 downto 0);

      -- Resolved request mapping for simulation provenance. Offset is the
      -- exact masked byte offset, including address bit 0.
      debug_mem_space        : out std_logic_vector(3 downto 0) := (others => '0');
      debug_mem_offset       : out std_logic_vector(23 downto 0) := (others => '0');
      debug_mem_offset_valid : out std_logic := '0';
      debug_gpu_collision    : out std_logic := '0';
      
      GPU_addr             : in  std_logic_vector(15 downto 0);
      GPU_dataread         : out std_logic_vector(15 downto 0);   
      
      Color_addr           : in  std_logic_vector(7 downto 0);
      Color_dataread       : out std_logic_vector(15 downto 0);    
      
      bios_wraddr          : in  std_logic_vector(12 downto 0);
      bios_wrdata          : in  std_logic_vector(15 downto 0);
      bios_wr              : in  std_logic;
      bios_wrcolor         : in  std_logic;
      
      RegBus_Din           : in  std_logic_vector(BUS_buswidth-1 downto 0);
      RegBus_Adr           : in  std_logic_vector(BUS_busadr-1 downto 0);
      RegBus_wren          : in  std_logic;
      RegBus_rst           : in  std_logic;
      RegBus_Dout          : out std_logic_vector(BUS_buswidth-1 downto 0);
      
      EXTRAM_read          : out std_logic;
      EXTRAM_write         : out std_logic;
      EXTRAM_be            : out std_logic_vector(1 downto 0);
      EXTRAM_addr          : out std_logic_vector(24 downto 0);
      EXTRAM_datawrite     : out std_logic_vector(15 downto 0);
      EXTRAM_dataread      : in  std_logic_vector(15 downto 0); 
      
      -- savestates              
      sleep_savestate      : in  std_logic;
      
      SSBus_Din            : in  std_logic_vector(SSBUS_buswidth-1 downto 0);
      SSBus_Adr            : in  std_logic_vector(SSBUS_busadr-1 downto 0);
      SSBus_wren           : in  std_logic;
      SSBus_rst            : in  std_logic;
      SSBus_Dout           : out std_logic_vector(SSBUS_buswidth-1 downto 0);
      
      SSMEM_Addr           : in  std_logic_vector(18 downto 0);
      SSMEM_RdEn           : in  std_logic_vector( 2 downto 0);
      SSMEM_WrEn           : in  std_logic_vector( 2 downto 0);
      SSMEM_WriteData      : in  std_logic_vector(15 downto 0);
      SSMEM_ReadData_REG   : out std_logic_vector(15 downto 0);
      SSMEM_ReadData_RAM   : out std_logic_vector(15 downto 0);
      SSMEM_ReadData_SRAM  : out std_logic_vector(15 downto 0)
   );
end entity;

architecture arch of memorymux is
  
   -- register
   signal BANK_ROM2        : std_logic_vector(REG_BANK_ROM2.upper downto REG_BANK_ROM2.lower);
   signal BANK_SRAM        : std_logic_vector(REG_BANK_SRAM.upper downto REG_BANK_SRAM.lower);
   signal BANK_ROM0        : std_logic_vector(REG_BANK_ROM0.upper downto REG_BANK_ROM0.lower);
   signal BANK_ROM1        : std_logic_vector(REG_BANK_ROM1.upper downto REG_BANK_ROM1.lower);
   signal mapper_2003_selected : std_logic;
   signal mapper_RegBus_Adr : std_logic_vector(BUS_busadr-1 downto 0);
   signal flash_enable     : std_logic := '0';
   
   signal HW_FLAGS_read    : std_logic_vector(REG_HW_FLAGS.upper downto REG_HW_FLAGS.lower);
   signal HW_FLAGS_written : std_logic;
   signal HW_FLAGS_set     : std_logic;
   
   type t_reg_wired_or is array(0 to 7) of std_logic_vector(7 downto 0);
   signal reg_wired_or : t_reg_wired_or;
  
   -- masks from header
   signal rommask          : std_logic_vector(23 downto 0);
   signal sramMask         : std_logic_vector(23 downto 0);
  
   -- cpu
   type tMemAccessType is 
   (
      BIOS,
      BIOSCOLOR,
      EXTRAM,
      RAMACC,
      UNMAPPED,
      ZERO
   );
   signal MemAccessType          : tMemAccessType; 
   signal MemAccessTypeNew       : tMemAccessType; 
   
   signal cpu_dataread_16        : std_logic_vector(15 downto 0);
   signal cpu_unaligned          : std_logic;
  
   -- BIOS non-color
   signal BIOS_address           : std_logic_vector(10 downto 0);
   signal BIOS_data              : std_logic_vector(15 downto 0);   
   
   signal BIOS_addressColor      : std_logic_vector(11 downto 0);
   signal BIOS_dataColor         : std_logic_vector(15 downto 0);
            
   -- 64kbyte ram    
   signal RAM_addressCPU         : std_logic_vector(14 downto 0);
   signal RAM_dataReadCPU        : std_logic_vector(15 downto 0);
   signal RAM_dataWriteCPU       : std_logic_vector(15 downto 0);
   signal RAM_dataWriteEnable    : std_logic_vector(1 downto 0);
   
   -- palette ram
   signal Palette_WriteEnable    : std_logic_vector(1 downto 0);
         
   -- savestates     
   type t_ss_wired_or is array(0 to 1) of std_logic_vector(63 downto 0);
   signal ss_wired_or : t_ss_wired_or;

begin 

   -- Intel altsyncram leaves mixed-port read-during-write data unspecified
   -- unless a mode is selected. Flag same-word collisions so simulation
   -- provenance does not overstate the returned display word's certainty.
   debug_gpu_collision <= '1' when RAM_dataWriteEnable /= "00" and
                                  RAM_addressCPU = GPU_addr(15 downto 1)
                          else '0';

   -- Bandai 2003 mirrors the standard byte-wide mapper registers at CF/D0,
   -- D2, and D4. D0/D2/D4 are the low bytes of wider registers; their upper
   -- bytes select ROM above this core's explicitly unsupported 16 MiB
   -- aperture. Keep the inherited C0-C3 path exact for Bandai 2001 and only
   -- expose the aliases when the cartridge footer selects the 2003 mapper.
   -- romtype carries footer RTC byte -3, despite its inherited name. Existing
   -- ROM metadata uses canonical value 01 as the Bandai 2003 selector. Keep
   -- this signal name stable because the checked-in SignalTap setup refers to
   -- it hierarchically.
   mapper_2003_selected <= '1' when romtype = x"01" else '0';
   mapper_RegBus_Adr <= x"C0" when mapper_2003_selected = '1' and RegBus_Adr = x"CF" else
                        x"C1" when mapper_2003_selected = '1' and RegBus_Adr = x"D0" else
                        x"C2" when mapper_2003_selected = '1' and RegBus_Adr = x"D2" else
                        x"C3" when mapper_2003_selected = '1' and RegBus_Adr = x"D4" else
                        RegBus_Adr;

   iREG_BANK_ROM2   : entity work.eReg generic map ( REG_BANK_ROM2   ) port map (clk, RegBus_Din, mapper_RegBus_Adr, RegBus_wren, RegBus_rst, reg_wired_or( 0), BANK_ROM2    , BANK_ROM2);
   iREG_BANK_SRAM   : entity work.eReg generic map ( REG_BANK_SRAM   ) port map (clk, RegBus_Din, mapper_RegBus_Adr, RegBus_wren, RegBus_rst, reg_wired_or( 1), BANK_SRAM    , BANK_SRAM);
   iREG_BANK_ROM0   : entity work.eReg generic map ( REG_BANK_ROM0   ) port map (clk, RegBus_Din, mapper_RegBus_Adr, RegBus_wren, RegBus_rst, reg_wired_or( 2), BANK_ROM0    , BANK_ROM0);
   iREG_BANK_ROM1   : entity work.eReg generic map ( REG_BANK_ROM1   ) port map (clk, RegBus_Din, mapper_RegBus_Adr, RegBus_wren, RegBus_rst, reg_wired_or( 3), BANK_ROM1    , BANK_ROM1);
                                                                                                                                                     
   iREG_HW_FLAGS    : entity work.eReg generic map ( REG_HW_FLAGS    ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren, RegBus_rst, reg_wired_or( 4), HW_FLAGS_read, open, HW_FLAGS_written); 

   -- Bandai 2003 self-flash control, port CEh. Only bit 0 exists: zero keeps
   -- the 10000h-1FFFFh window on SRAM, while one exposes the ROM/flash path.
   -- The mapper selector is exact so Bandai 2001 and unknown footer values do
   -- not gain this register. RegBus_rst is also asserted while restoring the
   -- register image, allowing this bit to participate in the existing
   -- register savestate walk without adding a separate state interface.
   process (clk)
   begin
      if rising_edge(clk) then
         if (RegBus_rst = '1' or mapper_2003_selected = '0') then
            flash_enable <= '0';
         elsif (RegBus_wren = '1' and RegBus_Adr = x"CE") then
            flash_enable <= RegBus_Din(0);
         end if;
      end if;
   end process;

   reg_wired_or(7) <= x"01" when mapper_2003_selected = '1' and
                                  RegBus_Adr = x"CE" and
                                  flash_enable = '1'
                      else x"00";

   process (reg_wired_or)
      variable wired_or : std_logic_vector(7 downto 0);
   begin
      wired_or := reg_wired_or(0);
      for i in 1 to (reg_wired_or'length - 1) loop
         wired_or := wired_or or reg_wired_or(i);
      end loop;
      RegBus_Dout <= wired_or;
   end process;
   
   -- savestates
   process (ss_wired_or)
      variable wired_or : std_logic_vector(63 downto 0);
   begin
      wired_or := ss_wired_or(0);
      for i in 1 to (ss_wired_or'length - 1) loop
         wired_or := wired_or or ss_wired_or(i);
      end loop;
      SSBUS_Dout <= wired_or;
   end process;
   
   
   -- carttype
   rommask      <= maskAddr;      
   sramMask     <= x"007FFF" when ramtype = x"01" else
                   x"007FFF" when ramtype = x"02" else     
                   x"01FFFF" when ramtype = x"03" else     
                   x"03FFFF" when ramtype = x"04" else     
                   x"07FFFF" when ramtype = x"05" else     
                   x"000000";
   
   -- 
   HW_FLAGS_read <= "100001" & isColor & HW_FLAGS_set;
    
   process (clk)
   begin
      if rising_edge(clk) then
         if (SSBUS_rst = '1') then
            HW_FLAGS_set <= '0';
         elsif (HW_FLAGS_written = '1' and RegBus_Din(0) = '1') then
            HW_FLAGS_set <= '1';
         end if;
      end if;
   end process;
               
   RAM_addressCPU   <= SSMEM_Addr(15 downto 1) when sleep_savestate = '1' else 
                       std_logic_vector(cpu_addr(15 downto 1));
                
   RAM_dataWriteCPU <= SSMEM_WriteData when sleep_savestate = '1' else 
                       cpu_datawrite when cpu_addr(0) = '0' else cpu_datawrite(7 downto 0) & cpu_datawrite(15 downto 8);
              
   SSMEM_ReadData_RAM  <= RAM_dataReadCPU;
   SSMEM_ReadData_SRAM <= EXTRAM_dataread;
              
   iramCPUA: entity work.dpram
   generic map
   (
       addr_width => 15,
       data_width => 8
   )
   port map
   (
      clock_a     => clk,
      address_a   => RAM_addressCPU,
      data_a      => RAM_dataWriteCPU(7 downto 0),
      wren_a      => RAM_dataWriteEnable(0),
      q_a         => RAM_dataReadCPU(7 downto 0),

      clock_b     => clk,
      address_b   => GPU_addr(15 downto 1),
      data_b      => x"00",
      wren_b      => '0',
      q_b         => GPU_dataread(7 downto 0)
   );
   iramCPUB: entity work.dpram
   generic map
   (
       addr_width => 15,
       data_width => 8
   )
   port map
   (
      clock_a     => clk,
      address_a   => RAM_addressCPU,
      data_a      => RAM_dataWriteCPU(15 downto 8),
      wren_a      => RAM_dataWriteEnable(1),
      q_a         => RAM_dataReadCPU(15 downto 8),

      clock_b     => clk,
      address_b   => GPU_addr(15 downto 1),
      data_b      => x"00",
      wren_b      => '0',
      q_b         => GPU_dataread(15 downto 8)
   );
   
   Palette_WriteEnable <= RAM_dataWriteEnable when (RAM_addressCPU(14 downto 8) = "1111111") else "00";

   iramPALA: entity work.dpram
   generic map
   (
       addr_width => 8,
       data_width => 8
   )
   port map
   (
      clock_a     => clk,
      address_a   => RAM_addressCPU(7 downto 0),
      data_a      => RAM_dataWriteCPU(7 downto 0),
      wren_a      => Palette_WriteEnable(0),
      q_a         => open,

      clock_b     => clk,
      address_b   => Color_addr,
      data_b      => x"00",
      wren_b      => '0',
      q_b         => Color_dataread(7 downto 0)
   );
   iramPALB: entity work.dpram
   generic map
   (
       addr_width => 8,
       data_width => 8
   )
   port map
   (
      clock_a     => clk,
      address_a   => RAM_addressCPU(7 downto 0),
      data_a      => RAM_dataWriteCPU(15 downto 8),
      wren_a      => Palette_WriteEnable(1),
      q_a         => open,

      clock_b     => clk,
      address_b   => Color_addr,
      data_b      => x"00",
      wren_b      => '0',
      q_b         => Color_dataread(15 downto 8)
   );
       
   ireg_shadow: entity work.dpram
   generic map
   (
       addr_width => 8,
       data_width => 8
   )
   port map
   (
      clock_a      => clk,
      address_a   => RegBus_Adr,
      data_a      => RegBus_Din,
      wren_a      => RegBus_wren,
      q_a         => open,
   
      clock_b     => clk,
      address_b   => SSMEM_Addr(7 downto 0),
      data_b      => x"00",
      wren_b      => '0',
      q_b         => SSMEM_ReadData_REG(7 downto 0)
   );
   SSMEM_ReadData_REG(15 downto 8) <= (others => '0');
   
   BIOS_address <= std_logic_vector(cpu_addr(11 downto 1));
   iswanbios : entity work.swanbios
   port map
   (
      clk         => clk,
      address     => BIOS_address,
      data        => BIOS_data,
      bios_wraddr => bios_wraddr(11 downto 1),
      bios_wrdata => bios_wrdata,
      bios_wr     => bios_wr
   );
   
   BIOS_addressColor <= std_logic_vector(cpu_addr(12 downto 1));
   iswanbioscolor : entity work.swanbioscolor
   port map
   (
      clk         => clk,
      address     => BIOS_addressColor,
      data        => BIOS_dataColor,
      bios_wraddr => bios_wraddr(12 downto 1),
      bios_wrdata => bios_wrdata,
      bios_wr     => bios_wrcolor
   );
      
   cpu_dataread <= cpu_dataread_16 when cpu_unaligned = '0' else x"00" & cpu_dataread_16(15 downto 8);
  
   process (all)
      variable BiosAccess : std_logic;
   begin
      cpu_dataread_16 <= x"0000";
      
      MemAccessTypeNew <= EXTRAM;
      case (MemAccessType) is
         when BIOS      => cpu_dataread_16 <= BIOS_data;
         when BIOSCOLOR => cpu_dataread_16 <= BIOS_dataColor;
         when EXTRAM    => cpu_dataread_16 <= EXTRAM_dataread;
         when RAMACC    => cpu_dataread_16 <= RAM_dataReadCPU;
         when UNMAPPED  => cpu_dataread_16 <= x"9090";
         when ZERO      => cpu_dataread_16 <= x"0000";
      end case;
      
      BiosAccess := '0';
      if (isColor) then
         if (HW_FLAGS_set = '0' and cpu_addr >= 16#100000# - 8192) then
            BiosAccess       := '1'; 
            MemAccessTypeNew <= BIOSCOLOR;
         end if;
      else
         if (HW_FLAGS_set = '0' and cpu_addr >= 16#100000# - 4096) then
            BiosAccess       := '1'; 
            MemAccessTypeNew <= BIOS;
         end if;
      end if;
      
      EXTRAM_addr      <= '0' & ((BANK_ROM2(3 downto 0) & std_logic_vector(cpu_addr)) and rommask); -- default
      EXTRAM_read      <= '0';
      EXTRAM_write     <= '0';
      EXTRAM_datawrite <= cpu_datawrite;
      EXTRAM_be        <= "00";

      -- Keep these encodings in sync with sim/verilator/trace_logger.hpp.
      -- 0 unknown, 1 IRAM, 2 SRAM, 3 ROM0, 4 ROM1, 5 linear ROM,
      -- 6 boot ROM, 7 unmapped mono IRAM, 8 absent SRAM, 9 flash window.
      debug_mem_space        <= x"0";
      debug_mem_offset       <= (others => '0');
      debug_mem_offset_valid <= '0';

      if (BiosAccess = '1') then
         debug_mem_space        <= x"6";
         debug_mem_offset_valid <= '1';
         if (isColor) then
            debug_mem_offset <= (23 downto 13 => '0') & std_logic_vector(cpu_addr(12 downto 0));
         else
            debug_mem_offset <= (23 downto 12 => '0') & std_logic_vector(cpu_addr(11 downto 0));
         end if;
      end if;
      
      RAM_dataWriteEnable <= "00";
      
      if (BiosAccess = '0') then
         case (cpu_addr(19 downto 16)) is
            when x"0" => 
               debug_mem_space        <= x"1";
               debug_mem_offset       <= x"00" & std_logic_vector(cpu_addr(15 downto 0));
               debug_mem_offset_valid <= '1';
               if (cpu_addr(0) = '0') then
                  RAM_dataWriteEnable <= cpu_be and (cpu_write & cpu_write);
               else
                  RAM_dataWriteEnable <= (cpu_be(0) & cpu_be(1)) and (cpu_write & cpu_write);
               end if;
               MemAccessTypeNew    <= RAMACC;
               if (isColor = '0' and cpu_addr(15 downto 14) /= "00") then
                  MemAccessTypeNew <= UNMAPPED;
                  RAM_dataWriteEnable <= "00";
                  debug_mem_space        <= x"7";
                  debug_mem_offset       <= (others => '0');
                  debug_mem_offset_valid <= '0';
               end if;
               
            when x"1" => 
               if (mapper_2003_selected = '1' and flash_enable = '1') then
                  -- CEh selects the ROM/flash device while retaining the SRAM
                  -- bank register and 64 KiB CPU window. The existing SDRAM
                  -- channel is the volatile backing for this first slice;
                  -- MBM29DL400 command decoding and APF persistence belong to
                  -- the flash controller layered above this routing contract.
                  EXTRAM_addr      <= '0' & ((BANK_SRAM & std_logic_vector(cpu_addr(15 downto 0))) and rommask);
                  debug_mem_space        <= x"9";
                  debug_mem_offset       <= (BANK_SRAM & std_logic_vector(cpu_addr(15 downto 0))) and rommask;
                  debug_mem_offset_valid <= '1';
                  EXTRAM_read      <= CPU_read;
                  EXTRAM_write     <= CPU_write;
                  EXTRAM_be        <= cpu_be;
                  if (cpu_addr(0) = '1') then
                     -- SDRAM is word-wide, but the Bandai 2003 flash window is
                     -- byte-addressed. Move an odd byte request/data item onto
                     -- the upper lane of the containing SDRAM word.
                     EXTRAM_be        <= cpu_be(0) & '0';
                     EXTRAM_datawrite <= cpu_datawrite(7 downto 0) & x"00";
                  end if;
               elsif (sramMask = x"000000") then
                  MemAccessTypeNew <= ZERO;
                  debug_mem_space <= x"8";
               else
                  EXTRAM_addr      <= '1' & ((BANK_SRAM & std_logic_vector(cpu_addr(15 downto 0))) and sramMask);
                  debug_mem_space        <= x"2";
                  debug_mem_offset       <= (BANK_SRAM & std_logic_vector(cpu_addr(15 downto 0))) and sramMask;
                  debug_mem_offset_valid <= '1';
                  EXTRAM_read      <= CPU_read;
                  EXTRAM_write     <= CPU_write;
                  EXTRAM_be        <= cpu_be;
                  if (cpu_addr(0) = '0') then
                     EXTRAM_be <= cpu_be;
                  else
                     EXTRAM_be        <= cpu_be(0) & '0';
                     EXTRAM_datawrite <= cpu_datawrite(7 downto 0) & x"00";
                  end if;
               end if;
               
            when x"2" =>
               EXTRAM_addr      <= '0' & ((BANK_ROM0 & std_logic_vector(cpu_addr(15 downto 0))) and rommask);
               debug_mem_space        <= x"3";
               debug_mem_offset       <= (BANK_ROM0 & std_logic_vector(cpu_addr(15 downto 0))) and rommask;
               debug_mem_offset_valid <= '1';
               EXTRAM_read      <= CPU_read;
               EXTRAM_write     <= '0';
               
            when x"3" =>
               EXTRAM_addr      <= '0' & ((BANK_ROM1 & std_logic_vector(cpu_addr(15 downto 0))) and rommask);
               debug_mem_space        <= x"4";
               debug_mem_offset       <= (BANK_ROM1 & std_logic_vector(cpu_addr(15 downto 0))) and rommask;
               debug_mem_offset_valid <= '1';
               EXTRAM_read      <= CPU_read;
               EXTRAM_write     <= '0';
               
            when others =>
               EXTRAM_addr      <= '0' & ((BANK_ROM2(3 downto 0) & std_logic_vector(cpu_addr)) and rommask);
               debug_mem_space        <= x"5";
               debug_mem_offset       <= (BANK_ROM2(3 downto 0) & std_logic_vector(cpu_addr)) and rommask;
               debug_mem_offset_valid <= '1';
               EXTRAM_read      <= CPU_read;
               EXTRAM_write     <= '0';
         end case;
      end if;
      
      if (SSMEM_WrEn(1) = '1') then
         RAM_dataWriteEnable <= "11";
      end if;
      
      if (sleep_savestate = '1') then
         EXTRAM_addr      <= "100000" & SSMEM_Addr(18 downto 0);
      end if;
      
      if (SSMEM_WrEn(2) = '1') then
         EXTRAM_datawrite <= SSMEM_WriteData;
         EXTRAM_read      <= '0';
         EXTRAM_write     <= '1';
         EXTRAM_be        <= "11";
      end if;
      
      if (SSMEM_RdEn(2) = '1') then
         EXTRAM_read      <= '1';
         EXTRAM_write     <= '0';
      end if;
      
   end process;
  
   process (clk)
   begin
      if rising_edge(clk) then
         if (reset = '1') then
            cpu_unaligned <= '0';
         else
            MemAccessType <= MemAccessTypeNew;
            cpu_unaligned <= cpu_addr(0);
         end if;
      end if;
   end process;
   
   -- eeprom
   
   ieeprom_int : entity work.eeprom
   generic map
   (
      isExternal           => '0',
      defaultvalue         => x"0000",
      REG_Data_H           => REG_EeIntData_H,
      REG_Data_L           => REG_EeIntData_L,
      REG_Addr_H           => REG_EeIntAddr_H,
      REG_Addr_L           => REG_EeIntAddr_L,
      REG_Cmd              => REG_EeIntCmd,
      REG_SAVESTATE_EEPROM => REG_SAVESTATE_EEPROMINT      
   )
   port map
   (
      clk            => clk, 
      clk_ram        => clk_ram,       
      ce             => ce,     
      reset          => reset,  
      isColor        => isColor,
      preserve_on_reset => preserve_internal_eeprom,
      
      ramtype        => x"00",
      
      written        => open,
      eeprom_bank    => internal_eeprom_bank,
      eeprom_addr    => internal_eeprom_addr,
      eeprom_din     => internal_eeprom_din,
      eeprom_dout    => internal_eeprom_dout,
      eeprom_req     => internal_eeprom_req,
      eeprom_rnw     => internal_eeprom_rnw,
                     
      RegBus_Din     => RegBus_Din, 
      RegBus_Adr     => RegBus_Adr, 
      RegBus_wren    => RegBus_wren,
      RegBus_rst     => RegBus_rst, 
      RegBus_Dout    => reg_wired_or(5),
                     
      -- savestates  
      SSBus_Din      => SSBus_Din, 
      SSBus_Adr      => SSBus_Adr, 
      SSBus_wren     => SSBus_wren,
      SSBus_rst      => SSBus_rst, 
      SSBus_Dout     => ss_wired_or(0),

      state_freeze   => '0',
      frozen_ack     => open,
      state_load     => '0',
      state_in       => (others => '0'),
      state_out      => open
   );
   
   ieeprom_ext : entity work.eeprom
   generic map
   (
      isExternal           => '1',
      defaultvalue         => x"FFFF",
      REG_Data_H           => REG_EeExtData_H,
      REG_Data_L           => REG_EeExtData_L,
      REG_Addr_H           => REG_EeExtAddr_H,
      REG_Addr_L           => REG_EeExtAddr_L,
      REG_Cmd              => REG_EeExtCmd,
      REG_SAVESTATE_EEPROM => REG_SAVESTATE_EEPROMEXT
   )
   port map
   (
      clk            => clk, 
      clk_ram        => clk_ram,       
      ce             => ce,     
      reset          => reset,  
      isColor        => isColor,
      preserve_on_reset => '0',
      
      ramtype        => ramtype,
      
      written        => eepromWrite,
      eeprom_bank    => '0',
      eeprom_addr    => eeprom_addr,
      eeprom_din     => eeprom_din, 
      eeprom_dout    => eeprom_dout,
      eeprom_req     => eeprom_req, 
      eeprom_rnw     => eeprom_rnw, 
                     
      RegBus_Din     => RegBus_Din, 
      RegBus_Adr     => RegBus_Adr, 
      RegBus_wren    => RegBus_wren,
      RegBus_rst     => RegBus_rst, 
      RegBus_Dout    => reg_wired_or(6),
                     
      -- savestates  
      SSBus_Din      => SSBus_Din, 
      SSBus_Adr      => SSBus_Adr, 
      SSBus_wren     => SSBus_wren,
      SSBus_rst      => SSBus_rst, 
      SSBus_Dout     => ss_wired_or(1),

      state_freeze   => '0',
      frozen_ack     => open,
      state_load     => '0',
      state_in       => (others => '0'),
      state_out      => open
   );
   

end architecture;
