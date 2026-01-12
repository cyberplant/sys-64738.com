#!/usr/bin/env python3
"""
prg_decompile.py - C64 PRG/VSF decompiler (BASIC detokenizer + 6502 disassembler)

Goals:
- Zero dependencies (stdlib only)
- Useful for diffing/analysis across compilations

Examples:
  python3 tools/prg_decompile.py programs/main.prg
  python3 tools/prg_decompile.py programs/main.prg --mode basic
  python3 tools/prg_decompile.py programs/main.prg --mode disasm --start 0x1000 --length 256
  python3 tools/prg_decompile.py snapshot.vsf --mode acme > snapshot.asm
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import signal
import sys
from typing import Dict, List, Optional, Tuple


# --- BASIC v2 token table (C64) ---

TOKEN_TO_KEYWORD: Dict[int, str] = {
    0x80: "END",
    0x81: "FOR",
    0x82: "NEXT",
    0x83: "DATA",
    0x84: "INPUT#",
    0x85: "INPUT",
    0x86: "DIM",
    0x87: "READ",
    0x88: "LET",
    0x89: "GOTO",
    0x8A: "RUN",
    0x8B: "IF",
    0x8C: "RESTORE",
    0x8D: "GOSUB",
    0x8E: "RETURN",
    0x8F: "REM",
    0x90: "STOP",
    0x91: "ON",
    0x92: "WAIT",
    0x93: "LOAD",
    0x94: "SAVE",
    0x95: "VERIFY",
    0x96: "DEF",
    0x97: "POKE",
    0x98: "PRINT#",
    0x99: "PRINT",
    0x9A: "CONT",
    0x9B: "LIST",
    0x9C: "CLR",
    0x9D: "CMD",
    0x9E: "SYS",
    0x9F: "OPEN",
    0xA0: "CLOSE",
    0xA1: "GET",
    0xA2: "NEW",
    0xA3: "TAB(",
    0xA4: "TO",
    0xA5: "FN",
    0xA6: "SPC(",
    0xA7: "THEN",
    0xA8: "NOT",
    0xA9: "STEP",
    0xAA: "+",
    0xAB: "-",
    0xAC: "*",
    0xAD: "/",
    0xAE: "^",
    0xAF: "AND",
    0xB0: "OR",
    0xB1: ">",
    0xB2: "=",
    0xB3: "<",
    0xB4: "SGN",
    0xB5: "INT",
    0xB6: "ABS",
    0xB7: "USR",
    0xB8: "FRE",
    0xB9: "POS",
    0xBA: "SQR",
    0xBB: "RND",
    0xBC: "LOG",
    0xBD: "EXP",
    0xBE: "COS",
    0xBF: "SIN",
    0xC0: "TAN",
    0xC1: "ATN",
    0xC2: "PEEK",
    0xC3: "LEN",
    0xC4: "STR$",
    0xC5: "VAL",
    0xC6: "ASC",
    0xC7: "CHR$",
    0xC8: "LEFT$",
    0xC9: "RIGHT$",
    0xCA: "MID$",
    0xCB: "GO",
    0xFF: "PI",
}


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch in ("_", "$")


def detokenize_basic_line(body: bytes) -> str:
    """
    body is the tokenized portion *after* the 2-byte line number and before the 0x00 terminator.
    Returns a best-effort ASCII listing.
    """
    out: List[str] = []
    i = 0
    in_quotes = False
    in_rem = False

    while i < len(body):
        b = body[i]

        if in_rem:
            # Treat remaining bytes as raw text.
            out.append(chr(b) if 0x20 <= b <= 0x7E else ".")
            i += 1
            continue

        if in_quotes:
            out.append(chr(b) if 0x20 <= b <= 0x7E else ".")
            if b == 0x22:  # "
                in_quotes = False
            i += 1
            continue

        if b == 0x22:  # "
            in_quotes = True
            out.append('"')
            i += 1
            continue

        if b >= 0x80:
            kw = TOKEN_TO_KEYWORD.get(b, f"{{TOK:{b:02X}}}")
            # Add spacing heuristics so "PRINTA" doesn't happen in output.
            if out:
                prev = out[-1][-1:] if out[-1] else ""
                if prev and _is_word_char(prev) and kw and _is_word_char(kw[0]):
                    out.append(" ")
            out.append(kw)
            i += 1
            if kw == "REM":
                in_rem = True
            continue

        # Plain ASCII-ish
        out.append(chr(b) if 0x20 <= b <= 0x7E else ".")
        i += 1

    return "".join(out).rstrip()


@dataclasses.dataclass(frozen=True)
class BasicLine:
    addr: int
    number: int
    text: str


def parse_basic_prg(load_addr: int, data: bytes) -> Tuple[List[BasicLine], int]:
    """
    Parse a tokenized BASIC program loaded at load_addr (usually 0x0801).
    data is the PRG body (excluding 2-byte load address header).

    Returns (lines, end_addr) where end_addr is the address just after the 00 00 end marker.
    """
    if len(data) < 4:
        raise ValueError("PRG too small to be BASIC")

    lines: List[BasicLine] = []
    addr = load_addr
    max_addr = load_addr + len(data)

    def at(a: int) -> int:
        off = a - load_addr
        if off < 0 or off >= len(data):
            raise ValueError(f"Address out of range: ${a:04X}")
        return off

    # Linked list of lines: each line begins with link pointer to next line (2 bytes).
    while True:
        if addr + 2 > max_addr:
            raise ValueError("Truncated BASIC line link")
        link = data[at(addr)] | (data[at(addr + 1)] << 8)
        if link == 0x0000:
            end_addr = addr + 2
            break

        if addr + 4 > max_addr:
            raise ValueError("Truncated BASIC line header")
        line_no = data[at(addr + 2)] | (data[at(addr + 3)] << 8)

        # Extract token bytes until 0x00
        p = addr + 4
        token_bytes: List[int] = []
        while True:
            if p >= max_addr:
                raise ValueError("Truncated BASIC line body")
            b = data[at(p)]
            p += 1
            if b == 0x00:
                break
            token_bytes.append(b)

        text = detokenize_basic_line(bytes(token_bytes))
        lines.append(BasicLine(addr=addr, number=line_no, text=text))

        # Sanity checks
        if link <= addr or link > max_addr:
            raise ValueError(f"Invalid BASIC link ${link:04X} at ${addr:04X}")
        addr = link

    return lines, end_addr


# --- 6502 disassembler ---

@dataclasses.dataclass(frozen=True)
class OpInfo:
    mnemonic: str
    mode: str  # imp, acc, imm, zp, zpx, zpy, abs, absx, absy, ind, indx, indy, rel
    size: int


OPCODES: Dict[int, OpInfo] = {}


def _add(op: int, mnem: str, mode: str, size: int) -> None:
    OPCODES[op] = OpInfo(mnemonic=mnem, mode=mode, size=size)


def _init_opcodes() -> None:
    # Standard 6502 set (common subset for analysis). Unknown opcodes will be emitted as .byte.
    add = _add
    # ADC
    add(0x69, "ADC", "imm", 2); add(0x65, "ADC", "zp", 2); add(0x75, "ADC", "zpx", 2); add(0x6D, "ADC", "abs", 3)
    add(0x7D, "ADC", "absx", 3); add(0x79, "ADC", "absy", 3); add(0x61, "ADC", "indx", 2); add(0x71, "ADC", "indy", 2)
    # AND
    add(0x29, "AND", "imm", 2); add(0x25, "AND", "zp", 2); add(0x35, "AND", "zpx", 2); add(0x2D, "AND", "abs", 3)
    add(0x3D, "AND", "absx", 3); add(0x39, "AND", "absy", 3); add(0x21, "AND", "indx", 2); add(0x31, "AND", "indy", 2)
    # ASL
    add(0x0A, "ASL", "acc", 1); add(0x06, "ASL", "zp", 2); add(0x16, "ASL", "zpx", 2); add(0x0E, "ASL", "abs", 3); add(0x1E, "ASL", "absx", 3)
    # Branches
    add(0x90, "BCC", "rel", 2); add(0xB0, "BCS", "rel", 2); add(0xF0, "BEQ", "rel", 2); add(0x30, "BMI", "rel", 2)
    add(0xD0, "BNE", "rel", 2); add(0x10, "BPL", "rel", 2); add(0x50, "BVC", "rel", 2); add(0x70, "BVS", "rel", 2)
    # BIT
    add(0x24, "BIT", "zp", 2); add(0x2C, "BIT", "abs", 3)
    # BRK/RTI/RTS
    add(0x00, "BRK", "imp", 1); add(0x40, "RTI", "imp", 1); add(0x60, "RTS", "imp", 1)
    # Flags
    add(0x18, "CLC", "imp", 1); add(0xD8, "CLD", "imp", 1); add(0x58, "CLI", "imp", 1); add(0xB8, "CLV", "imp", 1)
    add(0x38, "SEC", "imp", 1); add(0xF8, "SED", "imp", 1); add(0x78, "SEI", "imp", 1)
    # CMP/CPX/CPY
    add(0xC9, "CMP", "imm", 2); add(0xC5, "CMP", "zp", 2); add(0xD5, "CMP", "zpx", 2); add(0xCD, "CMP", "abs", 3)
    add(0xDD, "CMP", "absx", 3); add(0xD9, "CMP", "absy", 3); add(0xC1, "CMP", "indx", 2); add(0xD1, "CMP", "indy", 2)
    add(0xE0, "CPX", "imm", 2); add(0xE4, "CPX", "zp", 2); add(0xEC, "CPX", "abs", 3)
    add(0xC0, "CPY", "imm", 2); add(0xC4, "CPY", "zp", 2); add(0xCC, "CPY", "abs", 3)
    # DEC/INC
    add(0xC6, "DEC", "zp", 2); add(0xD6, "DEC", "zpx", 2); add(0xCE, "DEC", "abs", 3); add(0xDE, "DEC", "absx", 3)
    add(0xE6, "INC", "zp", 2); add(0xF6, "INC", "zpx", 2); add(0xEE, "INC", "abs", 3); add(0xFE, "INC", "absx", 3)
    # DEX/DEY/INX/INY
    add(0xCA, "DEX", "imp", 1); add(0x88, "DEY", "imp", 1); add(0xE8, "INX", "imp", 1); add(0xC8, "INY", "imp", 1)
    # EOR
    add(0x49, "EOR", "imm", 2); add(0x45, "EOR", "zp", 2); add(0x55, "EOR", "zpx", 2); add(0x4D, "EOR", "abs", 3)
    add(0x5D, "EOR", "absx", 3); add(0x59, "EOR", "absy", 3); add(0x41, "EOR", "indx", 2); add(0x51, "EOR", "indy", 2)
    # JMP/JSR
    add(0x4C, "JMP", "abs", 3); add(0x6C, "JMP", "ind", 3); add(0x20, "JSR", "abs", 3)
    # LDA/LDX/LDY
    add(0xA9, "LDA", "imm", 2); add(0xA5, "LDA", "zp", 2); add(0xB5, "LDA", "zpx", 2); add(0xAD, "LDA", "abs", 3)
    add(0xBD, "LDA", "absx", 3); add(0xB9, "LDA", "absy", 3); add(0xA1, "LDA", "indx", 2); add(0xB1, "LDA", "indy", 2)
    add(0xA2, "LDX", "imm", 2); add(0xA6, "LDX", "zp", 2); add(0xB6, "LDX", "zpy", 2); add(0xAE, "LDX", "abs", 3); add(0xBE, "LDX", "absy", 3)
    add(0xA0, "LDY", "imm", 2); add(0xA4, "LDY", "zp", 2); add(0xB4, "LDY", "zpx", 2); add(0xAC, "LDY", "abs", 3); add(0xBC, "LDY", "absx", 3)
    # LSR
    add(0x4A, "LSR", "acc", 1); add(0x46, "LSR", "zp", 2); add(0x56, "LSR", "zpx", 2); add(0x4E, "LSR", "abs", 3); add(0x5E, "LSR", "absx", 3)
    # NOP
    add(0xEA, "NOP", "imp", 1)
    # ORA
    add(0x09, "ORA", "imm", 2); add(0x05, "ORA", "zp", 2); add(0x15, "ORA", "zpx", 2); add(0x0D, "ORA", "abs", 3)
    add(0x1D, "ORA", "absx", 3); add(0x19, "ORA", "absy", 3); add(0x01, "ORA", "indx", 2); add(0x11, "ORA", "indy", 2)
    # Stack
    add(0x48, "PHA", "imp", 1); add(0x08, "PHP", "imp", 1); add(0x68, "PLA", "imp", 1); add(0x28, "PLP", "imp", 1)
    # ROL/ROR
    add(0x2A, "ROL", "acc", 1); add(0x26, "ROL", "zp", 2); add(0x36, "ROL", "zpx", 2); add(0x2E, "ROL", "abs", 3); add(0x3E, "ROL", "absx", 3)
    add(0x6A, "ROR", "acc", 1); add(0x66, "ROR", "zp", 2); add(0x76, "ROR", "zpx", 2); add(0x6E, "ROR", "abs", 3); add(0x7E, "ROR", "absx", 3)
    # SBC
    add(0xE9, "SBC", "imm", 2); add(0xE5, "SBC", "zp", 2); add(0xF5, "SBC", "zpx", 2); add(0xED, "SBC", "abs", 3)
    add(0xFD, "SBC", "absx", 3); add(0xF9, "SBC", "absy", 3); add(0xE1, "SBC", "indx", 2); add(0xF1, "SBC", "indy", 2)
    # STA/STX/STY
    add(0x85, "STA", "zp", 2); add(0x95, "STA", "zpx", 2); add(0x8D, "STA", "abs", 3); add(0x9D, "STA", "absx", 3)
    add(0x99, "STA", "absy", 3); add(0x81, "STA", "indx", 2); add(0x91, "STA", "indy", 2)
    add(0x86, "STX", "zp", 2); add(0x96, "STX", "zpy", 2); add(0x8E, "STX", "abs", 3)
    add(0x84, "STY", "zp", 2); add(0x94, "STY", "zpx", 2); add(0x8C, "STY", "abs", 3)
    # Transfers
    add(0xAA, "TAX", "imp", 1); add(0xA8, "TAY", "imp", 1); add(0xBA, "TSX", "imp", 1); add(0x8A, "TXA", "imp", 1)
    add(0x9A, "TXS", "imp", 1); add(0x98, "TYA", "imp", 1)


def fmt_operand(mode: str, addr: int, op_bytes: bytes) -> str:
    if mode == "imp":
        return ""
    if mode == "acc":
        return "A"
    if mode == "imm":
        return f"#$%02X" % op_bytes[1]
    if mode == "zp":
        return f"$%02X" % op_bytes[1]
    if mode == "zpx":
        return f"$%02X,X" % op_bytes[1]
    if mode == "zpy":
        return f"$%02X,Y" % op_bytes[1]
    if mode == "abs":
        v = op_bytes[1] | (op_bytes[2] << 8)
        return f"$%04X" % v
    if mode == "absx":
        v = op_bytes[1] | (op_bytes[2] << 8)
        return f"$%04X,X" % v
    if mode == "absy":
        v = op_bytes[1] | (op_bytes[2] << 8)
        return f"$%04X,Y" % v
    if mode == "ind":
        v = op_bytes[1] | (op_bytes[2] << 8)
        return f"($%04X)" % v
    if mode == "indx":
        return f"($%02X,X)" % op_bytes[1]
    if mode == "indy":
        return f"($%02X),Y" % op_bytes[1]
    if mode == "rel":
        off = op_bytes[1]
        if off >= 0x80:
            off -= 0x100
        target = (addr + 2 + off) & 0xFFFF
        return f"$%04X" % target
    return ""


def disassemble_6502(load_addr: int, data: bytes, start: Optional[int], length: Optional[int]) -> List[str]:
    if not OPCODES:
        _init_opcodes()
    base = load_addr
    if start is None:
        start = base
    if length is None:
        length = max(0, (base + len(data)) - start)

    start = int(start) & 0xFFFF
    length = int(length)
    if length < 0:
        raise ValueError("--length must be >= 0")

    off0 = start - base
    if off0 < 0 or off0 > len(data):
        raise ValueError(f"Start address ${start:04X} is outside PRG body ${base:04X}-${base+len(data)-1:04X}")

    out: List[str] = []
    i = off0
    end = min(len(data), off0 + length)
    addr = start

    while i < end:
        op = data[i]
        info = OPCODES.get(op)
        if info is None:
            out.append(f"{addr:04X}  {op:02X}        .byte ${op:02X}")
            i += 1
            addr = (addr + 1) & 0xFFFF
            continue

        size = info.size
        if i + size > end:
            raw = data[i:end]
            out.append(f"{addr:04X}  " + " ".join(f"{b:02X}" for b in raw).ljust(9) + "  .byte " + ",".join(f"${b:02X}" for b in raw))
            break

        raw = data[i:i + size]
        operand = fmt_operand(info.mode, addr, raw)
        bytes_str = " ".join(f"{b:02X}" for b in raw).ljust(9)
        if operand:
            out.append(f"{addr:04X}  {bytes_str}  {info.mnemonic} {operand}")
        else:
            out.append(f"{addr:04X}  {bytes_str}  {info.mnemonic}")

        i += size
        addr = (addr + size) & 0xFFFF

    return out


# --- PRG parsing ---

@dataclasses.dataclass(frozen=True)
class Prg:
    load_addr: int
    data: bytes


def read_prg(path: str) -> Prg:
    buf = open(path, "rb").read()
    if len(buf) < 2:
        raise ValueError("Not a PRG (too small)")
    load_addr = buf[0] | (buf[1] << 8)
    return Prg(load_addr=load_addr, data=buf[2:])


# --- VICE Snapshot (VSF) parsing ---

def read_vsf(path: str) -> Prg:
    """
    Parse a VICE snapshot file (.vsf) and extract RAM.
    Returns a Prg object with load_addr=0x0000 and data=64KB RAM.
    
    VSF format structure:
    - Header: "VICE Snapshot File" + 0x1A + 0x02 + 0x00
    - Modules: Each module has a 4-byte name (like "C64MEM")
    - C64MEM module contains the 64KB RAM, typically 8 bytes after the module name
    """
    buf = open(path, "rb").read()
    
    # Check VSF header
    if len(buf) < 20:
        raise ValueError("VSF file too small")
    
    header = buf[0:20]
    if not header.startswith(b"VICE Snapshot File"):
        raise ValueError("Not a VICE snapshot file (invalid header)")
    
    # Find C64MEM module
    c64mem_idx = buf.find(b"C64MEM")
    if c64mem_idx < 0:
        raise ValueError("C64MEM module not found in snapshot")
    
    # RAM typically starts 8 bytes after "C64MEM" (4 bytes name + 4 bytes padding/header)
    ram_start = c64mem_idx + 8
    
    if ram_start + 0x10000 > len(buf):
        raise ValueError("VSF file too small to contain 64KB RAM")
    
    # Extract 64KB RAM
    ram_data = buf[ram_start:ram_start + 0x10000]
    
    # Verify it looks like RAM (check a few common addresses)
    # $0801 often has BASIC program (non-zero link pointer)
    if len(ram_data) >= 0x0803:
        link = ram_data[0x0801] | (ram_data[0x0802] << 8)
        # BASIC link should point forward and be reasonable
        if not (0x0801 < link < 0xA000):
            # Try alternative offsets (some VSF versions might differ)
            for offset in [4, 12, 16, 20, 24]:
                alt_start = c64mem_idx + 4 + offset
                if alt_start + 0x10000 <= len(buf):
                    alt_ram = buf[alt_start:alt_start + 0x10000]
                    if len(alt_ram) >= 0x0803:
                        alt_link = alt_ram[0x0801] | (alt_ram[0x0802] << 8)
                        if 0x0801 < alt_link < 0xA000:
                            ram_data = alt_ram
                            break
    
    return Prg(load_addr=0x0000, data=ram_data)


def looks_like_basic(prg: Prg) -> bool:
    # Most tokenized BASIC programs start at $0801.
    return prg.load_addr == 0x0801 and len(prg.data) >= 6


def _hex(b: int) -> str:
    return f"${b:02X}"


def _hex16(v: int) -> str:
    return f"${v & 0xFFFF:04X}"


def _fmt_bytes(bs: bytes) -> str:
    return " ".join(f"{b:02X}" for b in bs)


def _is_printable(b: int) -> bool:
    return 0x20 <= b <= 0x7E


def _escape_acme_string(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


KNOWN_C64_ADDRS: Dict[int, str] = {
    0xD020: "VIC border color",
    0xD021: "VIC background color",
    0xD011: "VIC control register 1",
    0xD016: "VIC control register 2",
    0xD015: "VIC sprite enable",
    0xD027: "VIC sprite 0 color",
    0xD028: "VIC sprite 1 color",
    0x07F8: "Sprite pointer 0",
    0x07F9: "Sprite pointer 1",
    0x0400: "Screen RAM",
    0xD800: "Color RAM",
    0xDC00: "CIA1 (keyboard/joystick)",
}

KNOWN_C64_SYMBOLS_EXACT: Dict[int, str] = {
    0x0400: "SCREEN",
    0xD800: "COLORRAM",
    0xD000: "VIC",
    0xD400: "SID",
    0xDC00: "CIA1",
    0xD020: "BORDER",
    0xD021: "BACKGROUND",
    0xD011: "VIC_CTRL1",
    0xD016: "VIC_CTRL2",
    0xD015: "SPRITEN",
    0xD027: "SPRITEC0",
    0xD028: "SPRITEC1",
    0x07F8: "SPR_PTR0",
    0x07F9: "SPR_PTR1",
}

KNOWN_KERNAL_SYMBOLS: Dict[int, str] = {
    0xFFD2: "CHROUT",
    0xFFE4: "GETIN",
    0xFFCF: "CHRIN",
    0xFFBA: "SETLFS",
    0xFFBD: "SETNAM",
    0xFFC0: "OPEN",
    0xFFC3: "CLOSE",
    0xFFC6: "CHKIN",
    0xFFC9: "CHKOUT",
    0xFFCC: "CLRCHN",
}

def comment_for_addr(v: int) -> Optional[str]:
    v &= 0xFFFF
    if v in KNOWN_C64_ADDRS:
        return KNOWN_C64_ADDRS[v]
    # SID register block
    if 0xD400 <= v <= 0xD418:
        return "SID register"
    # VIC register block
    if 0xD000 <= v <= 0xD02E:
        return "VIC register"
    return None


def _guess_text(data: bytes, i: int, *, min_len: int = 8) -> Optional[Tuple[int, str, bool]]:
    """
    Heuristic: if there's a run of printable bytes (optionally NUL-terminated), treat as text.
    Returns (length, text, has_nul_term).
    """
    # Avoid common false positives: don't start a text run on punctuation/control-ish bytes.
    first = data[i]
    if not (_is_printable(first) and (chr(first).isalnum() or chr(first) == " ")):
        return None
    j = i
    while j < len(data) and _is_printable(data[j]):
        j += 1
    if j - i < min_len:
        return None
    has_nul = (j < len(data) and data[j] == 0x00)
    text = data[i:j].decode("latin1", errors="replace")
    return (j - i, text, has_nul)


def _guess_sprite_block(data: bytes, i: int) -> Optional[int]:
    """
    Heuristic: 63-byte sprite (21 rows * 3 bytes). Commonly aligned to 64.
    Returns length (63) if plausible.
    """
    if i + 63 > len(data):
        return None
    block = data[i:i + 63]
    # Many sprites are sparse: lots of 0x00, or sometimes lots of 0xFF.
    zeros = sum(1 for b in block if b == 0x00)
    ffs = sum(1 for b in block if b == 0xFF)
    if (zeros + ffs) / 63.0 >= 0.65:
        return 63
    return None


def _is_multicolor_sprite(sprite_data: bytes) -> bool:
    """
    Detect if a sprite is multicolor mode.
    In multicolor mode, pixels are 2 bits (4 colors) instead of 1 bit.
    We detect this by checking if the sprite uses the multicolor bit patterns.
    """
    if len(sprite_data) < 63:
        return False
    
    # In multicolor mode, each byte pair represents 4 pixels (2 bits each)
    # Check if we see patterns that suggest multicolor:
    # - Non-zero bits in positions that would be used for multicolor
    # - Patterns that don't make sense for hi-res (1 bit per pixel)
    
    # Count how many bytes have bits set in the "multicolor positions"
    # In multicolor, we typically see more varied bit patterns
    multicolor_indicators = 0
    hi_res_indicators = 0
    
    for i in range(0, 63, 3):  # Process 3-byte rows
        if i + 2 >= len(sprite_data):
            break
        row_bytes = sprite_data[i:i+3]
        
        # Check for multicolor patterns: bits often set in pairs
        # In multicolor, adjacent bits in the same nybble are often both set/clear
        for byte_val in row_bytes:
            # Check if byte has patterns suggesting multicolor (2-bit pixels)
            # Multicolor often has more "dense" patterns
            bit_pairs = [
                (byte_val & 0xC0) >> 6,  # Bits 7-6
                (byte_val & 0x30) >> 4,  # Bits 5-4
                (byte_val & 0x0C) >> 2,  # Bits 3-2
                (byte_val & 0x03),       # Bits 1-0
            ]
            # If we see non-zero values in the upper bits of pairs, likely multicolor
            if any(pair > 0 for pair in bit_pairs):
                multicolor_indicators += 1
            # Hi-res typically has more isolated bits
            if byte_val != 0 and (byte_val & (byte_val - 1)) == 0:  # Power of 2 (single bit)
                hi_res_indicators += 1
    
    # Heuristic: if we have more multicolor indicators, it's likely multicolor
    # Also check if sprite uses "dense" patterns (many bits set)
    total_bits = sum(bin(b).count('1') for b in sprite_data)
    density = total_bits / (63 * 8)
    
    # Multicolor sprites often have higher bit density
    if density > 0.3 and multicolor_indicators > hi_res_indicators * 1.5:
        return True
    
    # Another check: if we see patterns that suggest 2-bit pixels
    # (adjacent pixels often have similar values in multicolor)
    return multicolor_indicators > hi_res_indicators * 2


def _render_sprite_svg(sprite_data: bytes, addr: int, is_multicolor: bool, output_path: str) -> None:
    """Render a C64 sprite as SVG"""
    if len(sprite_data) < 63:
        return
    
    # C64 sprite: 24x21 pixels (3 bytes per row, 21 rows)
    width = 24
    height = 21
    
    # C64 colors (approximate RGB values)
    colors = {
        0: "#000000",  # Black (transparent in hi-res, color 0 in multicolor)
        1: "#FFFFFF",  # White
        2: "#880000",  # Red
        3: "#AAFFEE",  # Cyan
        4: "#CC44CC",  # Purple
        5: "#00CC55",  # Green
        6: "#0000AA",  # Blue
        7: "#EEEE77",  # Yellow
        8: "#DD8855",  # Orange
        9: "#664400",  # Brown
        10: "#FF7777", # Light red
        11: "#333333", # Dark grey
        12: "#777777", # Grey
        13: "#AAFF66", # Light green
        14: "#0088FF", # Light blue
        15: "#BBBBBB", # Light grey
    }
    
    # Default multicolor palette (can be customized via VIC registers)
    multicolor_palette = {
        0: colors[0],   # Transparent
        1: colors[1],   # White (sprite color)
        2: colors[6],   # Blue (shared multicolor 1)
        3: colors[2],   # Red (shared multicolor 2)
    }
    
    pixels = []
    
    if is_multicolor:
        # Multicolor: 2 bits per pixel, 4 pixels per byte (each pixel is 2x wide = 8 pixels per byte)
        for row in range(height):
            row_pixels = []
            byte_offset = row * 3
            for byte_idx in range(3):
                if byte_offset + byte_idx >= len(sprite_data):
                    break
                byte_val = sprite_data[byte_offset + byte_idx]
                # Extract 4 pixels (2 bits each) from byte
                # Each 2-bit pixel is displayed as 2 pixels wide
                for pixel_idx in range(4):
                    pixel_x = byte_idx * 8 + pixel_idx * 2
                    if pixel_x >= width:
                        break
                    # Get 2-bit pixel value (bits 7-6, 5-4, 3-2, 1-0)
                    bit_shift = 6 - (pixel_idx * 2)
                    pixel_val = (byte_val >> bit_shift) & 0x03
                    # In multicolor, each 2-bit value represents a pixel that's 2x wide
                    row_pixels.append((pixel_x, pixel_val))
                    if pixel_x + 1 < width:
                        row_pixels.append((pixel_x + 1, pixel_val))
            pixels.append(row_pixels)
    else:
        # Hi-res: 1 bit per pixel, 8 pixels per byte
        for row in range(height):
            row_pixels = []
            byte_offset = row * 3
            for byte_idx in range(3):
                if byte_offset + byte_idx >= len(sprite_data):
                    break
                byte_val = sprite_data[byte_offset + byte_idx]
                # Extract 8 pixels (1 bit each) from byte
                for bit_idx in range(8):
                    pixel_x = byte_idx * 8 + bit_idx
                    if pixel_x >= width:
                        break
                    pixel_val = 1 if (byte_val & (0x80 >> bit_idx)) else 0
                    row_pixels.append((pixel_x, pixel_val))
            pixels.append(row_pixels)
    
    # Generate SVG
    scale = 8  # Scale factor for visibility
    svg_width = width * scale
    svg_height = height * scale
    
    svg_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg width="{svg_width}" height="{svg_height}" xmlns="http://www.w3.org/2000/svg">',
        f'<rect width="{svg_width}" height="{svg_height}" fill="#000000"/>',
    ]
    
    for row_idx, row_pixels in enumerate(pixels):
        # Group consecutive pixels with same value for efficiency
        current_x = None
        current_val = None
        current_width = 0
        
        for pixel_x, pixel_val in row_pixels:
            if pixel_val == 0 and not is_multicolor:
                # Skip transparent pixels in hi-res
                if current_x is not None:
                    color = multicolor_palette.get(current_val, colors.get(current_val, "#FFFFFF")) if is_multicolor else colors.get(current_val, "#FFFFFF")
                    x = current_x * scale
                    y = row_idx * scale
                    pixel_width = scale * current_width
                    svg_lines.append(f'<rect x="{x}" y="{y}" width="{pixel_width}" height="{scale}" fill="{color}"/>')
                    current_x = None
                continue
            
            if current_x is None:
                current_x = pixel_x
                current_val = pixel_val
                current_width = 2 if is_multicolor else 1
            elif pixel_val == current_val and pixel_x == current_x + current_width:
                current_width += (2 if is_multicolor else 1)
            else:
                # Emit current pixel group
                color = multicolor_palette.get(current_val, colors.get(current_val, "#FFFFFF")) if is_multicolor else colors.get(current_val, "#FFFFFF")
                x = current_x * scale
                y = row_idx * scale
                pixel_width = scale * current_width
                svg_lines.append(f'<rect x="{x}" y="{y}" width="{pixel_width}" height="{scale}" fill="{color}"/>')
                current_x = pixel_x
                current_val = pixel_val
                current_width = 2 if is_multicolor else 1
        
        # Emit final pixel group
        if current_x is not None:
            color = multicolor_palette.get(current_val, colors.get(current_val, "#FFFFFF")) if is_multicolor else colors.get(current_val, "#FFFFFF")
            x = current_x * scale
            y = row_idx * scale
            pixel_width = scale * current_width
            svg_lines.append(f'<rect x="{x}" y="{y}" width="{pixel_width}" height="{scale}" fill="{color}"/>')
    
    svg_lines.append('</svg>')
    
    with open(output_path, 'w') as f:
        f.write('\n'.join(svg_lines))


def _find_zero_gaps(data: bytes, base_addr: int, start_off: int, gap_threshold: int = 128) -> List[Tuple[int, int]]:
    """
    Return list of (gap_start_addr, gap_end_addr_exclusive) for long $00 runs.
    """
    gaps: List[Tuple[int, int]] = []
    i = start_off
    n = len(data)
    while i < n:
        if data[i] != 0x00:
            i += 1
            continue
        j = i
        while j < n and data[j] == 0x00:
            j += 1
        if j - i >= gap_threshold:
            gaps.append((base_addr + i, base_addr + j))
        i = j
    return gaps


def decompile_acme(prg: Prg, gap_threshold: int = 128, verbose: bool = False, export_sprites: bool = False, output_dir: str = ".") -> List[str]:
    """
    Emit ACME-friendly output with:
    - * = $ADDR segment starts
    - instructions and bytes as right-side comments
    - heuristics for BASIC stub, text, sprite blocks
    - long $00 gaps compressed into a single segment jump
    """
    if not OPCODES:
        _init_opcodes()

    base = prg.load_addr
    data = prg.data

    # --- Pre-scan for labels and symbolic addresses ---
    @dataclasses.dataclass
    class TargetInfo:
        jsr: bool = False
        jmp: bool = False
        branch: bool = False

    targets: Dict[int, TargetInfo] = {}
    used_abs: set[int] = set()
    used_zp: set[int] = set()
    first_code_addr: Optional[int] = None
    jmp_edges: List[Tuple[int, int]] = []  # (src, dst)
    refs_abs: Dict[int, List[Tuple[int, str, str]]] = {}  # target -> [(src, mnemonic, mode)]
    sprite_ptr_map: Dict[int, int] = {}  # sprite_data_addr -> sprite_index

    def mark_target(addr: int, kind: str) -> None:
        addr &= 0xFFFF
        ti = targets.get(addr)
        if ti is None:
            ti = TargetInfo()
            targets[addr] = ti
        if kind == "jsr":
            ti.jsr = True
        elif kind == "jmp":
            ti.jmp = True
        elif kind == "branch":
            ti.branch = True

    # BASIC stub detection at $0801 (common for ML PRGs)
    basic_end_addr: Optional[int] = None
    basic_lines: List[BasicLine] = []
    if base == 0x0801:
        try:
            basic_lines, basic_end_addr = parse_basic_prg(base, data)
        except Exception:
            basic_end_addr = None

    scan_i = 0
    if basic_end_addr is not None:
        scan_i = basic_end_addr - base

    gaps = _find_zero_gaps(data, base, scan_i, gap_threshold=gap_threshold)
    gap_iter = iter(gaps)
    next_gap = next(gap_iter, None)

    i = scan_i
    last_imm_a: Optional[int] = None
    while i < len(data):
        addr = base + i
        if next_gap and addr == next_gap[0]:
            i = next_gap[1] - base
            next_gap = next(gap_iter, None)
            continue

        spr_len = _guess_sprite_block(data, i)
        if spr_len:
            i += spr_len
            continue

        op = data[i]
        
        # Check for text BEFORE checking opcodes (same logic as output phase)
        # This prevents 0x20 (JSR/space) from being misidentified as instructions
        text_guess = None
        if i + 10 <= len(data):
            lookahead = min(20, len(data) - i)
            printable_count = 0
            has_alnum_after_space = False
            for j in range(lookahead):
                if _is_printable(data[i + j]):
                    printable_count += 1
                    if j > 0 and data[i + j - 1] == 0x20 and chr(data[i + j]).isalnum():
                        has_alnum_after_space = True
                else:
                    break
            
            if (has_alnum_after_space and printable_count >= 8) or printable_count >= 12:
                text_guess = _guess_text(data, i, min_len=8)
        
        info = OPCODES.get(op)
        if info is None and text_guess is None:
            text_guess = _guess_text(data, i, min_len=10)
        
        if text_guess:
            ln, _txt, has_nul = text_guess
            i += ln + (1 if has_nul else 0)
            continue
        
        if info is None:
            i += 1
            continue

        size = info.size
        if i + size > len(data):
            break
        raw = data[i:i + size]

        if first_code_addr is None and op != 0x00:
            first_code_addr = addr

        # Track A immediate loads (for sprite pointer heuristics).
        if info.mnemonic == "LDA" and info.mode == "imm":
            last_imm_a = raw[1]

        if info.mode in ("abs", "absx", "absy", "ind"):
            tgt = raw[1] | (raw[2] << 8)
            used_abs.add(tgt)
            refs_abs.setdefault(tgt, []).append((addr, info.mnemonic, info.mode))
        if info.mode in ("zp", "zpx", "zpy", "indx", "indy"):
            used_zp.add(raw[1])

        # Sprite pointer heuristic: LDA #$C0 ; STA $07F8 => sprite data at $C0*64 (= $3000).
        if info.mnemonic == "STA" and info.mode == "abs" and last_imm_a is not None:
            tgt = raw[1] | (raw[2] << 8)
            if tgt in (0x07F8, 0x07F9):
                spr_idx = tgt - 0x07F8
                sprite_data_addr = (last_imm_a & 0xFF) * 64
                sprite_ptr_map.setdefault(sprite_data_addr & 0xFFFF, spr_idx)

        if info.mnemonic == "JSR" and info.mode == "abs":
            mark_target(raw[1] | (raw[2] << 8), "jsr")
        elif info.mnemonic == "JMP" and info.mode == "abs":
            tgt = raw[1] | (raw[2] << 8)
            mark_target(tgt, "jmp")
            jmp_edges.append((addr, tgt))
        elif info.mode == "rel":
            off = raw[1]
            if off >= 0x80:
                off -= 0x100
            mark_target((addr + 2 + off) & 0xFFFF, "branch")

        i += size

    label_names: Dict[int, str] = {}
    for a, ti in sorted(targets.items(), key=lambda kv: kv[0]):
        if ti.jsr:
            label_names[a] = f"function_{a:04X}"
        else:
            label_names[a] = f"label_{a:04X}"
    label_addrs = set(label_names.keys())

    def spans_label(start_addr: int, length: int) -> bool:
        if length <= 0:
            return False
        end_addr = (start_addr + length) & 0xFFFF
        # We only care about linear regions inside the PRG; this is a best-effort check.
        # (No wraparound expected in typical PRGs.)
        if end_addr < start_addr:
            return True
        for a in label_addrs:
            if start_addr <= a < end_addr:
                return True
        return False

    # Data labels (created lazily during output)
    data_labels: Dict[int, str] = {}
    used_data_names: set[str] = set()

    def alloc_data_label(addr_val: int, kind: str) -> str:
        addr_val &= 0xFFFF
        if addr_val in label_names:
            return label_names[addr_val]
        if addr_val in data_labels:
            return data_labels[addr_val]

        base_name: str
        if kind == "text":
            refs = refs_abs.get(addr_val, [])
            if any(m == "LDA" and mode in ("absx", "absy") for (_s, m, mode) in refs):
                base_name = "msg_text"
            else:
                base_name = "text"
        elif kind == "sprite":
            spr_idx = sprite_ptr_map.get(addr_val)
            if spr_idx is not None:
                base_name = f"sprite{spr_idx}_data"
            else:
                base_name = "sprite_data"
        else:
            base_name = "data"

        name = base_name
        if name in used_data_names:
            name = f"{base_name}_{addr_val:04X}"
        used_data_names.add(name)
        data_labels[addr_val] = name
        return name

    def sym_for_abs(v: int) -> str:
        v &= 0xFFFF
        if v in KNOWN_KERNAL_SYMBOLS:
            return KNOWN_KERNAL_SYMBOLS[v]
        if v in KNOWN_C64_SYMBOLS_EXACT:
            return KNOWN_C64_SYMBOLS_EXACT[v]
        if v in label_names:
            return label_names[v]
        if v in data_labels:
            return data_labels[v]
        # common RAM areas
        if 0x0400 <= v <= 0x07E7:
            return f"SCREEN+${v-0x0400:04X}".replace("$0000", "$0000").replace("+$0000", "")
        if 0xD800 <= v <= 0xDBE7:
            return f"COLORRAM+${v-0xD800:04X}".replace("+$0000", "")
        # base+offset forms for common register blocks
        if 0xD000 <= v <= 0xD02E:
            return f"VIC+${v-0xD000:02X}"
        if 0xD400 <= v <= 0xD418:
            return f"SID+${v-0xD400:02X}"
        if 0xDC00 <= v <= 0xDC0F:
            return f"CIA1+${v-0xDC00:02X}"
        return _hex16(v)

    def sym_for_zp(b: int) -> str:
        return f"ZP_{b & 0xFF:02X}"

    # Emit header + symbol tables
    out: List[str] = []
    source_type = "VSF snapshot" if base == 0x0000 and len(data) == 0x10000 else "PRG"
    out.append(f"; Decompiled from {source_type} (load={_hex16(base)}, len={len(data)} bytes)")
    out.append("; ACME-friendly output with labels and basic heuristics.")
    out.append("")
    out.append("!cpu 6510")
    out.append("")

    symbol_defs: List[str] = []
    # Base symbols that should exist if any of their ranges are referenced.
    if any(0xD000 <= a <= 0xD02E for a in used_abs):
        symbol_defs.append(f"{'VIC':<10}= {_hex16(0xD000)}")
    if any(0xD400 <= a <= 0xD418 for a in used_abs):
        symbol_defs.append(f"{'SID':<10}= {_hex16(0xD400)}")
    if any(0xDC00 <= a <= 0xDC0F for a in used_abs):
        symbol_defs.append(f"{'CIA1':<10}= {_hex16(0xDC00)}")
    if any(0x0400 <= a <= 0x07E7 for a in used_abs):
        symbol_defs.append(f"{'SCREEN':<10}= {_hex16(0x0400)}")
    if any(0xD800 <= a <= 0xDBE7 for a in used_abs):
        symbol_defs.append(f"{'COLORRAM':<10}= {_hex16(0xD800)}")

    # Exact symbols (only if referenced exactly)
    for addr_val, name in sorted(KNOWN_C64_SYMBOLS_EXACT.items(), key=lambda kv: kv[0]):
        if addr_val in used_abs and name not in {s.split("=")[0].strip() for s in symbol_defs}:
            symbol_defs.append(f"{name:<10}= {_hex16(addr_val)}")

    # KERNAL vectors (only if referenced)
    for addr_val, name in sorted(KNOWN_KERNAL_SYMBOLS.items(), key=lambda kv: kv[0]):
        if addr_val in used_abs:
            symbol_defs.append(f"{name:<10}= {_hex16(addr_val)}")

    # Dedupe while preserving order
    seen = set()
    symbol_defs = [s for s in symbol_defs if not (s.split("=")[0].strip() in seen or seen.add(s.split("=")[0].strip()))]
    if symbol_defs:
        out.append("; C64 symbols (used)")
        out.extend(symbol_defs)
        out.append("")

    if used_zp:
        out.append("; Zero-page variables (guessed)")
        for b in sorted(used_zp):
            out.append(f"{sym_for_zp(b):<10}= {_hex(b)}")
        out.append("")

    # Smarter label for the apparent entrypoint (best-effort)
    if first_code_addr is not None:
        if first_code_addr not in label_names:
            label_names[first_code_addr] = "start"
        else:
            # If it was already a label/function, keep that name but also provide an alias comment.
            pass
    label_addrs = set(label_names.keys())

    # Smarter label for the main loop (best-effort): first backward JMP target after start
    if first_code_addr is not None:
        backward = [(src, dst) for (src, dst) in jmp_edges if dst < src and dst in label_names]
        backward.sort(key=lambda e: (e[1], e[0]))
        if backward:
            _src, dst = backward[0]
            if dst != first_code_addr and label_names.get(dst, "").startswith("label_"):
                label_names[dst] = "main_loop"
                label_addrs = set(label_names.keys())

    # Smarter function names: analyze each JSR target and rename when we can recognize patterns.
    def analyze_routine(addr0: int, max_bytes: int = 256) -> Dict[str, bool]:
        """
        Best-effort static scan of a routine starting at addr0 until RTS/RTI or max_bytes.
        Returns feature flags.
        """
        off = addr0 - base
        if off < 0 or off >= len(data):
            return {}
        touched: set[int] = set()
        writes: set[int] = set()
        reads: set[int] = set()
        i2 = off
        end = min(len(data), off + max_bytes)
        while i2 < end:
            op = data[i2]
            info = OPCODES.get(op)
            if info is None:
                break
            size = info.size
            if i2 + size > end:
                break
            raw = data[i2:i2 + size]
            addr_here = (base + i2) & 0xFFFF
            if info.mode in ("abs", "absx", "absy"):
                v = raw[1] | (raw[2] << 8)
                touched.add(v)
                if info.mnemonic in ("STA", "STX", "STY", "INC", "DEC"):
                    writes.add(v)
                if info.mnemonic in ("LDA", "LDX", "LDY", "CMP", "BIT"):
                    reads.add(v)
            if info.mnemonic in ("RTS", "RTI"):
                break
            # Don't chase into other routines; just linear scan.
            if info.mnemonic == "JMP" and info.mode == "abs":
                break
            if info.mnemonic == "JSR":
                # keep scanning, but note it may continue
                pass
            i2 += size
            # avoid infinite loops on self-branches (best-effort)
            if (base + i2) == addr_here:
                break

        def any_in(r0: int, r1: int, s: set[int]) -> bool:
            return any(r0 <= x <= r1 for x in s)

        return {
            "touch_vic": any_in(0xD000, 0xD02E, touched),
            "touch_sid": any_in(0xD400, 0xD418, touched),
            "touch_cia1": any_in(0xDC00, 0xDC0F, touched),
            "writes_border_bg": (0xD020 in writes) or (0xD021 in writes),
            "writes_sprite_regs": any_in(0x07F8, 0x07FF, writes) or any_in(0xD015, 0xD02E, writes),
            "writes_screen": any_in(0x0400, 0x07E7, writes) or any_in(0xD800, 0xDBE7, writes),
        }

    # Rename functions based on features
    preferred: Dict[int, str] = {}
    for a, ti in targets.items():
        if not ti.jsr:
            continue
        feat = analyze_routine(a)
        name = None
        if feat.get("writes_border_bg") and feat.get("touch_vic"):
            name = "init_screen"
        elif feat.get("writes_sprite_regs"):
            name = "init_sprites"
        elif feat.get("touch_sid") and feat.get("touch_vic") and (0xD418 in used_abs):
            name = "init_sound"
        elif feat.get("touch_cia1"):
            name = "read_input"
        elif feat.get("writes_screen"):
            name = "draw_text"
        if name:
            preferred[a] = name

    # Apply preferred names, ensuring uniqueness
    used_names = set(label_names.values())
    for a, base_name in sorted(preferred.items(), key=lambda kv: kv[0]):
        new_name = base_name
        if new_name in used_names:
            new_name = f"{base_name}_{a:04X}"
        label_names[a] = new_name
        used_names.add(new_name)
    label_addrs = set(label_names.keys())

    # Emit symbol definitions for labels that are referenced but outside PRG data range
    prg_start = base
    prg_end = base + len(data)
    external_labels: List[Tuple[int, str]] = []
    for addr, name in sorted(label_names.items(), key=lambda kv: kv[0]):
        # Check if label is outside PRG data range
        if addr < prg_start or addr >= prg_end:
            # Avoid duplicates with known symbols
            if addr not in KNOWN_KERNAL_SYMBOLS and addr not in KNOWN_C64_SYMBOLS_EXACT:
                external_labels.append((addr, name))
    
    # Emit external labels section
    if external_labels:
        out.append("; External labels (referenced but outside PRG data)")
        for addr, name in external_labels:
            out.append(f"{name:<10}= {_hex16(addr)}")
        out.append("")

    # --- Instruction explanation (optional verbose output) ---
    def explain(mn: str, mode: str, operand_txt: str, addr_here: int, raw_bytes: bytes) -> str:
        mn_u = mn.upper()
        if mn_u == "NOP":
            return "No OPeration"
        if mn_u == "JMP":
            return f"Jump to {operand_txt}"
        if mn_u == "JSR":
            return f"Jump to subroutine {operand_txt}"
        if mn_u == "RTS":
            return "Return from subroutine"
        if mn_u == "RTI":
            return "Return from interrupt"
        if mn_u in ("LDA", "LDX", "LDY"):
            reg = mn_u[-1]
            return f"Load {reg} with {operand_txt or '(implied)'}"
        if mn_u in ("STA", "STX", "STY"):
            reg = mn_u[-1]
            return f"Store {reg} into {operand_txt}"
        if mn_u in ("INX", "INY", "DEX", "DEY"):
            return f"{mn_u} (increment/decrement index)"
        if mn_u in ("CLC", "SEC"):
            return "Clear/Set Carry flag"
        if mn_u in ("CLI", "SEI"):
            return "Clear/Set Interrupt Disable flag"
        if mn_u in ("CLD", "SED"):
            return "Clear/Set Decimal flag"
        if mn_u in ("CMP", "CPX", "CPY"):
            return f"Compare with {operand_txt}"
        if mn_u.startswith("B") and mode == "rel":
            branch_map = {
                "BEQ": "Branch if Equal (Z=1)",
                "BNE": "Branch if Not Equal (Z=0)",
                "BCC": "Branch if Carry Clear (C=0)",
                "BCS": "Branch if Carry Set (C=1)",
                "BMI": "Branch if Minus (N=1)",
                "BPL": "Branch if Plus (N=0)",
                "BVC": "Branch if Overflow Clear (V=0)",
                "BVS": "Branch if Overflow Set (V=1)",
            }
            return f"{branch_map.get(mn_u, 'Branch')} to {operand_txt}"
        if mn_u in ("ASL", "LSR", "ROL", "ROR"):
            return "Shift/rotate"
        if mn_u in ("AND", "ORA", "EOR"):
            return "Bitwise logic"
        if mn_u in ("ADC", "SBC"):
            return "Add/Subtract with Carry"
        return ""

    # --- Actual output pass ---
    i = 0
    cur_addr = base

    if basic_end_addr is not None:
        end_off = basic_end_addr - base
        out.append("* = $0801")
        out.append("; BASIC stub (tokenized):")
        for bl in basic_lines:
            out.append(f"; {bl.number} {bl.text}".rstrip())
        stub = data[0:end_off]
        for row in range(0, len(stub), 12):
            chunk = stub[row:row + 12]
            bytes_list = ",".join(_hex(b) for b in chunk)
            addr_here = base + row
            out.append(f"        !byte {bytes_list:<47} ; {addr_here:04X}: {_fmt_bytes(chunk)}")
        out.append("")
        i = end_off
        cur_addr = base + i

    gaps = _find_zero_gaps(data, base, i, gap_threshold=gap_threshold)
    gap_iter = iter(gaps)
    next_gap = next(gap_iter, None)

    def start_segment(addr: int) -> None:
        out.append(f"* = { _hex16(addr) }")

    start_segment(cur_addr)

    while i < len(data):
        addr = base + i

        if next_gap and addr == next_gap[0]:
            g0, g1 = next_gap
            # Check for labels within the gap and emit them before skipping
            for gap_addr in range(g0, g1):
                if gap_addr in label_names:
                    out.append(f"{label_names[gap_addr]}:")
            out.append(f"; ... gap {g1 - g0} bytes of $00 from {g0:04X} to {g1-1:04X}")
            i = g1 - base
            cur_addr = base + i
            out.append("")
            if i >= len(data):
                break
            start_segment(cur_addr)
            next_gap = next(gap_iter, None)
            continue

        if addr in label_names:
            out.append(f"{label_names[addr]}:")
        elif addr in data_labels:
            out.append(f"{data_labels[addr]}:")

        spr_len = _guess_sprite_block(data, i)
        if spr_len and not spans_label(addr, spr_len):
            alloc_data_label(addr, "sprite")
            sprite_label = data_labels[addr]
            out.append(f"{sprite_label}:")
            out.append(f"; sprite data (guess): {spr_len} bytes")
            block = data[i:i + spr_len]
            
            # Export sprite if requested
            if export_sprites:
                is_multicolor = _is_multicolor_sprite(block)
                # Clean up sprite name - remove any existing address suffixes
                sprite_name = sprite_label.replace("sprite", "sprite_data").replace("_data_data", "_data")
                # Remove any existing address pattern from name (hex or decimal)
                import re
                sprite_name = re.sub(r'_[0-9A-Fa-f]{4}$', '', sprite_name, flags=re.IGNORECASE)
                
                # Export as multicolor if detected, otherwise export both
                if is_multicolor:
                    svg_path = os.path.join(output_dir, f"{sprite_name}_{addr:04X}_multicolor.svg")
                    _render_sprite_svg(block, addr, True, svg_path)
                    out.append(f"; Exported: {svg_path}")
                else:
                    # Export both hi-res and multicolor guesses
                    svg_path_hi = os.path.join(output_dir, f"{sprite_name}_{addr:04X}_hires.svg")
                    svg_path_mc = os.path.join(output_dir, f"{sprite_name}_{addr:04X}_multicolor.svg")
                    _render_sprite_svg(block, addr, False, svg_path_hi)
                    _render_sprite_svg(block, addr, True, svg_path_mc)
                    out.append(f"; Exported: {svg_path_hi} (hi-res) and {svg_path_mc} (multicolor)")
            
            for row in range(0, spr_len, 12):
                chunk = block[row:row + 12]
                bytes_list = ",".join(_hex(b) for b in chunk)
                addr_here = addr + row
                out.append(f"        !byte {bytes_list:<47} ; {addr_here:04X}: {_fmt_bytes(chunk)}")
            i += spr_len
            cur_addr = base + i
            out.append("")
            continue

        op = data[i]
        
        # Check for text BEFORE checking opcodes, especially for ambiguous bytes like 0x20 (JSR/space)
        # If we see a pattern that looks like text (spaces + alphanumeric), prioritize text detection
        text_guess = None
        if i + 10 <= len(data):
            # Check if current position looks like text start
            # Look ahead: if we see 3+ consecutive printable chars (especially spaces + letters), it's likely text
            lookahead = min(20, len(data) - i)
            printable_count = 0
            has_alnum_after_space = False
            for j in range(lookahead):
                if _is_printable(data[i + j]):
                    printable_count += 1
                    if j > 0 and data[i + j - 1] == 0x20 and chr(data[i + j]).isalnum():
                        has_alnum_after_space = True
                else:
                    break
            
            # If we see spaces followed by alphanumeric, or long runs of printable, check for text
            if (has_alnum_after_space and printable_count >= 8) or printable_count >= 12:
                text_guess = _guess_text(data, i, min_len=8)
        
        # Also check if current byte is not a recognized opcode
        info = OPCODES.get(op)
        if info is None and text_guess is None:
            text_guess = _guess_text(data, i, min_len=10)
        
        # If we found text, emit it (even if current byte is a valid opcode like 0x20=JSR)
        if text_guess:
            ln, txt, has_nul = text_guess
            total_len = ln + (1 if has_nul else 0)
            if not spans_label(addr, total_len):
                alloc_data_label(addr, "text")
                out.append(f"{data_labels[addr]}:")
                out.append(f'        !text "{_escape_acme_string(txt)}" ; {addr:04X}: {_fmt_bytes(data[i:i+ln])}')
                i += ln
                cur_addr = base + i
                if has_nul:
                    out.append(f"        !byte $00{' ' * 34}; {cur_addr:04X}: 00")
                    i += 1
                    cur_addr = base + i
                continue
        
        if info is None:

            # Check if this address has a label (shouldn't normally happen for single bytes,
            # but check anyway to be safe)
            if addr in label_names:
                out.append(f"{label_names[addr]}:")
            out.append(f"        !byte {_hex(op):<40} ; {addr:04X}: {op:02X}")
            i += 1
            cur_addr = base + i
            continue

        size = info.size
        if i + size > len(data):
            tail = data[i:]
            out.append(f"        !byte {','.join(_hex(b) for b in tail)} ; {addr:04X}: {_fmt_bytes(tail)}")
            break

        raw = data[i:i + size]

        # Operand formatting with symbols/labels
        if info.mode == "imp":
            operand = ""
        elif info.mode == "acc":
            # ACME accepts bare shifts/rotates as accumulator mode.
            operand = ""
        elif info.mode == "imm":
            operand = f"#$%02X" % raw[1]
        elif info.mode == "zp":
            operand = sym_for_zp(raw[1])
        elif info.mode == "zpx":
            operand = f"{sym_for_zp(raw[1])},X"
        elif info.mode == "zpy":
            operand = f"{sym_for_zp(raw[1])},Y"
        elif info.mode == "abs":
            operand = sym_for_abs(raw[1] | (raw[2] << 8))
        elif info.mode == "absx":
            operand = f"{sym_for_abs(raw[1] | (raw[2] << 8))},X"
        elif info.mode == "absy":
            operand = f"{sym_for_abs(raw[1] | (raw[2] << 8))},Y"
        elif info.mode == "ind":
            operand = f"({sym_for_abs(raw[1] | (raw[2] << 8))})"
        elif info.mode == "indx":
            operand = f"({sym_for_zp(raw[1])},X)"
        elif info.mode == "indy":
            operand = f"({sym_for_zp(raw[1])}),Y"
        elif info.mode == "rel":
            off = raw[1]
            if off >= 0x80:
                off -= 0x100
            operand = sym_for_abs((addr + 2 + off) & 0xFFFF)
        else:
            operand = fmt_operand(info.mode, addr, raw)

        mnem = info.mnemonic.lower()
        asm = f"{mnem}"
        if operand:
            asm += f" {operand}"

        extra = ""
        if info.mode in ("abs", "absx", "absy"):
            v = raw[1] | (raw[2] << 8)
            c = comment_for_addr(v)
            if c:
                extra = f" ; {c}"

        desc = explain(info.mnemonic, info.mode, operand, addr, raw) if verbose else ""
        desc_part = f" ; {desc}" if desc else ""
        out.append(f"        {asm:<26} ; {addr:04X}: {_fmt_bytes(raw)}{extra}{desc_part}")
        i += size
        cur_addr = base + i

    # Collect any labels that were in label_names but never emitted
    # (This can happen if they're in gaps or data sections we skipped)
    emitted_labels = set()
    for line in out:
        # Check if line is a label definition (starts with label name and ends with :)
        if ':' in line and not line.strip().startswith(';') and not line.strip().startswith('*'):
            label_name = line.split(':')[0].strip()
            emitted_labels.add(label_name)
    
    # Find labels that weren't emitted but are in label_names and within PRG range
    missing_labels: List[Tuple[int, str]] = []
    prg_start = base
    prg_end = base + len(data)
    for addr, name in label_names.items():
        if name not in emitted_labels and prg_start <= addr < prg_end:
            missing_labels.append((addr, name))
    
    # Add missing labels as symbol definitions at the end
    if missing_labels:
        out.append("")
        out.append("; Labels referenced but not emitted in code (may be in data/gaps)")
        for addr, name in sorted(missing_labels, key=lambda x: x[0]):
            out.append(f"{name:<10}= {_hex16(addr)}")
        out.append("")

    return out


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="C64 PRG/VSF decompiler (BASIC detokenizer + 6502 disassembler)")
    ap.add_argument("input_file", help="Path to .prg or .vsf (VICE snapshot) file")
    ap.add_argument("--mode", choices=["auto", "basic", "disasm", "acme"], default="auto", help="Output mode")
    ap.add_argument("--start", default=None, help="Disasm start address (hex like 0x1000 or $1000 or decimal)")
    ap.add_argument("--length", type=int, default=None, help="Disasm byte length")
    ap.add_argument("--gap-threshold", type=int, default=128, help="ACME mode: compress $00 gaps >= this size")
    ap.add_argument("-v", "--verbose", action="store_true", help="ACME mode: add extra explanatory comments per instruction")
    ap.add_argument("--export-sprites", action="store_true", help="Export detected sprites as SVG images")
    ap.add_argument("--sprite-output-dir", default=".", help="Directory for exported sprite images (default: current directory)")
    args = ap.parse_args(argv)

    # Detect file type and read accordingly
    input_path = args.input_file.lower()
    if input_path.endswith('.vsf'):
        prg = read_vsf(args.input_file)
    else:
        prg = read_prg(args.input_file)

    # Parse start argument if provided
    start: Optional[int] = None
    if args.start is not None:
        s = str(args.start).strip()
        if s.startswith("$"):
            start = int(s[1:], 16)
        elif s.lower().startswith("0x"):
            start = int(s, 16)
        else:
            start = int(s, 10)

    mode = args.mode
    if mode == "auto":
        mode = "basic" if looks_like_basic(prg) else "disasm"

    if mode == "basic":
        try:
            lines, _end_addr = parse_basic_prg(prg.load_addr, prg.data)
        except Exception as e:
            raise SystemExit(f"Failed to parse BASIC PRG: {e}")
        for line in lines:
            print(f"{line.number} {line.text}".rstrip())
        return 0

    if mode == "disasm":
        lines = disassemble_6502(prg.load_addr, prg.data, start=start, length=args.length)
        for l in lines:
            print(l)
        return 0

    if mode == "acme":
        lines = decompile_acme(prg, gap_threshold=args.gap_threshold, verbose=args.verbose, 
                               export_sprites=args.export_sprites, output_dir=args.sprite_output_dir)
        for l in lines:
            print(l)
        return 0

    raise SystemExit(f"Unknown mode: {mode}")


if __name__ == "__main__":
    # Avoid noisy BrokenPipeError when piping to `head`, etc.
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except Exception:
        pass
    raise SystemExit(main(sys.argv[1:]))

