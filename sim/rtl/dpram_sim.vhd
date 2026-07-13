-- SPDX-License-Identifier: GPL-2.0-only
-- Simulation/synthesis model used only by the open-source regression flow.
-- It replaces Intel's altsyncram primitive; the production Quartus build keeps
-- using src/fpga/core/rtl/dpram.vhd.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity dpram is
  generic (
    addr_width : integer := 8;
    data_width : integer := 8
  );
  port (
    clock_a   : in  std_logic;
    clken_a   : in  std_logic := '1';
    address_a : in  std_logic_vector(addr_width - 1 downto 0);
    data_a    : in  std_logic_vector(data_width - 1 downto 0);
    wren_a    : in  std_logic := '0';
    q_a       : out std_logic_vector(data_width - 1 downto 0);
    clock_b   : in  std_logic;
    clken_b   : in  std_logic := '1';
    address_b : in  std_logic_vector(addr_width - 1 downto 0);
    data_b    : in  std_logic_vector(data_width - 1 downto 0) := (others => '0');
    wren_b    : in  std_logic := '0';
    q_b       : out std_logic_vector(data_width - 1 downto 0)
  );
end entity;

architecture behavioral of dpram is
  type ram_type is array (0 to (2 ** addr_width) - 1)
    of std_logic_vector(data_width - 1 downto 0);
  shared variable ram : ram_type := (others => (others => '0'));
begin
  process (clock_a)
  begin
    if rising_edge(clock_a) and clken_a = '1' then
      if wren_a = '1' then
        ram(to_integer(unsigned(address_a))) := data_a;
      end if;
      q_a <= ram(to_integer(unsigned(address_a)));
    end if;
  end process;

  process (clock_b)
  begin
    if rising_edge(clock_b) and clken_b = '1' then
      if wren_b = '1' then
        ram(to_integer(unsigned(address_b))) := data_b;
      end if;
      q_b <= ram(to_integer(unsigned(address_b)));
    end if;
  end process;
end architecture;

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity dpram_dif is
  generic (
    addr_width_a  : integer := 8;
    data_width_a  : integer := 8;
    addr_width_b  : integer := 8;
    data_width_b  : integer := 8;
    mem_init_file : string := " "
  );
  port (
    clock     : in  std_logic;
    address_a : in  std_logic_vector(addr_width_a - 1 downto 0);
    data_a    : in  std_logic_vector(data_width_a - 1 downto 0) := (others => '0');
    enable_a  : in  std_logic := '1';
    wren_a    : in  std_logic := '0';
    q_a       : out std_logic_vector(data_width_a - 1 downto 0);
    cs_a      : in  std_logic := '1';
    address_b : in  std_logic_vector(addr_width_b - 1 downto 0) := (others => '0');
    data_b    : in  std_logic_vector(data_width_b - 1 downto 0) := (others => '0');
    enable_b  : in  std_logic := '1';
    wren_b    : in  std_logic := '0';
    q_b       : out std_logic_vector(data_width_b - 1 downto 0);
    cs_b      : in  std_logic := '1'
  );
end entity;

architecture unsupported of dpram_dif is
begin
  -- The WonderSwan system hierarchy currently instantiates only dpram. Keep
  -- this entity so future upstream merges fail at elaboration, not analysis.
  q_a <= (others => '0');
  q_b <= (others => '0');
end architecture;
