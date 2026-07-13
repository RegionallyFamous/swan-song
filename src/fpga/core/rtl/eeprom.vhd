library IEEE;
use IEEE.std_logic_1164.all;  
use IEEE.numeric_std.all; 

use work.pRegisterBus.all;  
use work.pBus_savestates.all;

entity eeprom is
   generic
   (
      isExternal           : std_logic;
      defaultvalue         : std_logic_vector(15 downto 0);
      REG_Data_H           : regmap_type;
      REG_Data_L           : regmap_type;
      REG_Addr_H           : regmap_type;
      REG_Addr_L           : regmap_type;
      REG_Cmd              : regmap_type;
      REG_SAVESTATE_EEPROM : savestate_type
   );
   port 
   (
      clk            : in  std_logic;
      clk_ram        : in  std_logic;
      ce             : in  std_logic;
      reset          : in  std_logic;
      isColor        : in  std_logic;
      preserve_on_reset : in std_logic;
      
      ramtype        : in  std_logic_vector(7 downto 0);
      
      written        : out std_logic;
      eeprom_bank    : in  std_logic;
      eeprom_addr    : in  std_logic_vector(9 downto 0);
      eeprom_din     : in  std_logic_vector(15 downto 0);
      eeprom_dout    : out std_logic_vector(15 downto 0);
      eeprom_req     : in  std_logic;
      eeprom_rnw     : in  std_logic;
      
      RegBus_Din     : in  std_logic_vector(BUS_buswidth-1 downto 0);
      RegBus_Adr     : in  std_logic_vector(BUS_busadr-1 downto 0);
      RegBus_wren    : in  std_logic;
      RegBus_rst     : in  std_logic;
      RegBus_Dout    : out std_logic_vector(BUS_buswidth-1 downto 0);
      
      -- savestates     
      SSBus_Din      : in  std_logic_vector(SSBUS_buswidth-1 downto 0);
      SSBus_Adr      : in  std_logic_vector(SSBUS_busadr-1 downto 0);
      SSBus_wren     : in  std_logic;
      SSBus_rst      : in  std_logic;
      SSBus_Dout     : out std_logic_vector(SSBUS_buswidth-1 downto 0);

      -- Exact controller-state interface used by the Memories v2 staging
      -- path.  All trailing defaults preserve legacy instantiations until
      -- the higher-level state owner is connected.
      state_freeze   : in  std_logic := '0';
      frozen_ack     : out std_logic := '0';
      state_load     : in  std_logic := '0';
      state_in       : in  std_logic_vector(127 downto 0) := (others => '0');
      state_out      : out std_logic_vector(127 downto 0) := (others => '0')
   );
end entity;

architecture arch of eeprom is
  
   -- register
   -- The WonderSwan controller has distinct write-data and read-result
   -- latches.  In particular, completing a write must not make the written
   -- value visible through the data ports until a read command completes.
   signal WriteData   : std_logic_vector(15 downto 0);
   signal ReadData    : std_logic_vector(15 downto 0);
   signal Addr        : std_logic_vector(15 downto 0);
   signal Cmd         : std_logic_vector( 7 downto 0);
   
   signal Status      : std_logic_vector( 7 downto 0);
   
   signal Data_L_written : std_logic;
   signal Data_H_written : std_logic;
   signal Cmd_written    : std_logic;
   signal RegBus_wren_active : std_logic;
   signal RegBus_rst_active  : std_logic;
   signal SSBus_wren_active  : std_logic;
   signal SSBus_rst_active   : std_logic;
   signal state_load_active  : std_logic;
   
   type t_reg_wired_or is array(0 to 4) of std_logic_vector(7 downto 0);
   signal reg_wired_or : t_reg_wired_or;
   
   -- wiring
   signal opcode : std_logic_vector(1 downto 0);
   signal extCmd : std_logic_vector(1 downto 0);
   
   -- internal logic
   type tState is
   (
      OFF,
      IDLE,
      EVALCMD,
      CLEAR,
      OVERWRITE,
      WRITEWAIT,
      READWAIT,
      READONE
   );
   signal state : tState;
   
   signal writeEnable  : std_logic := '0';
   signal writeProtect : std_logic := '0';
   signal readDone     : std_logic := '1';
   signal readDelay    : integer range 0 to 9 := 0;
   
   signal size         : integer range 0 to 1024 := 0;
   
   signal clearCounter : integer range 0 to 1024 := 0;
   signal addrCounter  : integer range 0 to 1024 := 0;
                       
   signal RAMAddrFull  : std_logic_vector( 9 downto 0);
   signal RAMAddr      : std_logic_vector( 9 downto 0);
   signal RAMAddrPhysical : std_logic_vector(10 downto 0);
   signal EEPROMAddrPhysical : std_logic_vector(10 downto 0);
   signal writevalue   : std_logic_vector(15 downto 0);
   signal readvalue    : std_logic_vector(15 downto 0);
   signal RAMWrEn      : std_logic := '0';
   signal written_reg  : std_logic := '0';
   
   signal wren_b       : std_logic;
         
   -- savestates     
   signal SS_EEPROM      : std_logic_vector(REG_SAVESTATE_EEPROM.upper downto REG_SAVESTATE_EEPROM.lower);
   signal SS_EEPROM_BACK : std_logic_vector(REG_SAVESTATE_EEPROM.upper downto REG_SAVESTATE_EEPROM.lower);
   signal ssLoaded       : std_logic := '0';
   signal frozen_ack_reg : std_logic := '0';
   signal load_settle    : std_logic := '0';

   -- Fixed controller image.  The backing EEPROM contents live in their
   -- separate v2 payload regions; this vector contains only controller and
   -- synchronous-RAM pipeline state.
   --   15:0   WriteData       31:16  ReadData
   --   47:32  Addr            55:48  Cmd
   --   58:56  FSM             59     writeEnable
   --   60     writeProtect    61     readDone
   --   65:62  readDelay       76:66  size
   --   87:77  clearCounter    98:88  addrCounter
   --   114:99 writevalue      115    legacy ssLoaded history
   --   116    pending RAMWrEn 117    written pulse history
   --   127:118 reserved zero
   function encode_state(value : tState) return std_logic_vector is
   begin
      case value is
         when OFF       => return "000";
         when IDLE      => return "001";
         when EVALCMD   => return "010";
         when CLEAR     => return "011";
         when OVERWRITE => return "100";
         when WRITEWAIT => return "101";
         when READWAIT  => return "110";
         when READONE   => return "111";
      end case;
   end function;

   function decode_state(value : std_logic_vector(2 downto 0)) return tState is
   begin
      case value is
         when "000"  => return OFF;
         when "001"  => return IDLE;
         when "010"  => return EVALCMD;
         when "011"  => return CLEAR;
         when "100"  => return OVERWRITE;
         when "101"  => return WRITEWAIT;
         when "110"  => return READWAIT;
         when others => return READONE;
      end case;
   end function;

   function decode_bounded(
      value : std_logic_vector;
      limit_value : natural
   ) return natural is
      variable decoded : natural;
   begin
      decoded := to_integer(unsigned(value));
      if decoded > limit_value then
         return limit_value;
      end if;
      return decoded;
   end function;

begin
   -- A restore is accepted only from an already-quiescent prior cycle.  This
   -- prevents the first freeze edge (which may still commit RAMWrEn) from also
   -- replacing the controller pipeline beneath that write.
   state_load_active <= state_load and state_freeze and frozen_ack_reg;
   RegBus_wren_active <= RegBus_wren when state_freeze = '0' else '0';
   -- Device reset interrupts freeze/load and drops frozen_ack in the clocked
   -- process.  A register-bus-only reset is deferred so an acknowledged
   -- snapshot cannot mutate; state_load likewise has priority over it.
   RegBus_rst_active <= reset or
      (RegBus_rst and not state_freeze and not state_load_active);
   SSBus_wren_active <= SSBus_wren when state_freeze = '0' else '0';
   SSBus_rst_active <= SSBus_rst when state_freeze = '0' else '0';

   iREG_Data_H : entity work.eReg generic map ( REG_Data_H ) port map
      (clk, RegBus_Din, RegBus_Adr, RegBus_wren_active, RegBus_rst_active,
       reg_wired_or(0), ReadData(7 downto 0), WriteData(7 downto 0),
       Data_L_written, state_load_active, state_in(7 downto 0));
   iREG_Data_L : entity work.eReg generic map ( REG_Data_L ) port map
      (clk, RegBus_Din, RegBus_Adr, RegBus_wren_active, RegBus_rst_active,
       reg_wired_or(1), ReadData(15 downto 8), WriteData(15 downto 8),
       Data_H_written, state_load_active, state_in(15 downto 8));
   iREG_Addr_H : entity work.eReg generic map ( REG_Addr_H ) port map
      (clk, RegBus_Din, RegBus_Adr, RegBus_wren_active, RegBus_rst_active,
       reg_wired_or(2), Addr(7 downto 0), Addr(7 downto 0), open,
       state_load_active, state_in(39 downto 32));
   iREG_Addr_L : entity work.eReg generic map ( REG_Addr_L ) port map
      (clk, RegBus_Din, RegBus_Adr, RegBus_wren_active, RegBus_rst_active,
       reg_wired_or(3), Addr(15 downto 8), Addr(15 downto 8), open,
       state_load_active, state_in(47 downto 40));
   iREG_Cmd : entity work.eReg generic map ( REG_Cmd ) port map
      (clk, RegBus_Din, RegBus_Adr, RegBus_wren_active, RegBus_rst_active,
       reg_wired_or(4), Status, Cmd, Cmd_written,
       state_load_active, state_in(55 downto 48));

   written <= written_reg;
   frozen_ack <= frozen_ack_reg;

   process (all)
      variable image : std_logic_vector(127 downto 0);
   begin
      image := (others => '0');
      image(15 downto 0)   := WriteData;
      image(31 downto 16)  := ReadData;
      image(47 downto 32)  := Addr;
      image(55 downto 48)  := Cmd;
      image(58 downto 56)  := encode_state(state);
      image(59)            := writeEnable;
      image(60)            := writeProtect;
      image(61)            := readDone;
      image(65 downto 62)  := std_logic_vector(to_unsigned(readDelay, 4));
      image(76 downto 66)  := std_logic_vector(to_unsigned(size, 11));
      image(87 downto 77)  := std_logic_vector(to_unsigned(clearCounter, 11));
      image(98 downto 88)  := std_logic_vector(to_unsigned(addrCounter, 11));
      image(114 downto 99) := writevalue;
      image(115)           := ssLoaded;
      image(116)           := RAMWrEn;
      image(117)           := written_reg;
      state_out <= image;
   end process;
   
   process (reg_wired_or)
      variable wired_or : std_logic_vector(7 downto 0);
   begin
      wired_or := reg_wired_or(0);
      for i in 1 to (reg_wired_or'length - 1) loop
         wired_or := wired_or or reg_wired_or(i);
      end loop;
      RegBus_Dout <= wired_or;
   end process;
   
   opcode <= Addr(7 downto 6) when size = 64 else Addr(11 downto 10);
   extCmd <= Addr(5 downto 4) when size = 64 else Addr( 9 downto  8);
   
   -- Bits 0 and 1 are DONE and READY.  Protection is latched only by the
   -- internal controller and is reported in bit 7; the other bits read zero.
   Status <= writeProtect & "00000" & '1' & readDone when state = IDLE else
             writeProtect & "000000" & readDone;
   
   RAMAddrFull <= std_logic_vector(to_unsigned(addrCounter, 10));
   
   RAMAddr <= "0000" & RAMAddrFull(5 downto 0) when size = 64  else
                 '0' & RAMAddrFull(8 downto 0) when size = 512 else
               RAMAddrFull;

   -- Keep both console models resident at once: Color occupies bank 0 and
   -- monochrome occupies the first 64 words of bank 1. External cartridge
   -- EEPROM has no bank and retains its original 1024-word allocation. Static
   -- generates keep Quartus from inferring an unused second cartridge bank.
   RAMAddrPhysical <= '0' & RAMAddr when isColor = '1' else
                      '1' & RAMAddr;
   EEPROMAddrPhysical <= eeprom_bank & eeprom_addr;

   external_backing : if isExternal = '1' generate
      iramEEPROMExternal: entity work.dpram
      generic map
      (
          addr_width => 10,
          data_width => 16
      )
      port map
      (
         clock_a     => clk,
         address_a   => RAMAddr,
         data_a      => writevalue,
         wren_a      => RAMWrEn,
         q_a         => readvalue,

         clock_b     => clk_ram,
         address_b   => eeprom_addr,
         data_b      => eeprom_din,
         wren_b      => wren_b,
         q_b         => eeprom_dout
      );
   end generate;

   internal_backing : if isExternal = '0' generate
      iramEEPROMInternal: entity work.dpram
      generic map
      (
          addr_width => 11,
          data_width => 16
      )
      port map
      (
         clock_a     => clk,
         address_a   => RAMAddrPhysical,
         data_a      => writevalue,
         wren_a      => RAMWrEn,
         q_a         => readvalue,

         clock_b     => clk_ram,
         address_b   => EEPROMAddrPhysical,
         data_b      => eeprom_din,
         wren_b      => wren_b,
         q_b         => eeprom_dout
      );
   end generate;
   
   wren_b <= '1' when (eeprom_req = '1' and eeprom_rnw = '0') else '0';
   
   iSS_EEPROM : entity work.eReg_SS generic map ( REG_SAVESTATE_EEPROM ) port map (clk, SSBUS_Din, SSBUS_Adr, SSBus_wren_active, SSBus_rst_active, SSBUS_Dout, SS_EEPROM_BACK, SS_EEPROM);
               
   SS_EEPROM_BACK(15 downto  0) <= ReadData;
   SS_EEPROM_BACK(          16) <= writeEnable;       
               
   process (clk)
   begin
      if rising_edge(clk) then

         -- RAM port A observes the old RAMWrEn on this same edge.  Clearing
         -- the pipeline flag here therefore cannot cancel an already-pending
         -- write, which is the key freeze-boundary invariant.
         RAMWrEn <= '0';
         written_reg <= RAMWrEn;

         if (reset = '1') then

            frozen_ack_reg <= '0';
            load_settle    <= '0';
            RAMWrEn        <= '0';
            written_reg    <= '0';

            if (isExternal = '0' and preserve_on_reset = '0') then
               state        <= clear;
            else
               state        <= IDLE;
            end if;

            readDone     <= '1';
            writeProtect <= '0';
            readDelay    <= 0;
            clearCounter <= 0;
            addrCounter  <= 0;
            writevalue   <= defaultvalue;
            ssLoaded     <= '0';

            -- Only an explicitly pending legacy load may consult the hidden
            -- SS_EEPROM register.  Ordinary resets use the declared
            -- controller defaults, so identical v2 restores cannot diverge
            -- because of stale legacy state outside state_out.
            if (ssLoaded = '1') then
               ReadData <= SS_EEPROM(15 downto 0);
               writeEnable <= SS_EEPROM(16);
            else
               ReadData <= REG_SAVESTATE_EEPROM.defval(15 downto 0);
               if (isExternal = '0') then
                  -- The open bootstrap starts after the retail firmware's
                  -- internal-EEPROM write-enable sequence.
                  writeEnable <= '1';
               else
                  writeEnable <= REG_SAVESTATE_EEPROM.defval(16);
               end if;
            end if;

            if (isExternal = '1') then
               case (ramtype) is
                  when x"10"  => size <= 64;
                  when x"20"  => size <= 1024;
                  when x"50"  => size <= 512;
                  when others => size <= 0; state <= OFF;
               end case;
            else
               if (isColor = '1') then
                  size <= 1024;
               else
                  size <= 64;
               end if;
            end if;

         elsif (state_load_active = '1') then

            -- eReg consumes the register fields on this edge as well.  Its
            -- state-load path explicitly suppresses `written`, so restoring
            -- Cmd cannot be mistaken for a fresh EEPROM command.
            ReadData     <= state_in(31 downto 16);
            state        <= decode_state(state_in(58 downto 56));
            writeEnable  <= state_in(59);
            writeProtect <= state_in(60);
            readDone     <= state_in(61);
            readDelay    <= decode_bounded(state_in(65 downto 62), 9);
            size         <= decode_bounded(state_in(76 downto 66), 1024);
            clearCounter <= decode_bounded(state_in(87 downto 77), 1024);
            -- clearCounter may retain its inclusive terminal 1024 value;
            -- addrCounter addresses a 1024-word RAM and is only valid to 1023.
            -- The outer ABI validator rejects larger images.  Keep this clamp
            -- as a synthesis-safe last line of defence for direct RTL users.
            addrCounter  <= decode_bounded(state_in(98 downto 88), 1023);
            writevalue   <= state_in(114 downto 99);
            ssLoaded     <= state_in(115);
            RAMWrEn      <= state_in(116);
            written_reg  <= state_in(117);
            frozen_ack_reg <= '0';
            load_settle    <= '1';

         elsif (load_settle = '1') then

            -- A restored address needs one RAM clock before READONE may use
            -- q_a.  This settle edge also commits a deliberately restored
            -- pending RAMWrEn exactly once, then normalizes the pipeline.
            load_settle <= '0';
            if (RAMWrEn = '0') then
               -- No new commit means the restored outgoing pulse history is
               -- still the exact current value at the acknowledged boundary.
               written_reg <= written_reg;
            end if;
            if (ssLoaded = '1') then
               -- Canonical v2 images never retain a pending legacy-register
               -- restore.  Consume all of its architectural latch effects
               -- before ack, making the hidden legacy register irrelevant.
               ReadData <= SS_EEPROM(15 downto 0);
               writeEnable <= SS_EEPROM(16);
               ssLoaded <= '0';
               frozen_ack_reg <= '0';
            elsif (state_freeze = '1') then
               frozen_ack_reg <= '1';
            else
               frozen_ack_reg <= '0';
            end if;

         elsif (state_freeze = '1') then

            if (ssLoaded = '1') then
               -- The old savestate path stages ReadData/writeEnable for
               -- consumption by reset.  A v2 capture consumes those same
               -- values here so bit 115 can become canonical zero.
               ReadData <= SS_EEPROM(15 downto 0);
               writeEnable <= SS_EEPROM(16);
               ssLoaded <= '0';
               frozen_ack_reg <= '0';
            else
               frozen_ack_reg <= '1';
            end if;
            if (frozen_ack_reg = '1' and ssLoaded = '0') then
               -- Once acknowledged, both the controller image and outgoing
               -- write history remain stable for an arbitrarily long freeze.
               RAMWrEn     <= RAMWrEn;
               written_reg <= written_reg;
            end if;

         else

            frozen_ack_reg <= '0';
            load_settle    <= '0';

            if (SSBus_wren_active = '1' and
                SSBUS_Adr = std_logic_vector(to_unsigned(REG_SAVESTATE_EEPROM.Adr, SSBUS_Adr'length))) then
               ssLoaded <= '1';
            end if;

            case (state) is
            
               when OFF =>
                  null;
            
               when IDLE =>
               
                  if (ce = '1' and Cmd_written = '1') then
                     state <= EVALCMD;
                     if (RegBus_Din = x"10") then
                        readDone <= '0';
                     end if;
                  end if;
                  
                  case (size) is
                     when 64     => addrCounter <= to_integer(unsigned(Addr(5 downto 0)));
                     when 512    => addrCounter <= to_integer(unsigned(Addr(8 downto 0)));
                     when 1024   => addrCounter <= to_integer(unsigned(Addr(9 downto 0)));
                     when others => null;
                  end case;
                  
               when EVALCMD =>
                  state <= IDLE;

                  case (Cmd) is
                     when x"10" => -- READ
                        if (opcode = "10") then
                           state     <= READWAIT;
                           readDelay <= 0;
                        end if;
                        
                     when x"20" => -- WRITE
                        if (opcode = "01") then
                           writevalue <= WriteData;
                           if (writeEnable = '1' and
                               not (isExternal = '0' and writeProtect = '1' and addrCounter >= 16#30#)) then
                              RAMWrEn <= '1';
                              state <= WRITEWAIT;
                           end if;
                        elsif (opcode = "00" and extCmd = "01") then -- write all
                           state       <= OVERWRITE;
                           writevalue  <= WriteData;
                           addrCounter <= 0;
                           if (writeEnable = '1') then RAMWrEn <= '1'; end if;
                        end if;
                     
                     when x"40" =>
                        case (opcode) is
                           when "00" => 
                              case (extCmd) is
                                 when "00" =>
                                    writeEnable <= '0';
                                 
                                 when "01" => -- WRAL uses the WRITE control
                                    null;
                                 
                                 when "10" => -- erase all
                                    state       <= OVERWRITE;
                                    writevalue  <= x"FFFF";
                                    addrCounter <= 0;
                                    if (writeEnable = '1') then RAMWrEn <= '1'; end if; 
                                 
                                 when "11" =>
                                    writeEnable <= '1';
                                 
                                 when others => null;
                              end case;
                           
                           when "11" => -- erase
                              writevalue  <= x"FFFF";
                              if (writeEnable = '1' and
                                  not (isExternal = '0' and writeProtect = '1' and addrCounter >= 16#30#)) then
                                 RAMWrEn <= '1';
                                 state <= WRITEWAIT;
                              end if;

                           when others => null;
                        end case;
                     
                     when x"80" => -- internal write protection / external abort
                        if (isExternal = '0') then
                           writeProtect <= '1';
                        end if;

                     when others => null;
                  end case;
                  
               when CLEAR =>
                  if ((isExternal = '1' and clearCounter < size) or (isExternal = '0' and clearCounter < 16#43#)) then
                     addrCounter  <= clearCounter;
                     RAMWrEn      <= '1';
                     clearCounter <= clearCounter + 1;
                     writevalue   <= defaultvalue;
                     if (isExternal = '0') then
                        if (isColor = '1') then
                           case (clearCounter) is
                              when 16#3B# => writevalue <= x"0101";
                              when 16#3C# => writevalue <= x"0027";
                              when 16#3E# => writevalue <= x"0001";
                              when 16#40# => writevalue <= x"0101";
                              when 16#41# => writevalue <= x"0327";
                              -- wonderswancolor
                              when 16#30# => writevalue <= x"1921";
                              when 16#31# => writevalue <= x"0E18";
                              when 16#32# => writevalue <= x"1C0F";
                              when 16#33# => writevalue <= x"211D";
                              when 16#34# => writevalue <= x"180B";
                              when 16#35# => writevalue <= x"190D";
                              when 16#36# => writevalue <= x"1916";
                              when 16#37# => writevalue <= x"001C";
                              when others => null;
                           end case;
                        else
                           case (clearCounter) is
                              when 16#3B# => writevalue <= x"0001";
                              when 16#3C# => writevalue <= x"0024";
                              when 16#3E# => writevalue <= x"0001";
                              -- wonderswancolor
                              when 16#30# => writevalue <= x"1921";
                              when 16#31# => writevalue <= x"0E18";
                              when 16#32# => writevalue <= x"1C0F";
                              when 16#33# => writevalue <= x"211D";
                              when 16#34# => writevalue <= x"180B";
                              when others => null;
                           end case;
                        end if;
                     end if;
                  else
                     state <= IDLE;
                  end if;
                  
               when OVERWRITE =>
                  if (addrCounter + 1 < size and writeEnable = '1') then
                     addrCounter <= addrCounter + 1;
                     if (isExternal = '1' or writeProtect = '0' or addrCounter + 1 < 16#30#) then
                        RAMWrEn <= '1';
                     end if;
                  else
                     state <= IDLE;
                  end if;

               when WRITEWAIT =>
                  -- RAMWrEn was asserted in the preceding cycle.  Waiting one
                  -- clock keeps READY low until the synchronous RAM has
                  -- committed the write.
                  state <= IDLE;

               when READWAIT =>
                  -- Keep DONE observably low across the next CPU instruction.
                  -- Ten system enables follow the pinned emulator model's
                  -- conservative command delay; it is not a physical write-
                  -- latency claim.
                  if (ce = '1') then
                     if (readDelay = 9) then
                        state <= READONE;
                     else
                        readDelay <= readDelay + 1;
                     end if;
                  end if;
               
               when READONE =>
                  ReadData  <= readvalue;
                  readDone  <= '1';
                  state     <= IDLE;
            
            end case;
         

         end if;
      end if;
   end process;
   

end architecture;
