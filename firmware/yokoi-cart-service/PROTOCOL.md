# Yokoi Cart Service protocol v1

The service uses the WonderSwan EXT UART at 38400 baud, 8 data bits, no
parity, and one stop bit. Multi-byte integers are little-endian.

## Frame

| Offset | Size | Field |
| --- | ---: | --- |
| 0 | 2 | Magic, ASCII `YK` (`59 4B`) |
| 2 | 1 | Protocol version (`01`) |
| 3 | 1 | Sequence number |
| 4 | 1 | Command; responses set bit 7 |
| 5 | 2 | Payload length |
| 7 | n | Payload |
| 7+n | 2 | CRC-16/CCITT-FALSE over version through payload |

CRC-16 uses polynomial `0x1021`, initial `0xFFFF`, no reflection, and no final
XOR. A response payload always begins with a status byte.

## Commands

| Command | Request | Successful response data |
| --- | --- | --- |
| `01` Hello | empty | protocol, firmware `0.2.0`, model, capabilities, maximum transfer, `YOKOI` |
| `02` Cartridge info | empty | flags, model, system control, save kind, EEPROM address bits, ROM size, save size, raw 16-byte footer |
| `10` Read ROM | bank `u16`, offset `u16`, length `u8` | requested bytes |
| `11` Read SRAM | bank `u16`, offset `u16`, length `u8` | requested bytes |
| `12` Read EEPROM | address `u16`, length `u8` | requested bytes |
| `20` Write SRAM chunk | 1-128 sequential bytes | next linear position `u32`, complete `u8` |
| `21` Write EEPROM chunk | 2-128 sequential, even byte count | next linear position `u32`, complete `u8` |
| `22` Flash erase | reserved | `WRITE_LOCKED` |
| `23` Flash program | reserved | `WRITE_LOCKED` |
| `30` Prepare save write | save kind `u8`, exact size `u32`, image CRC32 `u32` | session token `u16` |
| `31` Begin save write | session token `u16` | initial position `u32` |
| `32` Cancel save write | empty | empty |

CRC32 is the standard reflected IEEE CRC-32 used by zlib: polynomial
`0xEDB88320`, initial `0xFFFFFFFF`, and final XOR `0xFFFFFFFF`.

The maximum transfer is 128 bytes. A read cannot cross a 64 KiB bank boundary.
Mapper bank values are signed-from-end values encoded as `u16`: `FFFF` is the
final bank, `FFFE` the penultimate bank, and so on. This mirrors official
cartridges of different physical sizes and supports the Bandai 2003 mapper's
full bank word.

Cartridge-info flags are: bit 0 cartridge self-test passed, bit 1 footer begins
with the expected far-jump opcode, bit 2 ROM size code is known, and bit 3 save
type is known. Save kinds are 0 none, 1 SRAM, 2 EEPROM, and 255 unknown.

Hello capability bits are `0001` read ROM, `0002` read SRAM, `0004` read
EEPROM, `0100` write SRAM, and `0200` write EEPROM.

## Status values

| Value | Meaning |
| --- | --- |
| `00` | OK |
| `01` | Bad frame CRC |
| `02` | Bad payload length |
| `03` | Unsupported command or protocol |
| `04` | Address, geometry, or image-size error |
| `05` | Write path is not armed or is permanently locked |
| `06` | Requested save-memory type is absent |
| `07` | Physical A+B confirmation is required |
| `08` | Cartridge fingerprint changed |
| `09` | Device readback verification failed |
| `0A` | Write session/chunk sequence is invalid |
| `0B` | Completed image CRC32 does not match |

## Write-session contract

Prepare validates exact save geometry and stores a fingerprint of the footer.
Begin succeeds only while A+B is physically held and the token and fingerprint
still match. Write chunks have no caller-selected address: the device advances
an internal linear position, making reordering or arbitrary writes impossible.
Every chunk is read back before the position advances. SRAM is mapped by the
declared size; EEPROM is unlocked only around a chunk and locked again before
the response. The session ends on completion or on the first inconsistency.

ROM flash commands deliberately remain locked. Retail cartridges use mask ROM;
programmable flash cartridges need board-specific identification, erase,
program, timeout, and recovery behavior rather than a generic write command.
