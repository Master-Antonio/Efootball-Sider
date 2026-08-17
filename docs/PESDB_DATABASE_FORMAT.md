# pesdb Database Format

Record-level layout of the eFootball database tables shipped under
`common/etc/pesdb/` — the WESYS container that wraps them, and the internal
structure of `Player.bin`, `PlayerAssignment.bin`, `PlayerAppearance.bin` and
`Team.bin`.

This complements `UNREAL_ENGINE_EFOOTBALL_ARCHITECTURE.md`, which covers the
container and crypto layers but stops short of the record layouts. Everything
below is what you need to read or write a squad, a shirt number or a player
rating without going through the game.

## Provenance

Derived by differential analysis against a full player CSV export (42,369
players) and re-verified byte-for-byte against a live install. Version tested:

| | |
|---|---|
| Game | eFootball 2027, Steam build, `dt200` |
| Tables | `common/etc/pesdb/*.bin`, 48 WESYS-wrapped files |
| Corpus | 23,552 player records, 23,687 assignment records, 981 teams |

Every count quoted in this document is reproducible from those files. Where a
claim held for only part of the corpus, the exact ratio is given rather than
rounded to "always".

---

## 1. The WESYS container

Database tables are wrapped in a 16-byte-header container. Since game version
5.0.0 the payload is XOR-stream encrypted *before* zlib compression, so the
zlib magic is not visible in a hex dump of a shipped file.

### 1.1 Header layout (16 bytes)

| Offset | Type | Meaning |
|---|---|---|
| `0x00` | u8 | Flag. `0xFF` on every shipped table. |
| `0x01` | u8 | Flag. **The low nibble selects the key constants.** |
| `0x02` | u8 | Flag. Bit 0 = payload present. Only two values occur: `0x83` (normal table) and `0x02` (empty table). |
| `0x03`–`0x07` | char[5] | `WESYS` magic |
| `0x08`–`0x0B` | u32 LE | Compressed payload size (= file size − 16) |
| `0x0C`–`0x0F` | u32 LE | Uncompressed size |

The magic starts at offset 3, not 0 — a `memcmp` against the start of the file
will never match.

**The size fields at `0x08`–`0x0F` are not just bookkeeping; they are part of
the key.** See below.

Nine tables in `pesdb/` are exactly 16 bytes long with `comp = orig = 0` and
flag byte 2 = `0x02` (`Weather.bin`, `CoachTactics.bin`, `PlayerDeleteList.bin`,
`Combination.bin`, …). These are empty tables, not corrupt files — decode them
as a zero-length payload rather than letting zlib raise.

### 1.2 Keystream

A 32-bit-word XOR stream from an xorshift128 variant. The state is
`(x, y, z, w)`:

- `x, y, z` are three constants chosen by the header nibble at `0x01`.
- `w` is **seeded per file** from the two header size fields.

```
w = ((orig_size << 16) | comp_size) & 0xFFFFFFFF

per word:
    t = (x ^ (x << 11)) & 0xFFFFFFFF
    x, y, z, prev = y, z, w, w
    w = (prev ^ (((prev >> 11) ^ t) >> 8) ^ t) & 0xFFFFFFFF
    payload_word ^= w
```

Key constants, extracted from `eFootball.exe`:

| Nibble | x | y | z |
|:---:|---|---|---|
| 1 | `0x168EA000` | `0x2E2AA6F2` | `0x0CC8DCD3` |
| 2 | `0xED5B2960` | `0x4A523B4E` | `0xF3A31BAD` |

Every table in the tested build uses nibble 2 (flag bytes `FF 22 83`).

Two details that are easy to miss:

- **The trailing 1–3 bytes of the payload are left in plaintext.** The cipher
  advances a whole 32-bit word at a time and simply stops; it does not pad. A
  decoder that masks the tail will corrupt the last bytes of the zlib stream.
  This is also the cheapest way to confirm the cipher is word-oriented rather
  than byte-oriented.
- **`w` depends on the file**, so there is no fixed four-word seed that decrypts
  everything. Concretely, in the tested build:

  | File | comp | orig | initial `w` |
  |---|---|---|---|
  | `Player.bin` | 2,381,837 | 9,420,800 | `0xC024580D` |
  | `Team.bin` | 106,119 | 1,569,600 | `0xF3419E87` |
  | `PlayerAssignment.bin` | 199,352 | 568,488 | `0xACAB0AB8` |

  This also means **you cannot re-encrypt in place**. Recompressing changes
  `comp_size`, which changes the seed, so a writer must compress first, read the
  final size, and only then generate the keystream.

The game is not consistent about its compression level: across the 39 non-empty
tables, 37 payloads start `78 01` (level 1) and 2 start `78 da` (level 9). Since
the level changes `comp_size` and therefore the seed, a writer should pick one
and derive the seed from what it actually produced, not from the original
header.

With those constants, all 39 non-empty tables in `pesdb/` decrypt and
round-trip (`unpack → pack → unpack` reproduces the original bytes).

### 1.3 Divergence from the current `rust_sider/src/crypto.rs`

The implementation in `crypto.rs` does not match the above, in three ways:

1. It picks the key from `data[0]`, matching `0x20` / `0x21`. Shipped tables
   have `data[0] == 0xFF`, so every real file falls through to the `_ =>`
   default arm. The actual selector is the **low nibble of `data[1]`** (`0x22`
   → nibble 2).
2. It uses a fixed fourth seed word. The real `w` is derived per file from the
   header size fields, so no constant can work across tables.
3. The step differs. `crypto.rs` computes
   `w = (w ^ (w >> 19)) ^ (t ^ (t >> 8))`; the game computes
   `w = w ^ (((w >> 11) ^ t) >> 8) ^ t`, where the `>> 8` applies to the
   combined `(w >> 11) ^ t` rather than to `t` alone.

Reproduction on a real `PlayerAssignment.bin` (header `FF 22 83`):

```
crypto.rs keystream   -> payload starts 3c d7 c0 43   zlib: incorrect header check
verified keystream    -> payload starts 78 da 54 9d   zlib: OK, 568,488 bytes
                                        ^^^^^ zlib magic
```

`test_xorshift_deterministic_keystream` passes because it only asserts that the
generator is deterministic, never that its output decrypts a real file. A test
that decompresses a known table and checks the result length against the header's
`orig_size` field would catch this.

### 1.4 Locating the constants after a key rotation

Search the `.xcode` section for the immediate compare against the magic
(`sub ecx, 59534557h`) to find the header-validation function, then walk back to
its caller — that is the decryption loop, and the constants are the immediates
following the nibble fetch. In the tested build this lands near VA
`0x144A05225`. The same route works whenever Konami rotates the keys.

---

## 2. Player.bin

Fixed **400 bytes per record**, no header, no index. `9,420,800 / 400 = 23,552`
records in the tested build.

| Offset | Size | Meaning |
|---|---|---|
| 0–7 | u64 LE | Native PID — Konami's internal index |
| 8–15 | u64 LE | **External PID** — the community-facing ID, and the key every other table references |
| 16–87 | — | Flags and bit-packed attributes |
| 88–392 | char[61] × 5 | Name region: 5 NUL-terminated UTF-8 fields, 61 bytes each |

Two properties matter for tooling:

- **The file is sorted strictly ascending by external PID (bytes 8–15), and the
  game binary-searches it.** If you insert a record you must re-sort the whole
  table, or lookups will silently miss.
- The name region is *inside* the 400-byte record, so records are still fixed
  stride despite carrying variable-length text.

Attributes are bit-packed and not byte-aligned; bit offsets are relative to the
start of the record. Summary of the decoded fields:

| Group | Count | Location | Verification |
|---|:---:|---|---|
| Abilities | 26 | bits 368–556, 6 bits each, stored value + 40 | full-CSV correlation r = 0.95–0.997 |
| Player skills | 65 | bits 223–680, 1 bit each | 42,369 players, zero false pos/neg per skill |
| AI playing styles | 7 | bits 614–680 | full-CSV purity scan |
| Playing style (attacking) | 22 | bit 372, 8 bits | 42,369 players, 100% |
| Playing style (defending) | 8 | bit 440, 6 bits, id = raw × 4 | 42,369 players, 100% |
| Nationality | 192 | bytes 41–42, u16 & 0x3FF | 42,369 players, 0 unknown IDs |
| Position | 14 | bit 556, 4 bits | full CSV |
| Height / Weight / Age | 3 | bits 248 (8) / 280 (7) / 536 | 42,369 players, 100% |
| Preferred foot / weak-foot usage / accuracy | 3 | bits 654 / 478 / 578 | full CSV |
| Position aptitude | 12 × 2 bits | bits 576–599, plus LB at 318 and CMF at 510 | primary slot always reads 2 |
| Form | 3 levels | byte 72 bits 6–7 | 42,369 players, 100% |
| Injury resistance | 3 levels | byte 67 bits 6 and 7 | 42,369 players, 100% |

Ability values are stored with a −40 bias in 6 bits: stored 63 displays as 103,
above the in-game cap of 99.

Note the two aptitude fields that sit outside the contiguous 576–599 block
(LB at bit 318, CMF at bit 510). Assuming a clean 12 × 2-bit run is the single
most common decoding mistake here.

---

## 3. PlayerAssignment.bin

Squad membership: which player is in which team, wearing which number, holding
which role. Fixed **24 bytes per record**; 23,687 records covering 787 teams.

| Offset | Type | Meaning |
|---|---|---|
| 0–3 | u32 LE | Record ID. Unique across the file (23,687/23,687) but **not a row number** — not contiguous, not monotonic, and not consecutive within a team. Only 19,531/23,686 records are the previous ID + 1. |
| 4–7 | — | Always 0 |
| 8–15 | u64 LE | **Player external PID**, referencing `Player.bin` bytes 8–15 |
| 16–19 | u32 LE | **Team ID** |
| 20 | u8 | Shirt number, 0-based — displayed number is byte 20 + 1 |
| 21 | u8 | Intra-team sort key = index × 4 |
| 22 | u8 | 6-bit role mask |
| 23 | — | Always 0 |

### 3.1 Invariants

Verified across the whole file:

| Invariant | Result |
|---|---|
| Sorted non-decreasing by team ID | 23,686/23,686 adjacent pairs |
| Each team occupies one contiguous block | 787/787 |
| Squad size between 11 and 40 | min 11, max 40 |
| Shirt number unique within a team | 787/787 teams, zero collisions |
| Byte 21 = index × 4 | 23,677/23,687 |
| Each role bit held by exactly one player per team | 4,722/4,722 (787 teams × 6 bits) |
| Bytes 4–7 and byte 23 zero | 23,687/23,687 |

The byte-21 exception is a single team (ID 199) that uses a different spacing.
It is still strictly increasing within the block, so treat byte 21 as "strictly
increasing sort key, usually ×4" rather than a computable index.

**Team ID is u32, not u16.** Reading it as u16 works for most of the file and
then quietly breaks: 24 African national teams have IDs ≥ 81,952, which truncate
to wrong values. National teams occupy the low range (Ireland 1, England 5,
Portugal 6), clubs follow (Arsenal 101, Benfica 191).

### 3.2 Role mask (byte 22)

Six bits, each held by exactly one player per team. Meanings were recovered by
ranking each bit-holder against their own squad by percentile:

| Bit | Role | Evidence |
|:---:|---|---|
| 5 | Captain | Highest overall in squad (0.17) and oldest (0.19); any position |
| 4 | Penalty taker | Top 14% finishing, worst defensive awareness in squad (0.65); usually the 9 or 10 |
| 0–3 | Set-piece takers | Top 12–15% set-piece taking and curl; usually the 10 |

Bits 0–3 are statistically indistinguishable from each other, so which one is
the left corner versus the free kick is still open. Name them by index.

### 3.3 The same player can be in several teams

971 PIDs appear 2–4 times across the file (club plus national team). The game
handles this normally, so adding a player to a squad does **not** require
removing them from their current one.

---

## 4. PlayerAppearance.bin

Body and appearance data. Fixed **64 bytes per record**, keyed by external PID
in bytes 0–7, sorted strictly ascending by that PID. Roughly 107 decoded fields
covering build, face, hair and kit-fit parameters.

Not every player has a record — the table is sparse relative to `Player.bin`.

---

## 5. Team.bin

Fixed **1,600 bytes per record**; 981 records. Team ID is u32 LE at offset 12,
unique and strictly ascending.

The 981 teams here exceed the 787 that actually have squads in
`PlayerAssignment.bin`; the remainder are defined but unpopulated.

---

## 6. Identifying a table by content

Filenames extracted from the game are not reliable, and there is no magic number
after the WESYS layer is stripped. All three player tables can be told apart
from their bytes alone:

| Table | Stride | Test |
|---|:---:|---|
| `Player` | 400 B | external PID (bytes 8–15) strictly ascending |
| `PlayerAssignment` | 24 B | bytes 4–7 all zero **and** byte 23 all zero **and** team ID (u32 @ 16) non-decreasing |
| `PlayerAppearance` | 64 B | PID (bytes 0–7) strictly ascending |

Two traps:

- `PlayerAppearance.bin` is also a multiple of 24 (2,410,752 = 24 × 100,448), so
  it must be tested *after* `PlayerAssignment`, or it will match the wrong rule.
- `TacticsFormation.bin` passes both the 24-byte stride and the monotonic-u32
  test. The bytes 4–7 zero check is what excludes it.

Tested against all 53 `.bin` files in `pesdb/`: exactly the three intended
tables match, the other 50 return no match.

---

## 7. Card IDs

External PIDs are 64-bit. Base cards have small IDs — 19,851 of 23,552 are
below 2^24 — while variant cards (special editions, Featured, Epic) carry a
high-bit prefix.

**Do not try to recover a base card from a variant by masking off the high
bits.** The rule looks convincing on a small sample and does not hold: only
1,135 of 3,701 variants (30.7%) map back correctly, and widening the mask past
18 bits stops changing the result, so it is not a matter of picking the right
width. Identify base cards by `PID < 2^24` combined with a name match and an
existence check against `Player.bin`.

---

## 8. Editing squads safely

The reason this is worth stating: whole-squad replacement looks like it should
require restructuring the file, and it does not.

**Every invariant in section 3.1 is a property of the slot, not of the player
occupying it.**

| Invariant | Under whole-squad replacement |
|---|---|
| File sorted by team ID | bytes 16–19 untouched → holds |
| Contiguous block, 11–40 players | no records added or removed → holds |
| Shirt number unique in team | already unique, inherited by the incoming player → holds |
| Intra-team sort key | untouched → holds |
| Role mask, one holder per bit | already satisfied, inherited → holds |
| Unique record ID | untouched → holds |

So replacing an entire squad means **writing a new PID into bytes 8–15 of each
of that team's records, and nothing else** — 320 bytes for a 40-player squad. No
relocation, no re-sort, no renumbering. Confirmed on live files: a byte-level
diff after replacing a full squad touches only the PID field, and a full-file
consistency check across all 787 teams reports no errors afterwards.

Single transfers are the same operation on one record.

### The one way to corrupt the save

**Dangling references.** Writing a PID that does not exist in `Player.bin`
leaves the game resolving a player who is not there. This constraint is strict
in shipped data — all 22,697 distinct assignment PIDs resolve against
`Player.bin`, a 100% hit rate — so it is worth enforcing as a hard precondition
rather than a warning.

### What genuinely does require restructuring

Changing a team's *headcount* (say 39 → 40 players). That inserts or removes a
record, which shifts every subsequent team's block, and the role mask has to be
handed over if the departing player held a bit. Inserting into `Player.bin` is
the same story plus a full re-sort, because of the binary search noted in
section 2.

---

## 9. Reference implementation

An independent GPL-compatible Python implementation of everything above,
including the WESYS codec and a squad editor built on section 8:

https://github.com/Giggitycountless/efootball-player-tool

Relevant modules: `wesys.py` (container codec, ~140 lines, stdlib only),
`efootball_core.py` (record layouts and bit maps), `efootball_squad.py` (squad
operations with the dangling-reference check). 83 regression tests cover the
layouts and invariants documented here.
