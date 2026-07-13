library IEEE;
use IEEE.std_logic_1164.all;  
use IEEE.numeric_std.all;   

entity gpu_bg is
   port 
   (
      clk            : in  std_logic;
      ce             : in  std_logic;
      isColor        : in  std_logic;
      
      startLine      : in  std_logic;
      lineY          : in  std_logic_vector(7 downto 0);
      
      enable         : in  std_logic;
      depth2         : in  std_logic;
      packed         : in  std_logic;
      tilemapSize    : in  std_logic;
      screenbase     : in  std_logic_vector(3 downto 0);
      scrollX        : in  std_logic_vector(7 downto 0);
      scrollY        : in  std_logic_vector(7 downto 0);
      
      useWindow      : in  std_logic := '0';
      WindowOutside  : in  std_logic := '0';
      WinX0          : in  std_logic_vector(7 downto 0) := (others => '0');
      WinY0          : in  std_logic_vector(7 downto 0) := (others => '0');
      WinX1          : in  std_logic_vector(7 downto 0) := (others => '0');
      WinY1          : in  std_logic_vector(7 downto 0) := (others => '0');

      RAM_Address    : out std_logic_vector(15 downto 0);
      RAM_Data       : in  std_logic_vector(15 downto 0);    
      RAM_valid      : in  std_logic;
      RAM_ResponseAddress   : in  std_logic_vector(15 downto 0);
      RAM_ResponseCollision : in  std_logic;
      
      tileActive     : out std_logic := '0';
      tilePalette    : out std_logic_vector(3 downto 0) := (others => '0');
      tileColor      : out std_logic_vector(3 downto 0) := (others => '0');

      -- Simulation observability. A screen-map word and the tile-pattern
      -- words are distinct reads even when their IRAM ranges overlap.
      debug_fetch_valid : out std_logic := '0';
      debug_fetch_tile  : out std_logic := '0';

      -- One event describes the complete background cell promoted into the
      -- pixel shifter: its map word, decoded attributes, and only the tile-row
      -- word(s) that can contribute pixels for that cell.
      debug_cell_valid     : out std_logic := '0';
      debug_cell_map_addr  : out std_logic_vector(15 downto 0) := (others => '0');
      debug_cell_map_value : out std_logic_vector(15 downto 0) := (others => '0');
      debug_cell_row_addr  : out std_logic_vector(15 downto 0) := (others => '0');
      debug_cell_row_value : out std_logic_vector(31 downto 0) := (others => '0');
      debug_cell_meta      : out std_logic_vector(23 downto 0) := (others => '0')
   );
end entity;

architecture arch of gpu_bg is
 
   type tfetchState is
   (
      FETCHTILE,
      FETCHCOLOR0,
      FETCHCOLOR1,
      FETCHDONE
   );
   signal fetchState : tfetchState;
   signal fetchwait  : integer range 0 to 3;
   

   signal pixelCount      : integer range 0 to 255;

   signal tilemapAddress    : std_logic_vector(15 downto 0);
   signal ColorAddress    : std_logic_vector(15 downto 0);

   signal tilemapBuf      : std_logic_vector(15 downto 0) := (others => '0');
   signal tilemapBuf_1    : std_logic_vector(15 downto 0) := (others => '0');

   signal posX            : unsigned(7 downto 0) := (others => '0');
   signal posY            : std_logic_vector(7 downto 0) := (others => '0');
   
   signal tileIndex       : std_logic_vector(9 downto 0);
   signal tileX_1         : std_logic_vector(2 downto 0);
   signal tileY           : std_logic_vector(2 downto 0);
   
   signal colorBuf        : std_logic_vector(31 downto 0) := (others => '0');
   signal colorBuf_1      : std_logic_vector(31 downto 0) := (others => '0');

   signal debug_map_addr_buf       : std_logic_vector(15 downto 0) := (others => '0');
   signal debug_map_collision_buf  : std_logic := '0';
   signal debug_row0_addr_buf      : std_logic_vector(15 downto 0) := (others => '0');
   signal debug_row0_collision_buf : std_logic := '0';
   signal debug_row1_addr_buf      : std_logic_vector(15 downto 0) := (others => '0');
   signal debug_row1_collision_buf : std_logic := '0';
   
   -- window
   signal wX0             : unsigned(7 downto 0) := (others => '0');
   signal wY0             : unsigned(7 downto 0) := (others => '0');
   signal wX1             : unsigned(7 downto 0) := (others => '0');
   signal wY1             : unsigned(7 downto 0) := (others => '0');
   signal windowAllow     : std_logic := '0';
   
   signal wxCheck         : unsigned(7 downto 0) := (others => '0');

begin 

   -- The public terminology follows WSdev's screen/tile split and ares'
   -- separate map-word and tile-data reads:
   -- https://ws.nesdev.org/w/index.php?title=Display&oldid=555
   -- https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/screen.cpp#L17-L32
   -- This is the physical fetch stream, including prefetches performed while
   -- the layer is disabled.  A completed pre-enable group can later be the
   -- first buffer promoted after enable, so omitting those reads would break
   -- end-to-end provenance for a real cell event.
   debug_fetch_valid <= '1' when fetchState /= FETCHDONE else '0';
   debug_fetch_tile  <= '1' when fetchState = FETCHCOLOR0 or fetchState = FETCHCOLOR1 else '0';

   tilemapAddress <= "00" & screenbase(2 downto 0) & posY(7 downto 3) & std_logic_vector(posX(7 downto 3)) & '0' when isColor = '0' else
                      '0' & screenbase & posY(7 downto 3) & std_logic_vector(posX(7 downto 3)) & '0'; 

   ColorAddress <=  std_logic_vector(to_unsigned(16#2000#, 16) + unsigned(tileIndex & tileY & '0'))  when depth2 = '1' and packed = '0' else
                    std_logic_vector(to_unsigned(16#4000#, 16) + unsigned(tileIndex & tileY & "00")) when depth2 = '0' and packed = '0' else
                    std_logic_vector(to_unsigned(16#2000#, 16) + unsigned(tileIndex & tileY & '0'))  when depth2 = '1' and packed = '1' else
                    std_logic_vector(to_unsigned(16#4000#, 16) + unsigned(tileIndex & tileY & "00"));

   
   RAM_Address <= tilemapAddress                   when fetchState = FETCHTILE   else
                  ColorAddress(15 downto 2) & "00" when fetchState = FETCHCOLOR0 else
                  ColorAddress(15 downto 2) & "10"; --when fetchState = FETCHCOLOR1;
   

   tileIndex <= tilemapBuf(13) & tilemapBuf(8 downto 0) when (tilemapSize = '1' and isColor = '1') else '0' & tilemapBuf(8 downto 0);
   tileY     <= std_logic_vector(to_unsigned(7, 3) - unsigned(posY(2 downto 0))) when tilemapBuf(15) = '1' else posY(2 downto 0);
   
   tileX_1   <= std_logic_vector(to_unsigned(7, 3) - posX(2 downto 0)) when tilemapBuf_1(14) = '1' else std_logic_vector(posX(2 downto 0));


   
   process (clk)
      variable cell_meta : std_logic_vector(23 downto 0);
   begin
      if rising_edge(clk) then
         -- Cell-valid is a pulse at the exact edge where the completed fetch
         -- buffer becomes the next pixel-producing buffer.
         debug_cell_valid <= '0';
      
         -- read tile
         case (fetchState) is
         
            when FETCHTILE => 
               if (fetchwait > 0) then
                  fetchwait <= fetchwait - 1;
               elsif (RAM_valid = '1') then
                  fetchState <= FETCHCOLOR0;
                  tilemapBuf <= RAM_Data;
                  debug_map_addr_buf      <= RAM_ResponseAddress;
                  debug_map_collision_buf <= RAM_ResponseCollision;
               end if;
               
            when FETCHCOLOR0 => 
               if (RAM_valid = '1') then
                  fetchState <= FETCHCOLOR1;
                  colorBuf(15 downto  0) <= RAM_Data;
                  debug_row0_addr_buf      <= RAM_ResponseAddress;
                  debug_row0_collision_buf <= RAM_ResponseCollision;
               end if;
               
            when FETCHCOLOR1 => 
               if (RAM_valid = '1') then
                  fetchState <= FETCHDONE;
                  colorBuf(31 downto 16) <= RAM_Data;
                  debug_row1_addr_buf      <= RAM_ResponseAddress;
                  debug_row1_collision_buf <= RAM_ResponseCollision;
               end if;
               
            when FETCHDONE =>
               null;
         
         end case;

      
         if (ce = '1') then
         
            tileActive <= '0';

            -- window check
            wX0 <= unsigned(WinX0);
            wX1 <= unsigned(WinX1);
            wY0 <= unsigned(WinY0);
            wY1 <= unsigned(WinY1);
            
            windowAllow <= '1';
            if ((wxCheck >= wX0 and wxCheck <= wX1) or (wxCheck >= wX1 and wxCheck <= wX0)) then -- inside
               if ((unsigned(lineY) >= wY0 and unsigned(lineY) <= wY1) or (unsigned(lineY) >= wY1 and unsigned(lineY) <= wY0)) then 
                  if (useWindow = '1' and WindowOutside = '1') then
                     windowAllow <= '0';
                  end if;
               end if;
            end if;
            
            if (wxCheck < wX0 or wxCheck > wX1 or unsigned(lineY) < wY0 or unsigned(lineY) > wY1) then -- outside
               if (useWindow = '1' and WindowOutside = '0') then
                  windowAllow <= '0';
               end if;
            end if;

            -- generate position
            if (startLine = '1' and enable = '1') then
               pixelCount     <= 0;
               wxCheck        <= to_unsigned(0, 8) - 15;
               posX           <= unsigned(scrollX) - 8; -- for prefetching
               posY           <= std_logic_vector(unsigned(lineY) + unsigned(scrollY));
            elsif (pixelCount < 250) then
               
               pixelCount <= pixelCount + 1;
               posX       <= posX + 1;
               wxCheck    <= wxCheck + 1;
               tileActive <= windowAllow;
               
               if (posX(2 downto 0) = "111") then
                  fetchState   <= FETCHTILE;
                  fetchwait    <= 3;
                  tilemapBuf_1 <= tilemapBuf;
                  colorBuf_1   <= colorBuf;
                  -- depth 2 has only 16 bit per 8 pixel
                  if (depth2 = '1' and tileY(0) = '1') then
                     colorBuf_1 <= x"0000" & colorBuf(31 downto 16);
                  end if;

                  if (enable = '1' and fetchState = FETCHDONE) then
                     debug_cell_valid     <= '1';
                     debug_cell_map_addr  <= debug_map_addr_buf;
                     debug_cell_map_value <= tilemapBuf;

                     cell_meta := (others => '0');
                     cell_meta(9 downto 0)   := tileIndex;
                     cell_meta(13 downto 10) := tilemapBuf(12 downto 9);
                     cell_meta(14)           := tilemapBuf(14);
                     cell_meta(15)           := tilemapBuf(15);
                     cell_meta(16)           := not depth2;
                     cell_meta(17)           := packed;
                     cell_meta(21)           := tilemapSize and isColor;
                     cell_meta(22)           := debug_map_collision_buf;

                     if (depth2 = '1') then
                        debug_cell_row_value(31 downto 16) <= (others => '0');
                        if (tileY(0) = '1') then
                           debug_cell_row_addr                 <= debug_row1_addr_buf;
                           debug_cell_row_value(15 downto 0)   <= colorBuf(31 downto 16);
                           -- Report the row of the word actually promoted.
                           -- posY can advance at startLine after this block was
                           -- fetched, so live tileY is not authoritative here.
                           cell_meta(20 downto 18)             := debug_row1_addr_buf(3 downto 1);
                           cell_meta(23)                       := debug_row1_collision_buf;
                        else
                           debug_cell_row_addr                 <= debug_row0_addr_buf;
                           debug_cell_row_value(15 downto 0)   <= colorBuf(15 downto 0);
                           cell_meta(20 downto 18)             := debug_row0_addr_buf(3 downto 1);
                           cell_meta(23)                       := debug_row0_collision_buf;
                        end if;
                     else
                        debug_cell_row_addr  <= debug_row0_addr_buf;
                        debug_cell_row_value <= colorBuf;
                        cell_meta(20 downto 18) := debug_row0_addr_buf(4 downto 2);
                        cell_meta(23)        := debug_row0_collision_buf or debug_row1_collision_buf;
                     end if;
                     debug_cell_meta <= cell_meta;
                  end if;
               end if;
               
            end if;
            
            -- pick data 
            tilePalette <= tilemapBuf_1(12 downto 9);
            
            if (packed = '0') then
               if (depth2 = '1') then -- 2 bit planar
                  tileColor <= "00" & colorBuf_1(15 - to_integer(unsigned(tileX_1))) & colorBuf_1(7 - to_integer(unsigned(tileX_1)));
               else  -- 4 bit planar
                  tileColor <= colorBuf_1(31 - to_integer(unsigned(tileX_1))) & colorBuf_1(23 - to_integer(unsigned(tileX_1))) & colorBuf_1(15 - to_integer(unsigned(tileX_1))) & colorBuf_1(7 - to_integer(unsigned(tileX_1)));
               end if;
            else
               if (depth2 = '1') then -- 2 bit packed
                  case (tileX_1) is
                     when "000" => tileColor <= "00" & colorBuf_1( 7 downto  6);
                     when "001" => tileColor <= "00" & colorBuf_1( 5 downto  4);
                     when "010" => tileColor <= "00" & colorBuf_1( 3 downto  2);
                     when "011" => tileColor <= "00" & colorBuf_1( 1 downto  0);
                     when "100" => tileColor <= "00" & colorBuf_1(15 downto 14);
                     when "101" => tileColor <= "00" & colorBuf_1(13 downto 12);
                     when "110" => tileColor <= "00" & colorBuf_1(11 downto 10);
                     when "111" => tileColor <= "00" & colorBuf_1( 9 downto  8);
                     when others => null;
                  end case;
               else -- 4 bit packed
                  case (tileX_1) is
                     when "000" => tileColor <= colorBuf_1( 7 downto  4);
                     when "001" => tileColor <= colorBuf_1( 3 downto  0);
                     when "010" => tileColor <= colorBuf_1(15 downto 12);
                     when "011" => tileColor <= colorBuf_1(11 downto  8);
                     when "100" => tileColor <= colorBuf_1(23 downto 20);
                     when "101" => tileColor <= colorBuf_1(19 downto 16);
                     when "110" => tileColor <= colorBuf_1(31 downto 28);
                     when "111" => tileColor <= colorBuf_1(27 downto 24);
                     when others => null;
                  end case;
               end if;     
            end if;
      
         end if;
      end if;
   end process; 
   
   

end architecture;
