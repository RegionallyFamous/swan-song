-- Modified for Swan Song by Regionally Famous on 2026-07-14.
-- See UPSTREAMS.md and LICENSING.md for provenance and licensing details.

library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

entity swanbios is
   port
   (
      clk         : in std_logic;
      address     : in std_logic_vector(10 downto 0);
      data        : out std_logic_vector(15 downto 0);
      word_width         : in std_logic := '0';
      protect_owner_area : in std_logic := '1'
   );
end entity;

architecture arch of swanbios is

   -- BEGIN GENERATED SWANSONG OPEN IPL V3
   subtype t_boot_word is std_logic_vector(15 downto 0);
   type t_rom is array(0 to 2047) of t_boot_word;
   constant OPEN_IPL_WORDS : t_rom :=
   (
      1920 => x"31FA",
      1921 => x"8EC0",
      1922 => x"8ED8",
      1923 => x"8EC0",
      1924 => x"BCD0",
      1925 => x"2000",
      1926 => x"01B0",
      1927 => x"14E6",
      1928 => x"9EB0",
      1929 => x"16E6",
      1930 => x"9BB0",
      1931 => x"17E6",
      1932 => x"40B0",
      1933 => x"B5E6",
      1934 => x"30B0",
      1935 => x"BCE6",
      1936 => x"01B0",
      1937 => x"BDE6",
      1938 => x"40B0",
      1939 => x"BEE6",
      1940 => x"80B0",
      1941 => x"BEE6",
      1942 => x"06C6",
      1943 => x"0400",
      1944 => x"C6B0",
      1945 => x"0106",
      1946 => x"8104",
      1947 => x"06C6",
      1948 => x"0402",
      1949 => x"C6E6",
      1950 => x"0306",
      1951 => x"A004",
      1952 => x"06C6",
      1953 => x"0404",
      1954 => x"C6EA",
      1955 => x"0506",
      1956 => x"0004",
      1957 => x"06C6",
      1958 => x"0406",
      1959 => x"C600",
      1960 => x"0706",
      1961 => x"FF04",
      1962 => x"06C6",
      1963 => x"0408",
      1964 => x"B9FF",
      1965 => x"0000",
      1966 => x"01BA",
      1967 => x"BB00",
      1968 => x"0040",
      1969 => x"00BD",
      1970 => x"BE00",
      1971 => x"023D",
      1972 => x"0DBF",
      1973 => x"B804",
      1974 => x"FF00",
      1975 => x"D88E",
      1976 => x"82B8",
      1977 => x"50F0",
      1978 => x"B89D",
      1979 => x"FF81",
      1980 => x"00EA",
      1981 => x"0004",
      1982 => x"9000",
      2040 => x"00EA",
      2041 => x"F000",
      2042 => x"90FF",
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
               when 1940 => return x"06C6";
               when 1941 => return x"0400";
               when 1942 => return x"C6B0";
               when 1943 => return x"0106";
               when 1944 => return x"8104";
               when 1945 => return x"06C6";
               when 1946 => return x"0402";
               when 1947 => return x"C6E6";
               when 1948 => return x"0306";
               when 1949 => return x"A004";
               when 1950 => return x"06C6";
               when 1951 => return x"0404";
               when 1952 => return x"C6EA";
               when 1953 => return x"0506";
               when 1954 => return x"0004";
               when 1955 => return x"06C6";
               when 1956 => return x"0406";
               when 1957 => return x"C600";
               when 1958 => return x"0706";
               when 1959 => return x"FF04";
               when 1960 => return x"06C6";
               when 1961 => return x"0408";
               when 1962 => return x"B9FF";
               when 1963 => return x"0000";
               when 1964 => return x"01BA";
               when 1965 => return x"BB00";
               when 1966 => return x"0040";
               when 1967 => return x"00BD";
               when 1968 => return x"BE00";
               when 1969 => return x"023D";
               when 1970 => return x"0DBF";
               when 1971 => return x"B804";
               when 1972 => return x"FF00";
               when 1973 => return x"D88E";
               when 1974 => return x"82B8";
               when 1975 => return x"50F0";
               when 1976 => return x"B89D";
               when 1977 => return x"FF81";
               when 1978 => return x"00EA";
               when 1979 => return x"0004";
               when 1980 => return x"9000";
               when 1981 => return x"9090";
               when 1982 => return x"9090";
               when others => return stored_word;
            end case;
         when "01" =>
            case address_index is
               when 1940 => return x"06C6";
               when 1941 => return x"0400";
               when 1942 => return x"C6B0";
               when 1943 => return x"0106";
               when 1944 => return x"8504";
               when 1945 => return x"06C6";
               when 1946 => return x"0402";
               when 1947 => return x"C6E6";
               when 1948 => return x"0306";
               when 1949 => return x"A004";
               when 1950 => return x"06C6";
               when 1951 => return x"0404";
               when 1952 => return x"C6EA";
               when 1953 => return x"0506";
               when 1954 => return x"0004";
               when 1955 => return x"06C6";
               when 1956 => return x"0406";
               when 1957 => return x"C600";
               when 1958 => return x"0706";
               when 1959 => return x"FF04";
               when 1960 => return x"06C6";
               when 1961 => return x"0408";
               when 1962 => return x"B9FF";
               when 1963 => return x"0000";
               when 1964 => return x"01BA";
               when 1965 => return x"BB00";
               when 1966 => return x"0040";
               when 1967 => return x"00BD";
               when 1968 => return x"BE00";
               when 1969 => return x"023D";
               when 1970 => return x"0DBF";
               when 1971 => return x"B804";
               when 1972 => return x"FF00";
               when 1973 => return x"D88E";
               when 1974 => return x"82B8";
               when 1975 => return x"50F0";
               when 1976 => return x"B89D";
               when 1977 => return x"FF85";
               when 1978 => return x"00EA";
               when 1979 => return x"0004";
               when 1980 => return x"9000";
               when 1981 => return x"9090";
               when 1982 => return x"9090";
               when others => return stored_word;
            end case;
         when "10" =>
            return stored_word;
         when "11" =>
            case address_index is
               when 1946 => return x"8504";
               when 1979 => return x"FF85";
               when others => return stored_word;
            end case;
         when others => return (others => 'X');
      end case;
   end function;
   -- END GENERATED SWANSONG OPEN IPL V3

   signal read_address : std_logic_vector(10 downto 0) := (others => '0');
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
