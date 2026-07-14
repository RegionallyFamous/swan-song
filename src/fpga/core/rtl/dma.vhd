library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

use work.pRegisterBus.all;
use work.pReg_swan.all;  
use work.pBus_savestates.all;
use work.pReg_savestates.all; 

entity dma is
   generic 
   (
      is_simu : std_logic := '0'
   );
   port
   (
      clk              : in  std_logic;
      ce               : in  std_logic;
      reset            : in  std_logic;
      isColor          : in  std_logic;
      -- Current $A0 cartridge-ROM bus configuration.  Defaults preserve all
      -- existing instantiations until the central control owner is wired.
      cartridge_rom_word : in std_logic := '1';
      cartridge_rom_slow : in std_logic := '0';
                       
      dma_active       : out std_logic;
      sdma_active      : out std_logic := '0';
      sdma_request     : out std_logic;
      cpu_idle         : in  std_logic;
                       
      bus_read         : out std_logic := '0';
      bus_write        : out std_logic := '0';
      bus_be           : out std_logic_vector(1 downto 0);
      bus_addr         : out unsigned(19 downto 0) := (others => '0');
      bus_datawrite    : out std_logic_vector(15 downto 0) := (others => '0');
      bus_dataread     : in  std_logic_vector(15 downto 0);
      
      -- sound DMA
      soundDMAvalue    : out std_logic_vector(7 downto 0);
      soundDMACh2      : out std_logic := '0';
      soundDMACh5      : out std_logic := '0';
     
      -- register
      RegBus_Din       : in  std_logic_vector(BUS_buswidth-1 downto 0);
      RegBus_Adr       : in  std_logic_vector(BUS_busadr-1 downto 0);
      RegBus_wren      : in  std_logic := '0';
      RegBus_rst       : in  std_logic;
      RegBus_Dout      : out std_logic_vector(BUS_buswidth-1 downto 0);
      
      -- savestates    
      sleep_savestate  : in  std_logic;      
      
      SSBUS_Din        : in  std_logic_vector(SSBUS_buswidth-1 downto 0);
      SSBUS_Adr        : in  std_logic_vector(SSBUS_busadr-1 downto 0);
      SSBUS_wren       : in  std_logic;
      SSBUS_rst        : in  std_logic;
      SSBUS_Dout       : out std_logic_vector(SSBUS_buswidth-1 downto 0)
   );
end entity;

architecture arch of dma is
   
   -- register
   signal DMA_SRC      : std_logic_vector(19 downto 0) := (others => '0');
   signal DMA_DST      : std_logic_vector(15 downto 0) := (others => '0');
   signal DMA_LEN      : std_logic_vector(15 downto 0) := (others => '0');
   signal DMA_CTRL     : std_logic_vector( 7 downto 0) := (others => '0');
   
   signal DMA_SRC_L_written : std_logic;
   signal DMA_SRC_M_written : std_logic;
   signal DMA_SRC_H_written : std_logic;
   signal DMA_DST_L_written : std_logic;
   signal DMA_DST_H_written : std_logic;
   signal DMA_LEN_L_written : std_logic;
   signal DMA_LEN_H_written : std_logic;
   signal DMA_CTRL_written  : std_logic;

   signal SDMA_CTRL    : std_logic_vector( 7 downto 0) := (others => '0');
   
   signal SDMA_SRC_L_written : std_logic;
   signal SDMA_SRC_M_written : std_logic;
   signal SDMA_SRC_H_written : std_logic;
   signal SDMA_LEN_L_written : std_logic;
   signal SDMA_LEN_M_written : std_logic;
   signal SDMA_LEN_H_written : std_logic;
   signal SDMA_CTRL_written  : std_logic;
   
   type t_reg_wired_or is array(0 to 14) of std_logic_vector(7 downto 0);
   signal reg_wired_or : t_reg_wired_or;
   signal RegBus_wren_color : std_logic;
   
   -- internal
   type tState is
   (
      IDLE,
      WAITING,
      READING,
      WRITING,
      DONE,
      SDMA_READ,
      SDMA_READDONE
   );
   signal state : tState;
   
   signal dmaOn   : std_logic := '0';
   signal waitcnt : integer range 0 to 4;
   
   -- sound DMA
   signal SDMA_SRC_work   : std_logic_vector(19 downto 0) := (others => '0');
   signal SDMA_LEN_work   : std_logic_vector(19 downto 0) := (others => '0');
   signal SDMA_SRC_reload : std_logic_vector(19 downto 0) := (others => '0');
   signal SDMA_LEN_reload : std_logic_vector(19 downto 0) := (others => '0');
   signal sdmaSlow        : unsigned(9 downto 0);
   signal sdma_requestIntern : std_logic;
   signal sdma_state_code : std_logic_vector(2 downto 0);
   
   -- savestates
   type t_ss_wired_or is array(0 to 2) of std_logic_vector(63 downto 0);
   signal ss_wired_or : t_ss_wired_or;
   
   signal SS_DMA           : std_logic_vector(REG_SAVESTATE_DMA     .upper downto REG_SAVESTATE_DMA     .lower);
   signal SS_DMA_BACK      : std_logic_vector(REG_SAVESTATE_DMA     .upper downto REG_SAVESTATE_DMA     .lower);
   
   signal SS_SOUNDDMA      : std_logic_vector(REG_SAVESTATE_SOUNDDMA.upper downto REG_SAVESTATE_SOUNDDMA.lower);
   signal SS_SOUNDDMA_BACK : std_logic_vector(REG_SAVESTATE_SOUNDDMA.upper downto REG_SAVESTATE_SOUNDDMA.lower);

   signal SS_SOUNDDMA_EXT      : std_logic_vector(REG_SAVESTATE_SOUNDDMA_EXT.upper downto REG_SAVESTATE_SOUNDDMA_EXT.lower);
   signal SS_SOUNDDMA_EXT_BACK : std_logic_vector(REG_SAVESTATE_SOUNDDMA_EXT.upper downto REG_SAVESTATE_SOUNDDMA_EXT.lower);

   -- GDMA accepts only 16-bit, single-cycle sources.  IRAM (segment 0) is
   -- always eligible; SRAM (segment 1) is always byte-wide; cartridge ROM
   -- (segments 2-F) requires the live $A0 word-width bit and no ROM wait.
   -- Re-evaluating this predicate before every word matches hardware's
   -- mid-transfer stop at a region boundary or after configuration changes.
   --
   -- WSdev DMA, permanent revision 562:
   -- https://ws.nesdev.org/w/index.php?title=DMA&oldid=562
   -- Mesen2 b9fa69d RunGeneralDma:
   -- https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsDmaController.cpp#L14-L44
   function gdma_source_valid(
      source_address : std_logic_vector(19 downto 0);
      rom_word       : std_logic;
      rom_slow       : std_logic
   ) return boolean is
   begin
      case source_address(19 downto 16) is
         when x"0" => return true;
         when x"1" => return false;
         when others => return rom_word = '1' and rom_slow = '0';
      end case;
   end function;

begin

   -- Mesen2 b9fa69d models $40-$53 as physically present on Color hardware,
   -- but returns zero and ignores every write while $60 bit 7 is clear.
   -- sleep_savestate keeps raw readback visible to the legacy 256-port image;
   -- DMA's dedicated SS records remain the authoritative restore path.
   -- https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsMemoryManager.cpp
   RegBus_wren_color <= RegBus_wren when isColor = '1' else '0';

   iREG_DMA_SRC_L  : entity work.eReg generic map ( REG_DMA_SRC_L  ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or( 0), DMA_SRC( 7 downto  0) , open, DMA_SRC_L_written  );
   iREG_DMA_SRC_M  : entity work.eReg generic map ( REG_DMA_SRC_M  ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or( 1), DMA_SRC(15 downto  8) , open, DMA_SRC_M_written  );
   iREG_DMA_SRC_H  : entity work.eReg generic map ( REG_DMA_SRC_H  ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or( 2), DMA_SRC(19 downto 16) , open, DMA_SRC_H_written  );
   iREG_DMA_DST_L  : entity work.eReg generic map ( REG_DMA_DST_L  ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or( 3), DMA_DST( 7 downto  0) , open, DMA_DST_L_written  );
   iREG_DMA_DST_H  : entity work.eReg generic map ( REG_DMA_DST_H  ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or( 4), DMA_DST(15 downto  8) , open, DMA_DST_H_written  );
   iREG_DMA_LEN_L  : entity work.eReg generic map ( REG_DMA_LEN_L  ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or( 5), DMA_LEN( 7 downto  0) , open, DMA_LEN_L_written  );
   iREG_DMA_LEN_H  : entity work.eReg generic map ( REG_DMA_LEN_H  ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or( 6), DMA_LEN(15 downto  8) , open, DMA_LEN_H_written  );
   iREG_DMA_CTRL   : entity work.eReg generic map ( REG_DMA_CTRL   ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or( 7), DMA_CTRL              , open, DMA_CTRL_written   );
   
   iREG_SDMA_SRC_L : entity work.eReg generic map ( REG_SDMA_SRC_L ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or( 8), SDMA_SRC_work( 7 downto  0), open, SDMA_SRC_L_written);
   iREG_SDMA_SRC_M : entity work.eReg generic map ( REG_SDMA_SRC_M ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or( 9), SDMA_SRC_work(15 downto  8), open, SDMA_SRC_M_written);
   iREG_SDMA_SRC_H : entity work.eReg generic map ( REG_SDMA_SRC_H ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or(10), SDMA_SRC_work(19 downto 16), open, SDMA_SRC_H_written);
   iREG_SDMA_LEN_L : entity work.eReg generic map ( REG_SDMA_LEN_L ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or(11), SDMA_LEN_work( 7 downto  0), open, SDMA_LEN_L_written);
   iREG_SDMA_LEN_M : entity work.eReg generic map ( REG_SDMA_LEN_M ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or(12), SDMA_LEN_work(15 downto  8), open, SDMA_LEN_M_written);
   iREG_SDMA_LEN_H : entity work.eReg generic map ( REG_SDMA_LEN_H ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or(13), SDMA_LEN_work(19 downto 16), open, SDMA_LEN_H_written);
   iREG_SDMA_CTRL  : entity work.eReg generic map ( REG_SDMA_CTRL  ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren_color, RegBus_rst, reg_wired_or(14), SDMA_CTRL             , open, SDMA_CTRL_written  );

   process (all)
      variable wired_or : std_logic_vector(7 downto 0);
   begin
      wired_or := reg_wired_or(0);
      for i in 1 to (reg_wired_or'length - 1) loop
         wired_or := wired_or or reg_wired_or(i);
      end loop;
      if (isColor = '1' or sleep_savestate = '1') then
         RegBus_Dout <= wired_or;
      else
         RegBus_Dout <= (others => '0');
      end if;
   end process;
   
   -- On the final WRITING edge dmaOn clears immediately to avoid an extra
   -- DONE busy cycle.  Keep ownership through that edge's bus-write pulse so
   -- SwanTop still selects the DMA address/data for the completed word.
   dma_active   <= dmaOn or bus_write;
   sdma_request <= sdma_requestIntern when is_simu = '0' else '0';
   
   bus_be <= "11";
   
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
   
   iSS_DMA        : entity work.eReg_SS generic map ( REG_SAVESTATE_DMA      ) port map (clk, SSBUS_Din, SSBUS_Adr, SSBUS_wren, SSBUS_rst, ss_wired_or(0), SS_DMA_BACK     , SS_DMA       );
   iSS_SOUNDDMA   : entity work.eReg_SS generic map ( REG_SAVESTATE_SOUNDDMA ) port map (clk, SSBUS_Din, SSBUS_Adr, SSBUS_wren, SSBUS_rst, ss_wired_or(1), SS_SOUNDDMA_BACK, SS_SOUNDDMA  );
   iSS_SOUNDDMA_EXT : entity work.eReg_SS generic map ( REG_SAVESTATE_SOUNDDMA_EXT ) port map (clk, SSBUS_Din, SSBUS_Adr, SSBUS_wren, SSBUS_rst, ss_wired_or(2), SS_SOUNDDMA_EXT_BACK, SS_SOUNDDMA_EXT);
   
   SS_DMA_BACK(15 downto  0) <= DMA_LEN; 
   SS_DMA_BACK(31 downto 16) <= DMA_DST; 
   SS_DMA_BACK(51 downto 32) <= DMA_SRC; 
   SS_DMA_BACK(59 downto 52) <= DMA_CTRL;
   
   
   SS_SOUNDDMA_BACK(19 downto  0) <= SDMA_LEN_work;
   SS_SOUNDDMA_BACK(31 downto 20) <= (31 downto 20 => '0');  --unused
   SS_SOUNDDMA_BACK(51 downto 32) <= SDMA_SRC_work;
   SS_SOUNDDMA_BACK(59 downto 52) <= SDMA_CTRL;

   -- Versioned extension in the previously-unused internal slot 18.  Slot 17
   -- remains byte-for-byte compatible with existing save images.
   SS_SOUNDDMA_EXT_BACK(19 downto  0) <= SDMA_LEN_reload;
   SS_SOUNDDMA_EXT_BACK(39 downto 20) <= SDMA_SRC_reload;
   SS_SOUNDDMA_EXT_BACK(49 downto 40) <= std_logic_vector(sdmaSlow);
   SS_SOUNDDMA_EXT_BACK(50)           <= sdma_requestIntern;
   SS_SOUNDDMA_EXT_BACK(53 downto 51) <= sdma_state_code;
   SS_SOUNDDMA_EXT_BACK(59 downto 54) <= (others => '0');
   SS_SOUNDDMA_EXT_BACK(62 downto 60) <= "001";
   SS_SOUNDDMA_EXT_BACK(63)           <= '1';

   -- Fixed encodings make the save format independent of the compiler's
   -- representation of tState.  Only IDLE and the pre-bus SDMA_READ state are
   -- legal restore points; the remaining encodings are diagnostic on save.
   with state select sdma_state_code <=
      "000" when IDLE,
      "001" when WAITING,
      "010" when READING,
      "011" when WRITING,
      "100" when DONE,
      "101" when SDMA_READ,
      "110" when SDMA_READDONE;
   
   
   process (clk)
      variable sdma_timerhit : std_logic;
      variable gdma_start_accepted : boolean;
      variable gdma_next_source : std_logic_vector(19 downto 0);
   begin
      if rising_edge(clk) then

         -- The register-write path and the CE-driven shared FSM both run in
         -- this process.  Remember an accepted GDMA start so the later IDLE
         -- arbitration cannot overwrite WAITING with a pending SDMA grant on
         -- the same edge and leave dmaOn stranded high in IDLE.
         gdma_start_accepted := false;
      
         bus_read  <= '0';
         bus_write <= '0';
                
         soundDMACh2 <= '0';
         soundDMACh5 <= '0';
         
         -- DMA
         if (sleep_savestate = '0') then
            if (DMA_SRC_L_written = '1') then DMA_SRC( 7 downto  1) <= RegBus_Din(7 downto 1); end if;
            if (DMA_SRC_M_written = '1') then DMA_SRC(15 downto  8) <= RegBus_Din; end if;
            if (DMA_SRC_H_written = '1') then DMA_SRC(19 downto 16) <= RegBus_Din(3 downto 0); end if;
            if (DMA_DST_L_written = '1') then DMA_DST( 7 downto  1) <= RegBus_Din(7 downto 1); end if;
            if (DMA_DST_H_written = '1') then DMA_DST(15 downto  8) <= RegBus_Din; end if;
            if (DMA_LEN_L_written = '1') then DMA_LEN( 7 downto  1) <= RegBus_Din(7 downto 1); end if;
            if (DMA_LEN_H_written = '1') then DMA_LEN(15 downto  8) <= RegBus_Din; end if;
         end if;
      
         if (DMA_CTRL_written = '1' and dmaOn = '0' and sleep_savestate = '0' and isColor = '1') then
            DMA_CTRL(7) <= RegBus_Din(7);
            DMA_CTRL(0) <= RegBus_Din(6);
            if (RegBus_Din(7) = '1') then
               if (unsigned(DMA_LEN) > 0 and
                   gdma_source_valid(DMA_SRC, cartridge_rom_word, cartridge_rom_slow)) then
                  dmaOn   <= '1';
                  state   <= WAITING;
                  waitcnt <= 0;
                  gdma_start_accepted := true;
               else
                  DMA_CTRL(7) <= '0';
               end if;
            end if;
         end if;
         
         -- SOUND DMA
         if (SDMA_CTRL_written = '1' and sleep_savestate = '0' and isColor = '1') then
            SDMA_CTRL <= RegBus_Din(7 downto 6) & '0' & RegBus_Din(4 downto 0);
            if (RegBus_Din(7) = '1' and unsigned(SDMA_LEN_work) = 0) then
               SDMA_CTRL(7) <= '0';
               if (state /= SDMA_READ and state /= SDMA_READDONE) then
                  sdma_requestIntern <= '0';
               end if;
            elsif (RegBus_Din(7) = '0' and state /= SDMA_READ and state /= SDMA_READDONE) then
               sdma_requestIntern <= '0';
            end if;
         end if;
      
         if (reset = '1') then
         
            DMA_LEN  <= SS_DMA(15 downto  0);
            DMA_DST  <= SS_DMA(31 downto 16);
            DMA_SRC  <= SS_DMA(51 downto 32);
            DMA_CTRL <= SS_DMA(59 downto 52);
              
            dmaOn <= '0';
            state <= IDLE;
         
            SDMA_LEN_work <= SS_SOUNDDMA(19 downto  0);
            SDMA_SRC_work <= SS_SOUNDDMA(51 downto 32);
            SDMA_CTRL     <= SS_SOUNDDMA(59 downto 52);

            sdma_active        <= '0';
            if (SS_SOUNDDMA_EXT(63) = '1' and
                SS_SOUNDDMA_EXT(62 downto 60) = "001" and
                SS_SOUNDDMA_EXT(59 downto 54) = "000000") then
               SDMA_LEN_reload    <= SS_SOUNDDMA_EXT(19 downto  0);
               SDMA_SRC_reload    <= SS_SOUNDDMA_EXT(39 downto 20);
               sdmaSlow           <= unsigned(SS_SOUNDDMA_EXT(49 downto 40));

               -- The save handshake can quiesce in IDLE or after IDLE has
               -- selected SDMA_READ but before that state asserts bus_read.
               -- No bus_dataread latch is saved, so every other state must
               -- fail safe rather than resume a partial transaction.  An IDLE
               -- request cannot legally survive with Sound DMA disabled, but
               -- an already-selected SDMA_READ must finish atomically even if
               -- software disabled the channel before the save handshake.
               if (SS_SOUNDDMA_EXT(53 downto 51) = "101" and
                   SS_SOUNDDMA_EXT(50) = '1') then
                  state <= SDMA_READ;
                  sdma_requestIntern <= '1';
               elsif (SS_SOUNDDMA_EXT(53 downto 51) = "000") then
                  state <= IDLE;
                  if (SS_SOUNDDMA(59) = '1') then
                     sdma_requestIntern <= SS_SOUNDDMA_EXT(50);
                  else
                     sdma_requestIntern <= '0';
                  end if;
               else
                  state <= IDLE;
                  sdma_requestIntern <= '0';
               end if;
            else
               -- Legacy images have an all-zero slot 18.  Their visible live
               -- counters are the best available repeat reload values.
               SDMA_LEN_reload    <= SS_SOUNDDMA(19 downto  0);
               SDMA_SRC_reload    <= SS_SOUNDDMA(51 downto 32);
               sdmaSlow           <= (others => '0');
               sdma_requestIntern <= '0';
               state              <= IDLE;
            end if;
            
         elsif (ce = '1') then
            
            if (SDMA_CTRL(7) = '1' and not (SDMA_CTRL_written = '1' and sleep_savestate = '0' and isColor = '1' and (RegBus_Din(7) = '0' or unsigned(SDMA_LEN_work) = 0))) then
               sdmaSlow      <= sdmaSlow + 1;
               sdma_timerhit := '0';
               case (SDMA_CTRL(1 downto 0)) is
                  when "00" => if (sdmaSlow >= 767) then sdma_timerhit := '1'; end if;
                  when "01" => if (sdmaSlow >= 511) then sdma_timerhit := '1'; end if;
                  when "10" => if (sdmaSlow >= 255) then sdma_timerhit := '1'; end if;
                  when "11" => if (sdmaSlow >= 127) then sdma_timerhit := '1'; end if;
                  when others => null;
               end case;
               if (sdma_timerhit = '1') then
                  sdmaSlow           <= (others => '0');
                  sdma_requestIntern <= '1';
               end if;
            end if;
         
            case (state) is
         
               when IDLE =>
                  if (gdma_start_accepted) then
                     -- GDMA owns this edge; retain any pending SDMA request so
                     -- it can arbitrate normally after the block transfer.
                     null;
                  elsif (SDMA_CTRL_written = '1' and sleep_savestate = '0' and isColor = '1' and (RegBus_Din(7) = '0' or unsigned(SDMA_LEN_work) = 0)) then
                     sdma_requestIntern <= '0';
                  elsif (sdma_requestIntern = '1') then
                     if (SDMA_CTRL(7) = '0') then
                        sdma_requestIntern <= '0';
                     elsif (cpu_idle = '1' or is_simu = '1') then
                        state         <= SDMA_READ;
                     end if;
                  end if;
                  
               when WAITING =>
                  if (waitcnt < 4) then
                     waitcnt <= waitcnt + 1;
                  else
                     state <= READING;
                  end if;
         
               when READING =>
                  if (gdma_source_valid(DMA_SRC, cartridge_rom_word, cartridge_rom_slow)) then
                     state    <= WRITING;
                     bus_read <= '1';
                     bus_addr <= unsigned(DMA_SRC);
                  else
                     -- Abort before issuing or accounting the current word.
                     -- Prior completed words remain reflected in the live
                     -- source, destination, and length registers.
                     state       <= IDLE;
                     dmaOn       <= '0';
                     DMA_CTRL(7) <= '0';
                  end if;
                  
               when WRITING =>
                  bus_write     <= '1';
                  bus_addr      <= x"0" & unsigned(DMA_DST);
                  bus_datawrite <= bus_dataread;
                  DMA_LEN <= std_logic_vector(unsigned(DMA_LEN) - 2);
                  if (DMA_CTRL(0) = '1') then
                     gdma_next_source := std_logic_vector(unsigned(DMA_SRC) - 2);
                     DMA_SRC <= gdma_next_source;
                     DMA_DST <= std_logic_vector(unsigned(DMA_DST) - 2);
                  else
                     gdma_next_source := std_logic_vector(unsigned(DMA_SRC) + 2);
                     DMA_SRC <= gdma_next_source;
                     DMA_DST <= std_logic_vector(unsigned(DMA_DST) + 2);
                  end if;
                  if (unsigned(DMA_LEN) = 2) then
                     -- The bus_write pulse above holds dma_active high for
                     -- this final transfer CE.  Retire directly to IDLE so
                     -- total active time is exactly 5 + 2*words CE pulses.
                     state       <= IDLE;
                     dmaOn       <= '0';
                     DMA_CTRL(7) <= '0';
                  elsif (not gdma_source_valid(
                           gdma_next_source,
                           cartridge_rom_word,
                           cartridge_rom_slow)) then
                     -- Source validation itself has zero cycle cost.  Retire
                     -- on the completed-write edge when the next word crosses
                     -- into an ineligible region or the live bus mode changed,
                     -- rather than stalling the CPU for an abort-only CE.
                     state       <= IDLE;
                     dmaOn       <= '0';
                     DMA_CTRL(7) <= '0';
                  else
                     state <= READING;
                  end if;
                  
               when DONE =>
                  state       <= IDLE;
                  dmaOn       <= '0';
                  DMA_CTRL(7) <= '0';
                  
               when SDMA_READ =>
                  state        <= SDMA_READDONE;
                  if (is_simu = '0') then
                     sdma_active   <= '1';
                     bus_read      <= '1';
                     bus_addr      <= unsigned(SDMA_SRC_work);
                  end if;
                  if (SDMA_CTRL(2) = '0') then
                     SDMA_LEN_work <= std_logic_vector(unsigned(SDMA_LEN_work) - 1);
                     if (SDMA_CTRL(6) = '1') then
                        SDMA_SRC_work <= std_logic_vector(unsigned(SDMA_SRC_work) - 1);
                     else
                        SDMA_SRC_work <= std_logic_vector(unsigned(SDMA_SRC_work) + 1);
                     end if;
                  end if;
               
               when SDMA_READDONE =>
                  state        <= IDLE;
                  sdma_requestIntern <= '0';
                  sdma_active  <= '0';
                  
                  if (SDMA_CTRL(2) = '1') then
                     soundDMAvalue <= x"00";
                  else
                     soundDMAvalue <= bus_dataread(7 downto 0);
                  end if;
                  soundDMACh2   <= not SDMA_CTRL(4);
                  soundDMACh5   <= SDMA_CTRL(4);
                  
                  if (SDMA_CTRL(2) = '0' and unsigned(SDMA_LEN_work) = 0) then
                     if (SDMA_CTRL(3) = '1') then
                        SDMA_SRC_work <= SDMA_SRC_reload;
                        SDMA_LEN_work <= SDMA_LEN_reload;
                     else
                        SDMA_CTRL(7) <= '0';
                     end if;
                  end if;

            end case;
            
         end if;

         -- The visible source/length ports are the live counters.  Explicit
         -- process-owned shadows retain the same writes for repeat reloads and
         -- save-state restoration.  These byte assignments are last so CPU
         -- writes win coincident transfers.
         if (reset = '0' and sleep_savestate = '0') then
            if (SDMA_SRC_L_written = '1') then
               SDMA_SRC_work( 7 downto  0) <= RegBus_Din;
               SDMA_SRC_reload( 7 downto  0) <= RegBus_Din;
            end if;
            if (SDMA_SRC_M_written = '1') then
               SDMA_SRC_work(15 downto  8) <= RegBus_Din;
               SDMA_SRC_reload(15 downto  8) <= RegBus_Din;
            end if;
            if (SDMA_SRC_H_written = '1') then
               SDMA_SRC_work(19 downto 16) <= RegBus_Din(3 downto 0);
               SDMA_SRC_reload(19 downto 16) <= RegBus_Din(3 downto 0);
            end if;
            if (SDMA_LEN_L_written = '1') then
               SDMA_LEN_work( 7 downto  0) <= RegBus_Din;
               SDMA_LEN_reload( 7 downto  0) <= RegBus_Din;
            end if;
            if (SDMA_LEN_M_written = '1') then
               SDMA_LEN_work(15 downto  8) <= RegBus_Din;
               SDMA_LEN_reload(15 downto  8) <= RegBus_Din;
            end if;
            if (SDMA_LEN_H_written = '1') then
               SDMA_LEN_work(19 downto 16) <= RegBus_Din(3 downto 0);
               SDMA_LEN_reload(19 downto 16) <= RegBus_Din(3 downto 0);
            end if;
         end if;
      end if;
   end process;
     

end architecture;
