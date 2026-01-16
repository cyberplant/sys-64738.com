# C64 Emulator Comparison

## Initialization Differences

### JSC64 (JavaScript)
- **CPU Reset:**
  - `a = 0x00, x = 0x00, y = 0x00`
  - `p = 0x04` (I flag only: %00000100)
  - `sp = 0xFF`
  - Writes `$0000 = 0x2F`
  - Writes `$0001 = 0x37`
  - Reads reset vector from `$FFFC`

### Python Emulator (Current)
- **CPU Reset:**
  - `a = 0x00, x = 0x00, y = 0x00`
  - `p = 0x24` (Z + I flags: %00100100) ⚠️ **DIFFERENT**
  - `sp = 0xFF`
  - **Missing:** `$0000 = 0x2F` ⚠️ **MISSING**
  - Writes `$0001 = 0x37`
  - Reads reset vector from `$FFFC`

## Key Findings

1. **Zero-page $0000:** JSC64 writes `0x2F` during reset, Python doesn't
2. **P Register:** JSC64 uses `0x04` (I flag only), Python uses `0x24` (I + Z flags)
3. **Zero-page initialization:** Both set similar values, but Python may be missing some

## Opcode Implementation

### NOP Variants (JSC64)
JSC64 has `opNOP` handler that does nothing - all NOP variants use same handler:
- Standard NOP: `0xEA`
- Undocumented NOPs: `0x1A, 0x3A, 0x5A, 0x7A, 0xDA, 0xFA`
- All consume 2 cycles, 1 byte length

### Python Implementation
- Currently implements `0xEA` (standard NOP)
- Added variants: `0x80, 0x82, 0x89, 0xC2, 0xE2` (immediate NOPs - 2 bytes)
- Added variants: `0x04, 0x44, 0x64` (zero-page NOPs - 2 bytes)
- Added variants: `0x14, 0x1C, 0x3C, 0x5C, 0x7C, 0xDC, 0xFC` (absolute indexed NOPs - 3 bytes)

## Recommendations

1. **Add `$0000` initialization:** Write `0x2F` during reset
2. **Fix P register:** Use `0x04` instead of `0x24` (I flag only, not Z flag)
3. **Verify zero-page:** Check if all necessary zero-page addresses are initialized
