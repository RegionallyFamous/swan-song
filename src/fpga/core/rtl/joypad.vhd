-- Modified for Swan Song by Regionally Famous on 2026-07-14.
-- See UPSTREAMS.md and LICENSING.md for provenance and licensing details.

library IEEE;
use IEEE.std_logic_1164.all;  
use IEEE.numeric_std.all;     

use work.pRegisterBus.all;
use work.pReg_swan.all;

entity joypad is
   port 
   (     
      clk            : in  std_logic;
      ce             : in  std_logic;
      sleep_savestate : in  std_logic;

      IRQ_Key        : out std_logic := '0';
      
      vertical       : in  std_logic;
      
      KeyY1          : in  std_logic;
      KeyY2          : in  std_logic;
      KeyY3          : in  std_logic;
      KeyY4          : in  std_logic;
      KeyX1          : in  std_logic;
      KeyX2          : in  std_logic;
      KeyX3          : in  std_logic;
      KeyX4          : in  std_logic;
      KeyStart       : in  std_logic;
      KeyA           : in  std_logic;
      KeyB           : in  std_logic;
   
      RegBus_Din     : in  std_logic_vector(BUS_buswidth-1 downto 0);
      RegBus_Adr     : in  std_logic_vector(BUS_busadr-1 downto 0);
      RegBus_wren    : in  std_logic;
      RegBus_rst     : in  std_logic;
      RegBus_Dout    : out std_logic_vector(BUS_buswidth-1 downto 0)
   );
end entity;

architecture arch of joypad is

   -- register
   signal KEYPAD      : std_logic_vector(REG_KEYPAD.upper downto REG_KEYPAD.lower);
   signal KEYPAD_read : std_logic_vector(REG_KEYPAD.upper downto REG_KEYPAD.lower);
   signal KEYPAD_last : std_logic_vector(3 downto 0) := (others => '0');

begin 

   iREG_KEYPAD : entity work.eReg generic map ( REG_KEYPAD ) port map (clk, RegBus_Din, RegBus_Adr, RegBus_wren, RegBus_rst, RegBus_Dout, KEYPAD_read, KEYPAD);  
  
   process (all)
   begin
   
      KEYPAD_read <= '0' & KEYPAD(6 downto 4) & "0000";
      if (KEYPAD(4) = '1') then
         if (vertical = '0') then
            if (KeyY1 = '1') then KEYPAD_read(0) <= '1'; end if;
            if (KeyY2 = '1') then KEYPAD_read(1) <= '1'; end if;
            if (KeyY3 = '1') then KEYPAD_read(2) <= '1'; end if;
            if (KeyY4 = '1') then KEYPAD_read(3) <= '1'; end if;
         else
            if (KeyX4 = '1') then KEYPAD_read(0) <= '1'; end if;
            if (KeyX1 = '1') then KEYPAD_read(1) <= '1'; end if;
            if (KeyX2 = '1') then KEYPAD_read(2) <= '1'; end if;
            if (KeyX3 = '1') then KEYPAD_read(3) <= '1'; end if;
         end if;
      end if;

      if (KEYPAD(5) = '1') then
         if (vertical = '0') then
            if (KeyX1 = '1') then KEYPAD_read(0) <= '1'; end if;
            if (KeyX2 = '1') then KEYPAD_read(1) <= '1'; end if;
            if (KeyX3 = '1') then KEYPAD_read(2) <= '1'; end if;
            if (KeyX4 = '1') then KEYPAD_read(3) <= '1'; end if;
         else
            if (KeyY4 = '1') then KEYPAD_read(0) <= '1'; end if;
            if (KeyY1 = '1') then KEYPAD_read(1) <= '1'; end if;
            if (KeyY2 = '1') then KEYPAD_read(2) <= '1'; end if;
            if (KeyY3 = '1') then KEYPAD_read(3) <= '1'; end if;
         end if;
      end if;

      if (KEYPAD(6) = '1') then
         if (KeyStart = '1') then KEYPAD_read(1) <= '1'; end if;
         if (KeyA     = '1') then KEYPAD_read(2) <= '1'; end if;
         if (KeyB     = '1') then KEYPAD_read(3) <= '1'; end if;
      end if;
   
   end process;

   -- Key input is edge-triggered. Hold the edge until the interrupt controller
   -- reaches its next system clock enable so a host input transition between
   -- enables cannot be lost. Changing the selected matrix can itself expose a
   -- held key and therefore produces the same rising edge as the hardware scan.
   process (clk)
   begin
      if rising_edge(clk) then
         if (RegBus_rst = '1' or sleep_savestate = '1') then
            KEYPAD_last <= KEYPAD_read(3 downto 0);
            IRQ_Key     <= '0';
         else
            if (ce = '1') then
               IRQ_Key <= '0';
            end if;
            if ((KEYPAD_read(3 downto 0) and not KEYPAD_last) /= "0000") then
               IRQ_Key <= '1';
            end if;
            KEYPAD_last <= KEYPAD_read(3 downto 0);
         end if;
      end if;
   end process;

end architecture;

