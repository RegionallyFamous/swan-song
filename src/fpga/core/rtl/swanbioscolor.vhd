-- Modified for Swan Song by Regionally Famous on 2026-07-14.
-- See UPSTREAMS.md and LICENSING.md for provenance and licensing details.

library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

entity swanbioscolor is
   port
   (
      clk         : in std_logic;
      address     : in std_logic_vector(11 downto 0);
      data        : out std_logic_vector(15 downto 0);
      word_width         : in std_logic := '0';
      protect_owner_area : in std_logic := '1'
   );
end entity;

architecture arch of swanbioscolor is

   -- BEGIN GENERATED SWANSONG OPEN IPL V3
   subtype t_boot_word is std_logic_vector(15 downto 0);
   type t_rom is array(0 to 4095) of t_boot_word;
   constant OPEN_IPL_WORDS : t_rom :=
   (
      3968 => x"31FA",
      3969 => x"8EC0",
      3970 => x"8ED8",
      3971 => x"8EC0",
      3972 => x"BCD0",
      3973 => x"2000",
      3974 => x"01B0",
      3975 => x"14E6",
      3976 => x"9EB0",
      3977 => x"16E6",
      3978 => x"9BB0",
      3979 => x"17E6",
      3980 => x"0AB0",
      3981 => x"60E6",
      3982 => x"40B0",
      3983 => x"B5E6",
      3984 => x"00B0",
      3985 => x"BCE6",
      3986 => x"13B0",
      3987 => x"BDE6",
      3988 => x"40B0",
      3989 => x"BEE6",
      3990 => x"80B0",
      3991 => x"BEE6",
      3992 => x"06C6",
      3993 => x"0400",
      3994 => x"C6B0",
      3995 => x"0106",
      3996 => x"8304",
      3997 => x"06C6",
      3998 => x"0402",
      3999 => x"C6E6",
      4000 => x"0306",
      4001 => x"A004",
      4002 => x"06C6",
      4003 => x"0404",
      4004 => x"C6EA",
      4005 => x"0506",
      4006 => x"0004",
      4007 => x"06C6",
      4008 => x"0406",
      4009 => x"C600",
      4010 => x"0706",
      4011 => x"FF04",
      4012 => x"06C6",
      4013 => x"0408",
      4014 => x"B9FF",
      4015 => x"0000",
      4016 => x"01BA",
      4017 => x"BB00",
      4018 => x"0043",
      4019 => x"00BD",
      4020 => x"BE00",
      4021 => x"0435",
      4022 => x"0BBF",
      4023 => x"B804",
      4024 => x"FE00",
      4025 => x"D88E",
      4026 => x"86B8",
      4027 => x"50F0",
      4028 => x"B89D",
      4029 => x"FF83",
      4030 => x"00EA",
      4031 => x"0004",
      4032 => x"9000",
      4088 => x"00EA",
      4089 => x"F000",
      4090 => x"90FF",
      others => x"9090"
   );
   signal rom : t_rom := OPEN_IPL_WORDS;
   attribute ramstyle : string;
   attribute ramstyle of rom : signal is "M10K";

   function open_ipl_read_word
   (
      address_index     : natural;
      stored_word       : t_boot_word;
      selected_width    : std_logic;
      selected_protect  : std_logic
   ) return t_boot_word is
      variable variant : std_logic_vector(1 downto 0);
   begin
      variant := selected_protect & selected_width;
      case variant is
         when "00" =>
            case address_index is
               when 3990 => return x"06C6";
               when 3991 => return x"0400";
               when 3992 => return x"C6B0";
               when 3993 => return x"0106";
               when 3994 => return x"8304";
               when 3995 => return x"06C6";
               when 3996 => return x"0402";
               when 3997 => return x"C6E6";
               when 3998 => return x"0306";
               when 3999 => return x"A004";
               when 4000 => return x"06C6";
               when 4001 => return x"0404";
               when 4002 => return x"C6EA";
               when 4003 => return x"0506";
               when 4004 => return x"0004";
               when 4005 => return x"06C6";
               when 4006 => return x"0406";
               when 4007 => return x"C600";
               when 4008 => return x"0706";
               when 4009 => return x"FF04";
               when 4010 => return x"06C6";
               when 4011 => return x"0408";
               when 4012 => return x"B9FF";
               when 4013 => return x"0000";
               when 4014 => return x"01BA";
               when 4015 => return x"BB00";
               when 4016 => return x"0043";
               when 4017 => return x"00BD";
               when 4018 => return x"BE00";
               when 4019 => return x"0435";
               when 4020 => return x"0BBF";
               when 4021 => return x"B804";
               when 4022 => return x"FE00";
               when 4023 => return x"D88E";
               when 4024 => return x"86B8";
               when 4025 => return x"50F0";
               when 4026 => return x"B89D";
               when 4027 => return x"FF83";
               when 4028 => return x"00EA";
               when 4029 => return x"0004";
               when 4030 => return x"9000";
               when 4031 => return x"9090";
               when 4032 => return x"9090";
               when others => return stored_word;
            end case;
         when "01" =>
            case address_index is
               when 3990 => return x"06C6";
               when 3991 => return x"0400";
               when 3992 => return x"C6B0";
               when 3993 => return x"0106";
               when 3994 => return x"8704";
               when 3995 => return x"06C6";
               when 3996 => return x"0402";
               when 3997 => return x"C6E6";
               when 3998 => return x"0306";
               when 3999 => return x"A004";
               when 4000 => return x"06C6";
               when 4001 => return x"0404";
               when 4002 => return x"C6EA";
               when 4003 => return x"0506";
               when 4004 => return x"0004";
               when 4005 => return x"06C6";
               when 4006 => return x"0406";
               when 4007 => return x"C600";
               when 4008 => return x"0706";
               when 4009 => return x"FF04";
               when 4010 => return x"06C6";
               when 4011 => return x"0408";
               when 4012 => return x"B9FF";
               when 4013 => return x"0000";
               when 4014 => return x"01BA";
               when 4015 => return x"BB00";
               when 4016 => return x"0043";
               when 4017 => return x"00BD";
               when 4018 => return x"BE00";
               when 4019 => return x"0435";
               when 4020 => return x"0BBF";
               when 4021 => return x"B804";
               when 4022 => return x"FE00";
               when 4023 => return x"D88E";
               when 4024 => return x"86B8";
               when 4025 => return x"50F0";
               when 4026 => return x"B89D";
               when 4027 => return x"FF87";
               when 4028 => return x"00EA";
               when 4029 => return x"0004";
               when 4030 => return x"9000";
               when 4031 => return x"9090";
               when 4032 => return x"9090";
               when others => return stored_word;
            end case;
         when "10" =>
            return stored_word;
         when "11" =>
            case address_index is
               when 3996 => return x"8704";
               when 4029 => return x"FF87";
               when others => return stored_word;
            end case;
         when others => return (others => 'X');
      end case;
   end function;
   -- END GENERATED SWANSONG OPEN IPL V3

   signal read_address : std_logic_vector(11 downto 0) := (others => '0');
   signal read_data    : t_boot_word := x"9090";
   
begin

   process (clk) 
   begin
      if rising_edge(clk) then
         read_address <= address;
         read_data    <= rom(to_integer(unsigned(address)));
      end if;
   end process;

   data <= open_ipl_read_word(
      to_integer(unsigned(read_address)),
      read_data,
      word_width,
      protect_owner_area
   );
end architecture;
