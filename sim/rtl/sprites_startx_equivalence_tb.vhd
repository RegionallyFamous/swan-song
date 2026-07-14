library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

-- Two-instance proof for the deferred row-zero sprite start.  The reference
-- instance starts at logical x=0.  The second instance starts one or two
-- system cycles later but receives that beam position through startX.  Once
-- the visible 224-pixel interval begins, every functional output must match.
entity sprites_startx_equivalence_tb is
end entity;

architecture tb of sprites_startx_equivalence_tb is
   type natural_array is array(natural range <>) of natural;
   constant X_POSITIONS : natural_array(0 to 31) := (
      0, 255, 31, 32, 33, 191, 192, 193,
      7, 8, 15, 16, 23, 24, 63, 64,
      95, 96, 127, 128, 159, 160, 207, 208,
      215, 216, 223, 224, 239, 240, 247, 248
   );

   signal clk            : std_logic := '0';
   signal ce             : std_logic := '0';
   signal normal_start   : std_logic := '0';
   signal delayed_start  : std_logic := '0';
   signal delayed_startx : std_logic_vector(7 downto 0) := (others => '0');

   signal line_y         : std_logic_vector(7 downto 0) := (others => '0');
   signal enable         : std_logic := '1';
   signal depth2         : std_logic := '0';
   signal packed         : std_logic := '0';
   signal use_window     : std_logic := '1';
   signal win_x0         : std_logic_vector(7 downto 0) := x"20";
   signal win_y0         : std_logic_vector(7 downto 0) := x"00";
   signal win_x1         : std_logic_vector(7 downto 0) := x"BF";
   signal win_y1         : std_logic_vector(7 downto 0) := x"00";

   signal clear_next : std_logic := '0';
   signal load_next  : std_logic := '0';
   signal load_index : integer range 0 to 31 := 0;
   signal load_data  : std_logic_vector(31 downto 0) := (others => '0');
   signal load_color : std_logic_vector(31 downto 0) := (others => '0');

   signal normal_active   : std_logic;
   signal normal_prio     : std_logic;
   signal normal_palette  : std_logic_vector(3 downto 0);
   signal normal_color    : std_logic_vector(3 downto 0);
   signal normal_active2  : std_logic;
   signal normal_palette2 : std_logic_vector(3 downto 0);
   signal normal_color2   : std_logic_vector(3 downto 0);

   signal delayed_active   : std_logic;
   signal delayed_prio     : std_logic;
   signal delayed_palette  : std_logic_vector(3 downto 0);
   signal delayed_color    : std_logic_vector(3 downto 0);
   signal delayed_active2  : std_logic;
   signal delayed_palette2 : std_logic_vector(3 downto 0);
   signal delayed_color2   : std_logic_vector(3 downto 0);

   function descriptor(index : natural) return std_logic_vector is
      variable value : std_logic_vector(31 downto 0) := (others => '0');
   begin
      value(31 downto 24) := std_logic_vector(to_unsigned(X_POSITIONS(index), 8));
      value(23 downto 16) := x"00";
      if index mod 2 = 1 then
         value(14) := '1'; -- horizontal flip
      end if;
      if index mod 3 = 0 then
         value(13) := '1'; -- Screen 2 priority
      end if;
      if index mod 4 < 2 then
         value(12) := '1'; -- inverse window region selection
      end if;
      value(11 downto 9) := std_logic_vector(to_unsigned(index mod 8, 3));
      value(8 downto 0) := std_logic_vector(to_unsigned(index, 9));
      return value;
   end function;

   function color_row(index : natural) return std_logic_vector is
      variable value : std_logic_vector(31 downto 0) := (others => '0');
   begin
      -- Four non-symmetric planes make horizontal-flip and packed/planar
      -- indexing observable.  Every loaded row is distinct.
      value(7 downto 0) := std_logic_vector(
         rotate_right(to_unsigned(16#81#, 8), index mod 8)
      );
      value(15 downto 8) := std_logic_vector(
         rotate_right(to_unsigned(16#42#, 8), (index + 1) mod 8)
      );
      value(23 downto 16) := std_logic_vector(
         rotate_right(to_unsigned(16#24#, 8), (index + 3) mod 8)
      );
      value(31 downto 24) := std_logic_vector(
         rotate_right(to_unsigned(16#18#, 8), (index + 5) mod 8)
      );
      return value;
   end function;
begin
   clk <= not clk after 5 ns;

   normal : entity work.sprites
      port map (
         clk => clk,
         ce => ce,
         startLine => normal_start,
         startX => (others => '0'),
         lineY => line_y,
         enable => enable,
         depth2 => depth2,
         packed => packed,
         useWindow => use_window,
         WinX0 => win_x0,
         WinY0 => win_y0,
         WinX1 => win_x1,
         WinY1 => win_y1,
         clearNext => clear_next,
         loadNext => load_next,
         loadIndex => load_index,
         loadData => load_data,
         loadColor => load_color,
         tileActive => normal_active,
         tilePrio => normal_prio,
         tilePalette => normal_palette,
         tileColor => normal_color,
         tileActive2 => normal_active2,
         tilePalette2 => normal_palette2,
         tileColor2 => normal_color2
      );

   delayed : entity work.sprites
      port map (
         clk => clk,
         ce => ce,
         startLine => delayed_start,
         startX => delayed_startx,
         lineY => line_y,
         enable => enable,
         depth2 => depth2,
         packed => packed,
         useWindow => use_window,
         WinX0 => win_x0,
         WinY0 => win_y0,
         WinX1 => win_x1,
         WinY1 => win_y1,
         clearNext => clear_next,
         loadNext => load_next,
         loadIndex => load_index,
         loadData => load_data,
         loadColor => load_color,
         tileActive => delayed_active,
         tilePrio => delayed_prio,
         tilePalette => delayed_palette,
         tileColor => delayed_color,
         tileActive2 => delayed_active2,
         tilePalette2 => delayed_palette2,
         tileColor2 => delayed_color2
      );

   stimulus : process
      procedure tick is
      begin
         wait until rising_edge(clk);
         wait for 1 ns;
      end procedure;

      procedure load_fixture is
      begin
         ce <= '0';
         normal_start <= '0';
         delayed_start <= '0';
         load_next <= '0';
         clear_next <= '1';
         tick;
         clear_next <= '0';
         for index in 0 to 31 loop
            load_index <= index;
            load_data <= descriptor(index);
            load_color <= color_row(index);
            load_next <= '1';
            tick;
         end loop;
         load_next <= '0';
         tick;
      end procedure;

      procedure compare_visible(visible_x : natural; delay : natural) is
      begin
         assert normal_active = delayed_active
            report "tileActive mismatch delay=" & integer'image(delay) &
                   " x=" & integer'image(visible_x) severity failure;
         assert normal_prio = delayed_prio
            report "tilePrio mismatch delay=" & integer'image(delay) &
                   " x=" & integer'image(visible_x) severity failure;
         assert normal_palette = delayed_palette
            report "tilePalette mismatch delay=" & integer'image(delay) &
                   " x=" & integer'image(visible_x) severity failure;
         assert normal_color = delayed_color
            report "tileColor mismatch delay=" & integer'image(delay) &
                   " x=" & integer'image(visible_x) severity failure;
         assert normal_active2 = delayed_active2
            report "tileActive2 mismatch delay=" & integer'image(delay) &
                   " x=" & integer'image(visible_x) severity failure;
         assert normal_palette2 = delayed_palette2
            report "tilePalette2 mismatch delay=" & integer'image(delay) &
                   " x=" & integer'image(visible_x) severity failure;
         assert normal_color2 = delayed_color2
            report "tileColor2 mismatch delay=" & integer'image(delay) &
                   " x=" & integer'image(visible_x) severity failure;
      end procedure;

      procedure run_case(
         delay          : natural;
         packed_mode    : std_logic;
         depth2_mode    : std_logic;
         reverse_window : boolean
      ) is
         variable active_count    : natural := 0;
         variable active2_count   : natural := 0;
         variable high_prio_seen  : boolean := false;
         variable low_prio_seen   : boolean := false;
         variable palette_changed : boolean := false;
         variable color_changed   : boolean := false;
         variable last_palette    : std_logic_vector(3 downto 0) := (others => '0');
         variable last_color      : std_logic_vector(3 downto 0) := (others => '0');
      begin
         assert delay = 1 or delay = 2 severity failure;
         packed <= packed_mode;
         depth2 <= depth2_mode;
         if reverse_window then
            win_x0 <= x"BF";
            win_x1 <= x"20";
         else
            win_x0 <= x"20";
            win_x1 <= x"BF";
         end if;
         delayed_startx <= std_logic_vector(to_unsigned(delay, 8));
         load_fixture;

         -- The GPU begins publishing pixels at xCount=20.  Run through
         -- xCount=243 inclusive and compare the corresponding 224 visible
         -- samples after each CE edge.  The three idle clocks reproduce the
         -- fastest production CE cadence.
         for system_x in 0 to 243 loop
            if system_x = 0 then
               normal_start <= '1';
            else
               normal_start <= '0';
            end if;
            if system_x = delay then
               delayed_start <= '1';
            else
               delayed_start <= '0';
            end if;
            ce <= '1';
            tick;
            ce <= '0';
            normal_start <= '0';
            delayed_start <= '0';

            if system_x >= 20 then
               compare_visible(system_x - 20, delay);
               if normal_active = '1' then
                  active_count := active_count + 1;
                  if normal_prio = '1' then
                     high_prio_seen := true;
                  else
                     low_prio_seen := true;
                  end if;
                  if normal_palette /= last_palette then
                     palette_changed := true;
                  end if;
                  if normal_color /= last_color then
                     color_changed := true;
                  end if;
                  last_palette := normal_palette;
                  last_color := normal_color;
               end if;
               if normal_active2 = '1' then
                  active2_count := active2_count + 1;
               end if;
            end if;

            for idle in 1 to 3 loop
               tick;
               if system_x >= 20 then
                  -- Tile outputs must remain equivalent and stable between CE
                  -- pulses as they do in the production GPU.
                  compare_visible(system_x - 20, delay);
               end if;
            end loop;
         end loop;

         assert active_count > 0 and active_count < 224
            report "fixture did not exercise both active and window-clipped pixels"
            severity failure;
         assert active2_count > 0
            report "fixture did not exercise the high-priority sprite path"
            severity failure;
         assert high_prio_seen and low_prio_seen
            report "fixture did not expose both tilePrio values" severity failure;
         assert palette_changed and color_changed
            report "fixture did not expose varied palette/color outputs" severity failure;
      end procedure;
   begin
      -- Planar and packed rows, normal and reversed window bounds, alternating
      -- horizontal flips, both priority paths, and boundary-adjacent X values
      -- are all present in the common 32-row fixture.
      run_case(1, '0', '0', false);
      run_case(2, '1', '0', true);
      run_case(2, '0', '1', false);

      report "PASS sprites startX offset 1/2 equivalence for all 224 visible outputs, planar/packed/depth2, flips, priorities, and window boundaries"
         severity note;
      std.env.stop;
      wait;
   end process;
end architecture;
