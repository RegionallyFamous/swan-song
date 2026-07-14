library IEEE;
use IEEE.std_logic_1164.all;

-- Central WonderSwan SoC control-register slice.  This is the sole production
-- owner of $A0 and the Color-only $60 register; consumers receive normalized
-- state rather than independently decoding or storing either port.
--
-- Reference contract:
--   WSdev SoC revision 641 ($A0 and Color-only $60):
--   https://ws.nesdev.org/w/index.php?title=SoC&oldid=641
--   ares 449b9371 CPU/system I/O and serialization:
--   https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cpu/io.cpp#L31-L36
--   https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/system/io.cpp#L1-L46
--   Mesen2 b9fa69dd memory-manager I/O and serialization:
--   https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsMemoryManager.cpp#L249-L266
--   https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsMemoryManager.cpp#L314-L347
--
-- Mesen2 retains undocumented $60 bit 2 in its raw SystemControl2 byte, but
-- does not attach behavior to it.  WSdev and ares expose only mask EBh.  This
-- block follows the documented/functional mask and therefore reads bit 2 as
-- zero.  On a monochrome model, $60 is deliberately reported as unmapped so
-- the eventual bus owner can return its chosen open-bus value (Mesen2 uses
-- 90h) without that policy leaking into this register block.
entity soc_control is
   port
   (
      clk                    : in  std_logic;
      reset                  : in  std_logic;
      is_color_model         : in  std_logic;

      reg_addr               : in  std_logic_vector(7 downto 0);
      reg_write              : in  std_logic;
      reg_data_in            : in  std_logic_vector(7 downto 0);
      reg_data_out           : out std_logic_vector(7 downto 0);
      reg_read_mapped        : out std_logic;
      reg_write_mapped       : out std_logic;
      port_60_mapped         : out std_logic;

      -- Exact-state restore is intentionally stronger than normal software
      -- writes: it may clear the otherwise set-only boot-ROM lockout.  The
      -- low byte stores writable $A0 bits and the high byte stores $60.
      state_load             : in  std_logic := '0';
      state_data_in          : in  std_logic_vector(15 downto 0) := (others => '0');
      state_data_out         : out std_logic_vector(15 downto 0);

      boot_rom_locked        : out std_logic;
      cartridge_rom_word     : out std_logic;
      cartridge_rom_slow     : out std_logic;
      -- Video exports are effective, not merely the raw $60 bits.  Color is
      -- required for 4bpp and both Color+4bpp are required for packed 4bpp.
      -- video_mode is canonical: 000 mono, 100 Color 2bpp,
      -- 110 Color 4bpp planar, 111 Color 4bpp packed.
      color_enabled          : out std_logic;
      video_mode             : out std_logic_vector(2 downto 0);
      video_4bpp             : out std_logic;
      video_4bpp_packed      : out std_logic;
      cartridge_sram_slow    : out std_logic;
      cartridge_io_slow      : out std_logic;
      cartridge_clock_fast   : out std_logic
   );
end entity;

architecture rtl of soc_control is
   constant A0_WRITE_MASK   : std_logic_vector(7 downto 0) := x"0D";
   constant DISP_MODE_MASK  : std_logic_vector(7 downto 0) := x"EB";

   signal boot_rom_locked_reg : std_logic := '0';
   signal rom_word_reg        : std_logic := '0';
   signal rom_slow_reg        : std_logic := '0';
   signal disp_mode_reg       : std_logic_vector(7 downto 0) := (others => '0');

   signal a0_read             : std_logic_vector(7 downto 0);
   signal a0_state            : std_logic_vector(7 downto 0);
begin
   -- Bit 7 is the fixed cartridge-bus self-test result.  Bit 1 identifies the
   -- physical SoC model and is never writable through $A0.
   a0_read  <= '1' & "000" & rom_slow_reg & rom_word_reg &
               is_color_model & boot_rom_locked_reg;
   a0_state <= "0000" & rom_slow_reg & rom_word_reg & '0' &
               boot_rom_locked_reg;

   port_60_mapped <= is_color_model;

   process (all)
   begin
      reg_data_out     <= (others => '0');
      reg_read_mapped  <= '0';
      reg_write_mapped <= '0';

      if (reg_addr = x"A0") then
         reg_data_out     <= a0_read;
         reg_read_mapped  <= '1';
         reg_write_mapped <= '1';
      elsif (reg_addr = x"60" and is_color_model = '1') then
         reg_data_out     <= disp_mode_reg;
         reg_read_mapped  <= '1';
         reg_write_mapped <= '1';
      end if;
   end process;

   process (clk)
      variable masked_a0 : std_logic_vector(7 downto 0);
      variable masked_60 : std_logic_vector(7 downto 0);
   begin
      if rising_edge(clk) then
         if (reset = '1') then
            boot_rom_locked_reg <= '0';
            rom_word_reg        <= '0';
            rom_slow_reg        <= '0';
            disp_mode_reg       <= (others => '0');
         elsif (state_load = '1') then
            masked_a0 := state_data_in(7 downto 0) and A0_WRITE_MASK;
            boot_rom_locked_reg <= masked_a0(0);
            rom_word_reg        <= masked_a0(2);
            rom_slow_reg        <= masked_a0(3);
            if (is_color_model = '1') then
               disp_mode_reg <= state_data_in(15 downto 8) and DISP_MODE_MASK;
            else
               disp_mode_reg <= (others => '0');
            end if;
         else
            if (reg_write = '1' and reg_addr = x"A0") then
               masked_a0 := reg_data_in and A0_WRITE_MASK;
               -- Boot-ROM lockout is one-way for software.  ROM width and
               -- wait-state selects are ordinary replacement fields.
               boot_rom_locked_reg <= boot_rom_locked_reg or masked_a0(0);
               rom_word_reg        <= masked_a0(2);
               rom_slow_reg        <= masked_a0(3);
            end if;

            if (is_color_model = '0') then
               -- Model selection is boot-stable in production.  Clearing the
               -- Color-only byte here also makes model changes deterministic
               -- in focused simulation and prevents hidden mono state.
               disp_mode_reg <= (others => '0');
            elsif (reg_write = '1' and reg_addr = x"60") then
               masked_60 := reg_data_in and DISP_MODE_MASK;
               -- Every implemented $60 bit is replace-on-write, not sticky.
               disp_mode_reg <= masked_60;
            end if;
         end if;
      end if;
   end process;

   state_data_out <= disp_mode_reg & a0_state;

   boot_rom_locked      <= boot_rom_locked_reg;
   cartridge_rom_word   <= rom_word_reg;
   cartridge_rom_slow   <= rom_slow_reg;
   color_enabled        <= is_color_model and disp_mode_reg(7);
   video_4bpp           <= is_color_model and disp_mode_reg(7) and disp_mode_reg(6);
   video_4bpp_packed    <= is_color_model and disp_mode_reg(7) and
                           disp_mode_reg(6) and disp_mode_reg(5);
   video_mode           <= "000" when is_color_model = '0' or disp_mode_reg(7) = '0' else
                           "100" when disp_mode_reg(6) = '0' else
                           "110" when disp_mode_reg(5) = '0' else
                           "111";
   cartridge_sram_slow  <= disp_mode_reg(1) when is_color_model = '1' else '0';
   cartridge_io_slow    <= disp_mode_reg(3) when is_color_model = '1' else '0';
   cartridge_clock_fast <= disp_mode_reg(0) when is_color_model = '1' else '0';
end architecture;
