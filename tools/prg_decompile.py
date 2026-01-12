#!/usr/bin/env python3
"""
prg_decompile.py - C64 PRG decompiler (BASIC detokenizer + 6502 disassembler)

Goals:
- Zero dependencies (stdlib only)
- Useful for diffing/analysis across compilations

Examples:
  python3 tools/prg_decompile.py programs/main.prg
  python3 tools/prg_decompile.py programs/main.prg --mode basic
  python3 tools/prg_decompile.py programs/main.prg --mode disasm --start 0x1000 --length 256
"""

from __future__ import annotations

import argparse
import dataclasses
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


def parse_basic_prg(load_addr: int, data: bytes) -> List[BasicLine]:
    """
    Parse a tokenized BASIC program loaded at load_addr (usually 0x0801).
    data is the PRG body (excluding 2-byte load address header).
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

    return lines


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


def looks_like_basic(prg: Prg) -> bool:
    # Most tokenized BASIC programs start at $0801.
    return prg.load_addr == 0x0801 and len(prg.data) >= 6


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="C64 PRG decompiler (BASIC detokenizer + 6502 disassembler)")
    ap.add_argument("prg", help="Path to .prg file")
    ap.add_argument("--mode", choices=["auto", "basic", "disasm"], default="auto", help="Output mode")
    ap.add_argument("--start", default=None, help="Disasm start address (hex like 0x1000 or $1000 or decimal)")
    ap.add_argument("--length", type=int, default=None, help="Disasm byte length")
    args = ap.parse_args(argv)

    prg = read_prg(args.prg)

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
            lines = parse_basic_prg(prg.load_addr, prg.data)
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

    raise SystemExit(f"Unknown mode: {mode}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

