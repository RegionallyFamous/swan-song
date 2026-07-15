-- Modified for Swan Song by Regionally Famous on 2026-07-14.
-- See UPSTREAMS.md and LICENSING.md for provenance and licensing details.

library IEEE;
use IEEE.std_logic_1164.all;  
use IEEE.numeric_std.all; 

use work.pRegisterBus.all;  
use work.pReg_swan.all;

entity rtc is
   port 
   (
      clk                  : in  std_logic;
      ce                   : in  std_logic;
      reset                : in  std_logic;
      hasRTC               : in  std_logic;                     -- Unused
      
      RTC_timestampNew     : in  std_logic;                     -- new current timestamp from system
      RTC_timestampIn      : in  std_logic_vector(31 downto 0); -- timestamp in seconds, current time
      RTC_timestampSaved   : in  std_logic_vector(31 downto 0); -- timestamp in seconds, saved time
      RTC_savedtimeIn      : in  std_logic_vector(41 downto 0); -- time structure, loaded
      RTC_saveLoaded       : in  std_logic;                     -- must be 0 when loading new game, should go and stay 1 when RTC was loaded and values are valid
      RTC_timestampOut     : out std_logic_vector(31 downto 0); -- timestamp to be saved
      RTC_savedtimeOut     : out std_logic_vector(41 downto 0); -- time structure to be saved

      sleep_savestate      : in  std_logic;

      -- Exact device state for the Memories v2 RTC section.  Capture clients
      -- first assert state_freeze and wait for state_frozen.  state_data_out
      -- is then stable until state_freeze is released.  A state_load pulse is
      -- accepted only while frozen and directly replaces the RTC state; it
      -- does not replay register writes or command side effects.
      state_freeze         : in  std_logic := '0';
      state_frozen         : out std_logic := '0';
      state_load           : in  std_logic := '0';
      state_data_in        : in  std_logic_vector(255 downto 0) := (others => '0');
      state_data_out       : out std_logic_vector(255 downto 0) := (others => '0');

      RegBus_Din           : in  std_logic_vector(BUS_buswidth-1 downto 0);
      RegBus_Adr           : in  std_logic_vector(BUS_busadr-1 downto 0);
      RegBus_wren          : in  std_logic;
      RegBus_rden          : in  std_logic;
      RegBus_rst           : in  std_logic;
      RegBus_Dout          : out std_logic_vector(BUS_buswidth-1 downto 0)
   );
end entity;

architecture arch of rtc is
  
   -- register
   signal RTC_COMMAND : std_logic_vector(7 downto 0) := (others => '0');
   signal RTC_READ    : std_logic_vector(7 downto 0) := (others => '0');
   
   signal RTC_COMMAND_written : std_logic;
   
   type t_reg_wired_or is array(0 to 1) of std_logic_vector(7 downto 0);
   signal reg_wired_or : t_reg_wired_or;
   
   -- internal logic
   -- The serialized forms intentionally cover the complete binary widths.
   -- Values 7 and 36864000..67108863 are invalid v2 input and are rejected by
   -- the outer loader, but retaining their full widths here makes this device
   -- interface total and avoids simulator range failures on untrusted input.
   signal index            : integer range 0 to 7 := 0;
   signal RegBus_wren_1    : std_logic := '0';
   signal RegBus_rden_1    : std_logic := '0';
   
   signal RTC_timestampNew_1 : std_logic := '0';
   
   signal rtc_change       : std_logic := '0';
   signal RTC_saveLoaded_1 : std_logic := '0';
   
   -- Power-on zero is intentionally deterministic before Pocket's first
   -- 0090 timestamp seed.  The edge detector below retains the legacy seed
   -- behavior and does not continuously follow the host clock.
   signal RTC_timestamp    : std_logic_vector(31 downto 0) := (others => '0');
   signal diffSeconds      : unsigned(31 downto 0) := (others => '0');
   
   signal secondcount      : integer range 0 to 67108863 := 0; -- 26-bit phase; 1 second at 36.864 MHz
                           
   signal tm_year          : unsigned(7 downto 0) := x"00";
   signal tm_mon           : unsigned(4 downto 0) := '0' & x"1";
   signal tm_mday          : unsigned(5 downto 0) := "00" & x"1";
   signal tm_wday          : unsigned(2 downto 0) := "000";
   signal tm_hour          : unsigned(5 downto 0) := "00" & x"0";
   signal tm_min           : unsigned(6 downto 0) := "000" & x"0";
   signal tm_sec           : unsigned(6 downto 0) := "000" & x"1";
                           
   signal buf_tm_year      : std_logic_vector(7 downto 0) := x"00";
   signal buf_tm_mon       : std_logic_vector(4 downto 0) := '0' & x"1";
   signal buf_tm_mday      : std_logic_vector(5 downto 0) := "00" & x"1";
   signal buf_tm_wday      : std_logic_vector(2 downto 0) := "000";
   signal buf_tm_hour      : std_logic_vector(5 downto 0) := "00" & x"0";
   signal buf_tm_min       : std_logic_vector(6 downto 0) := "000" & x"0";
   signal buf_tm_sec       : std_logic_vector(6 downto 0) := "000" & x"1";

   signal rtc_regbus_wren  : std_logic;
   signal rtc_regbus_rst   : std_logic;
   signal state_frozen_i   : std_logic := '0';

begin 
   -- eReg's stored writeback value is not architecturally visible here, but
   -- suppressing its write input ensures that *all* sequential state below
   -- the RTC device boundary is held during a cooperative freeze.
   rtc_regbus_wren <= RegBus_wren when state_freeze = '0' else '0';
   rtc_regbus_rst  <= RegBus_rst  when state_freeze = '0' else '0';

   iREG_RTC_COMMAND : entity work.eReg generic map ( REG_RTC_COMMAND ) port map (clk, RegBus_Din, RegBus_Adr, rtc_regbus_wren, rtc_regbus_rst, reg_wired_or(0), x"80"   , open, RTC_COMMAND_written);
   iREG_RTC_WRITE   : entity work.eReg generic map ( REG_RTC_WRITE   ) port map (clk, RegBus_Din, RegBus_Adr, rtc_regbus_wren, rtc_regbus_rst, reg_wired_or(1), RTC_READ, open);
   
   process (reg_wired_or)
      variable wired_or : std_logic_vector(7 downto 0);
   begin
      wired_or := reg_wired_or(0);
      for i in 1 to (reg_wired_or'length - 1) loop
         wired_or := wired_or or reg_wired_or(i);
      end loop;
      RegBus_Dout <= wired_or;
   end process;
               
   RTC_timestampOut <= RTC_timestamp;
   RTC_savedtimeOut(41 downto 34) <= buf_tm_year;
   RTC_savedtimeOut(33 downto 29) <= buf_tm_mon; 
   RTC_savedtimeOut(28 downto 23) <= buf_tm_mday;
   RTC_savedtimeOut(22 downto 20) <= buf_tm_wday;
   RTC_savedtimeOut(19 downto 14) <= buf_tm_hour;
   RTC_savedtimeOut(13 downto 7)  <= buf_tm_min; 
   RTC_savedtimeOut(6 downto 0)   <= buf_tm_sec; 

   state_frozen <= state_frozen_i;

   -- Stable, byte-aligned v2 RTC image.  Byte +0x00 is bits 255:248, matching
   -- the ABI rule that the lowest normalized byte occupies bridge bits 31:24.
   -- This is the active first 0x20 bytes of the fixed 0x100-byte RTC section;
   -- its serializer writes the remaining 0xe0 section bytes as zero.
   --
   --   00 command       01 read latch       02 index (low 3 bits)
   --   03 edge/change flags: wren, rden, timestampNew, change, saveLoaded
   --   04..07 timestamp 08..0b catch-up     0c..0f subsecond phase
   --   10..16 live BCD calendar (year, month, mday, wday, hour, min, sec)
   --   17..1d buffered BCD calendar         1e..1f zero
   --
   -- Unused upper bits within calendar/index/flag bytes are canonical zero.
   -- Do not reorder these bytes without changing the device schema/ABI.
   process (all)
      variable packed_state : std_logic_vector(255 downto 0);
   begin
      packed_state := (others => '0');
      packed_state(255 downto 248) := RTC_COMMAND;
      packed_state(247 downto 240) := RTC_READ;
      packed_state(234 downto 232) := std_logic_vector(to_unsigned(index, 3));
      packed_state(224)            := RegBus_wren_1;
      packed_state(225)            := RegBus_rden_1;
      packed_state(226)            := RTC_timestampNew_1;
      packed_state(227)            := rtc_change;
      packed_state(228)            := RTC_saveLoaded_1;
      packed_state(223 downto 192) := RTC_timestamp;
      packed_state(191 downto 160) := std_logic_vector(diffSeconds);
      packed_state(159 downto 128) := std_logic_vector(to_unsigned(secondcount, 32));
      packed_state(127 downto 120) := std_logic_vector(tm_year);
      packed_state(116 downto 112) := std_logic_vector(tm_mon);
      packed_state(109 downto 104) := std_logic_vector(tm_mday);
      packed_state(98 downto 96)   := std_logic_vector(tm_wday);
      packed_state(93 downto 88)   := std_logic_vector(tm_hour);
      packed_state(86 downto 80)   := std_logic_vector(tm_min);
      packed_state(78 downto 72)   := std_logic_vector(tm_sec);
      packed_state(71 downto 64)   := buf_tm_year;
      packed_state(60 downto 56)   := buf_tm_mon;
      packed_state(53 downto 48)   := buf_tm_mday;
      packed_state(42 downto 40)   := buf_tm_wday;
      packed_state(37 downto 32)   := buf_tm_hour;
      packed_state(30 downto 24)   := buf_tm_min;
      packed_state(22 downto 16)   := buf_tm_sec;
      state_data_out <= packed_state;
   end process;
               
   process (clk)
   begin
      if rising_edge(clk) then

         -- The acknowledge rises only after an edge on which the complete
         -- emulated RTC process was held.  It remains high until release.
         state_frozen_i <= state_freeze;

         -- Freeze deliberately dominates reset and register reset.  The v2
         -- owner aborts an interrupted transaction by dropping state_freeze;
         -- reset is then observed by this device on the following edge.
         if (state_freeze = '1') then

            -- A load is accepted only after the requester has observed the
            -- previous-cycle acknowledge.  This enforces the documented
            -- request -> frozen -> load ordering at the device boundary.
            if (state_load = '1' and state_frozen_i = '1') then
               RTC_COMMAND        <= state_data_in(255 downto 248);
               RTC_READ           <= state_data_in(247 downto 240);
               index              <= to_integer(unsigned(state_data_in(234 downto 232)));
               RegBus_wren_1      <= state_data_in(224);
               RegBus_rden_1      <= state_data_in(225);
               RTC_timestampNew_1 <= state_data_in(226);
               rtc_change         <= state_data_in(227);
               RTC_saveLoaded_1   <= state_data_in(228);
               RTC_timestamp      <= state_data_in(223 downto 192);
               diffSeconds        <= unsigned(state_data_in(191 downto 160));
               secondcount        <= to_integer(unsigned(state_data_in(153 downto 128)));
               tm_year            <= unsigned(state_data_in(127 downto 120));
               tm_mon             <= unsigned(state_data_in(116 downto 112));
               tm_mday            <= unsigned(state_data_in(109 downto 104));
               tm_wday            <= unsigned(state_data_in(98 downto 96));
               tm_hour            <= unsigned(state_data_in(93 downto 88));
               tm_min             <= unsigned(state_data_in(86 downto 80));
               tm_sec             <= unsigned(state_data_in(78 downto 72));
               buf_tm_year        <= state_data_in(71 downto 64);
               buf_tm_mon         <= state_data_in(60 downto 56);
               buf_tm_mday        <= state_data_in(53 downto 48);
               buf_tm_wday        <= state_data_in(42 downto 40);
               buf_tm_hour        <= state_data_in(37 downto 32);
               buf_tm_min         <= state_data_in(30 downto 24);
               buf_tm_sec         <= state_data_in(22 downto 16);
            end if;

         else
      
         if (rtc_change = '0') then
            buf_tm_year <= std_logic_vector(tm_year);
            buf_tm_mon  <= std_logic_vector(tm_mon); 
            buf_tm_mday <= std_logic_vector(tm_mday);
            buf_tm_wday <= std_logic_vector(tm_wday);
            buf_tm_hour <= std_logic_vector(tm_hour);
            buf_tm_min  <= std_logic_vector(tm_min); 
            buf_tm_sec  <= std_logic_vector(tm_sec); 
         end if;
      
         rtc_change <= '0';
         
         if (secondcount < 36863999) then
            secondcount <= secondcount + 1;
         else
            secondcount <= 0;
         end if;
         
         RTC_saveLoaded_1 <= RTC_saveLoaded;
         if (RTC_saveLoaded_1 = '0' and  RTC_saveLoaded = '1') then
         
            if (unsigned(RTC_timestamp) > unsigned(RTC_timestampSaved)) then
               diffSeconds <= unsigned(RTC_timestamp) - unsigned(RTC_timestampSaved);
            end if;
         
            tm_year <= unsigned(RTC_savedtimeIn(41 downto 34));
            tm_mon  <= unsigned(RTC_savedtimeIn(33 downto 29));
            tm_mday <= unsigned(RTC_savedtimeIn(28 downto 23));
            tm_wday <= unsigned(RTC_savedtimeIn(22 downto 20));
            tm_hour <= unsigned(RTC_savedtimeIn(19 downto 14));
            tm_min  <= unsigned(RTC_savedtimeIn(13 downto 7));
            tm_sec  <= unsigned(RTC_savedtimeIn(6 downto 0));
         
         else
            
            if (tm_year(7 downto 4) > 9)  then tm_year(7 downto 4) <= (others => '0'); rtc_change <= '1'; end if;    
            if (tm_year(3 downto 0) > 9)  then tm_year(3 downto 0) <= (others => '0'); tm_year(7 downto 4) <= tm_year(7 downto 4) + 1;  rtc_change <= '1'; end if;
            
            -- 0x12 = 18
            if (tm_mon > 18) then tm_mon <= "00001"; tm_year(3 downto 0) <= tm_year(3 downto 0) + 1; rtc_change <= '1'; end if;
            if (tm_mon(3 downto 0) > 9) then tm_mon(3 downto 0) <= (others => '0'); tm_mon(4) <= '1'; rtc_change <= '1'; end if;


            case (tm_mon) is -- 0x31 = 49, 0x30 = 48, 0x28 = 40
               when "00001" => if (tm_mday > 49) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when "00010" => if (tm_mday > 40) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when "00011" => if (tm_mday > 49) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when "00100" => if (tm_mday > 48) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when "00101" => if (tm_mday > 49) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when "00110" => if (tm_mday > 48) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when "00111" => if (tm_mday > 49) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when "01000" => if (tm_mday > 49) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when "01001" => if (tm_mday > 48) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when "10000" => if (tm_mday > 49) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when "10001" => if (tm_mday > 48) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when "10010" => if (tm_mday > 49) then tm_mday <= "000001"; tm_mon(3 downto 0) <= tm_mon(3 downto 0) + 1; rtc_change <= '1'; end if;
               when others => null;
            end case;
            if (tm_mday(3 downto 0) > 9) then tm_mday(3 downto 0) <= (others => '0'); tm_mday(5 downto 4) <= tm_mday(5 downto 4) + 1; rtc_change <= '1'; end if;

            if (tm_wday > 6) then tm_wday <= (others => '0'); rtc_change <= '1'; end if;

            -- 0x23 = 35
            if (tm_hour > 35) then tm_hour <= (others => '0'); tm_wday <= tm_wday + 1; tm_mday(3 downto 0) <= tm_mday(3 downto 0) + 1; rtc_change <= '1'; end if;
            if (tm_hour(3 downto 0) > 9) then tm_hour(3 downto 0) <= (others => '0'); tm_hour(5 downto 4) <= tm_hour(5 downto 4) + 1; rtc_change <= '1'; end if;
            
            if (tm_min(6 downto 4) > 5)  then tm_min(6 downto 4)  <= (others => '0'); tm_hour(3 downto 0) <= tm_hour(3 downto 0) + 1; rtc_change <= '1'; end if;    
            if (tm_min(3 downto 0) > 9)  then tm_min(3 downto 0)  <= (others => '0'); tm_min(6 downto 4)  <= tm_min(6 downto 4) + 1;  rtc_change <= '1'; end if;
                                                                                                                        
            if (tm_sec(6 downto 4) > 5)  then tm_sec(6 downto 4)  <= (others => '0'); tm_min(3 downto 0)  <= tm_min(3 downto 0) + 1;  rtc_change <= '1'; end if;    
            if (tm_sec(3 downto 0) > 9)  then tm_sec(3 downto 0)  <= (others => '0'); tm_sec(6 downto 4)  <= tm_sec(6 downto 4) + 1;  rtc_change <= '1'; end if;
            
            if (secondcount >= 36863999) then 
               secondcount        <= 0; 
               RTC_timestamp      <= std_logic_vector(unsigned(RTC_timestamp) + 1);
               tm_sec(3 downto 0) <= tm_sec(3 downto 0) + 1;  
               rtc_change         <= '1'; 
            elsif (diffSeconds > 0 and rtc_change = '0') then   
               diffSeconds        <= diffSeconds - 1; 
               tm_sec(3 downto 0) <= tm_sec(3 downto 0) + 1;  
               rtc_change         <= '1'; 
            end if;
   
         end if;
         
         RTC_timestampNew_1 <= RTC_timestampNew;
         if (RTC_timestampNew = '1' and RTC_timestampNew_1 = '0') then
            RTC_timestamp <= RTC_timestampIn;
         end if;
         
         -- register interface
         if (reset = '1') then
         
            RTC_COMMAND <= (others => '0');
            RTC_READ    <= (others => '0');
            index       <= 0;
            
         else
            RegBus_wren_1 <= RegBus_wren;
            RegBus_rden_1 <= RegBus_rden;
            
            if (RTC_COMMAND_written = '1') then
            
               RTC_COMMAND <= RegBus_Din;
               
               if (sleep_savestate = '0') then
            
                  if (RegBus_Din = x"10") then
                  
                     secondcount <= 0;
                     tm_year     <= x"00";
                     tm_mon      <= '0' & x"1";
                     tm_mday     <= "00" & x"1";
                     tm_wday     <= "000";
                     tm_hour     <= "00" & x"0";
                     tm_min      <= "000" & x"0";
                     tm_sec      <= "000" & x"1";
                     
                  end if;
                  
                  if (RegBus_Din = x"12" or RegBus_Din = x"14" or RegBus_Din = x"15" or RegBus_Din = x"18") then
                     index <= 0;
                  end if;
                  
               end if;
            
            end if;
            
            if (to_integer(unsigned(RegBus_Adr)) = REG_RTC_WRITE.Adr) then
            
               if (RTC_COMMAND = x"14" and sleep_savestate = '0' and RegBus_wren_1 = '0' and RegBus_wren = '1') then
               
                  case (index) is
                     when 0 => tm_year <= unsigned(RegBus_Din);
                     when 1 => tm_mon  <= unsigned(RegBus_Din(4 downto 0));
                     when 2 => tm_mday <= unsigned(RegBus_Din(5 downto 0));
                     when 3 => tm_wday <= unsigned(RegBus_Din(2 downto 0));
                     when 4 => tm_hour <= unsigned(RegBus_Din(5 downto 0));
                     when 5 => tm_min  <= unsigned(RegBus_Din(6 downto 0));
                     when 6 => tm_sec  <= unsigned(RegBus_Din(6 downto 0));
                     when others => null;
                  end case;
               
                  if (index < 6) then
                     index <= index + 1;
                  else
                     RTC_COMMAND <= x"00";
                  end if;
               
               end if;
            
               if (RTC_COMMAND = x"15" and sleep_savestate = '0' and RegBus_rden_1 = '1' and RegBus_rden = '0') then

                  if (index < 6) then
                     index <= index + 1;
                  else
                     RTC_COMMAND <= x"00";
                  end if;
               
               end if;
            
            end if;
            
            RTC_READ <= (others => '0');
            if (RTC_COMMAND = x"15") then
               case (index) is
                  when 0 => RTC_READ             <= buf_tm_year;
                  when 1 => RTC_READ(4 downto 0) <= buf_tm_mon;
                  when 2 => RTC_READ(5 downto 0) <= buf_tm_mday;
                  when 3 => RTC_READ(2 downto 0) <= buf_tm_wday;
                  when 4 => RTC_READ(5 downto 0) <= buf_tm_hour;
                  when 5 => RTC_READ(6 downto 0) <= buf_tm_min;
                  when 6 => RTC_READ(6 downto 0) <= buf_tm_sec;
                  when others => null;
               end case;
            end if;
            
         end if;

         end if;
         
      end if;
   end process;
   

end architecture;
