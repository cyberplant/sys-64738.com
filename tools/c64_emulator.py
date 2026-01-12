#!/usr/bin/env python3
"""
C64 Emulator - Text mode Python implementation

A Commodore 64 emulator focused on text mode operation.
Can load and run PRG files, dump memory, and communicate via TCP/UDP.

Usage:
    python tools/c64_emulator.py [program.prg]
    python tools/c64_emulator.py --tcp-port 1234
    python tools/c64_emulator.py program.prg --udp-port 1235
"""

from __future__ import annotations

import argparse
import json
import queue
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime


# C64 Memory Map Constants
ROM_BASIC_START = 0xA000
ROM_BASIC_END = 0xC000
ROM_KERNAL_START = 0xE000
ROM_KERNAL_END = 0x10000
ROM_CHAR_START = 0xD000
ROM_CHAR_END = 0xE000

RAM_START = 0x0000
RAM_END = 0x10000

# I/O Addresses
VIC_BASE = 0xD000
SID_BASE = 0xD400
CIA1_BASE = 0xDC00
CIA2_BASE = 0xDD00

# IRQ vector
IRQ_VECTOR = 0x0314

# Screen memory (default)
SCREEN_MEM = 0x0400
COLOR_MEM = 0xD800


@dataclass
class CPUState:
    """6502 CPU state"""
    pc: int = 0x0000  # Program counter
    a: int = 0  # Accumulator
    x: int = 0  # X register
    y: int = 0  # Y register
    sp: int = 0xFF  # Stack pointer
    p: int = 0x24  # Processor status (Z=2, I=4, D=8, B=16, V=64, N=128)
    cycles: int = 0
    stopped: bool = False


@dataclass
class CIATimer:
    """CIA timer state"""
    latch: int = 0xFFFF  # Timer latch value
    counter: int = 0xFFFF  # Current counter value
    running: bool = False  # Is timer running?
    irq_enabled: bool = False  # Is IRQ enabled for this timer?
    one_shot: bool = False  # One-shot mode (vs continuous)
    input_mode: int = 0  # Input mode (0=processor clock)
    
    def update(self, cycles: int) -> bool:
        """Update timer, return True if IRQ should be triggered"""
        if not self.running:
            return False
        
        if self.input_mode == 0:  # Processor clock mode
            self.counter -= cycles
            if self.counter <= 0:
                # Timer underflow
                # Reload timer first
                overflow = abs(self.counter)
                self.counter = self.latch - overflow
                if self.counter < 0:
                    self.counter = 0
                
                if self.irq_enabled:
                    return True
                # If one-shot, stop timer
                if self.one_shot:
                    self.running = False
        return False
    
    def reset(self) -> None:
        """Reset timer to latch value"""
        self.counter = self.latch


@dataclass
class MemoryMap:
    """C64 memory map"""
    ram: bytearray = field(default_factory=lambda: bytearray(0x10000))
    basic_rom: Optional[bytes] = None
    kernal_rom: Optional[bytes] = None
    char_rom: Optional[bytes] = None
    udp_debug: Optional['UdpDebugLogger'] = None
    cia1_timer_a: CIATimer = field(default_factory=CIATimer)
    cia1_timer_b: CIATimer = field(default_factory=CIATimer)
    cia1_icr: int = 0  # Interrupt Control Register
    pending_irq: bool = False  # Pending IRQ flag
    
    def read(self, addr: int) -> int:
        """Read from memory, handling ROM/RAM mapping"""
        addr &= 0xFFFF
        
        # I/O area (can be ROM or RAM depending on memory config)
        if ROM_CHAR_START <= addr < ROM_CHAR_END:
            # Check if I/O is enabled (bit 0 of $01)
            if self.ram[0x01] & 0x03 == 0x03:  # I/O enabled
                # I/O registers (VIC, SID, CIA, etc.)
                return self._read_io(addr)
            elif self.char_rom:
                return self.char_rom[addr - ROM_CHAR_START]
            else:
                return self.ram[addr]
        
        # BASIC ROM
        if ROM_BASIC_START <= addr < ROM_BASIC_END:
            if self.ram[0x01] & 0x07 == 0x07:  # BASIC ROM enabled
                if self.basic_rom:
                    return self.basic_rom[addr - ROM_BASIC_START]
            return self.ram[addr]
        
        # KERNAL ROM
        if ROM_KERNAL_START <= addr < ROM_KERNAL_END:
            if self.ram[0x01] & 0x07 == 0x07:  # KERNAL ROM enabled
                if self.kernal_rom:
                    return self.kernal_rom[addr - ROM_KERNAL_START]
            return self.ram[addr]
        
        # RAM
        return self.ram[addr]
    
    def write(self, addr: int, value: int) -> None:
        """Write to memory (only RAM, ROM writes are ignored)"""
        addr &= 0xFFFF
        value &= 0xFF
        
        # Log memory writes if UDP debug is enabled (only screen writes to reduce overhead)
        if self.udp_debug and self.udp_debug.enabled:
            # Only log screen writes (most important for seeing output)
            if 0x0400 <= addr < 0x07E8:
                self.udp_debug.send('memory_write', {
                    'addr': addr,
                    'value': value
                })
        
        # ROM areas - writes go to RAM underneath
        if ROM_BASIC_START <= addr < ROM_BASIC_END:
            self.ram[addr] = value
        elif ROM_KERNAL_START <= addr < ROM_KERNAL_END:
            self.ram[addr] = value
        elif ROM_CHAR_START <= addr < ROM_CHAR_END:
            # I/O area
            if self.ram[0x01] & 0x03 == 0x03:  # I/O enabled
                self._write_io(addr, value)
            else:
                self.ram[addr] = value
        else:
            self.ram[addr] = value
    
    def _read_io(self, addr: int) -> int:
        """Read from I/O registers"""
        # VIC registers
        if VIC_BASE <= addr < VIC_BASE + 0x40:
            return self._read_vic(addr - VIC_BASE)
        
        # SID registers
        if SID_BASE <= addr < SID_BASE + 0x20:
            return 0  # SID not implemented yet
        
        # CIA1
        if CIA1_BASE <= addr < CIA1_BASE + 0x10:
            return self._read_cia1(addr - CIA1_BASE)
        
        # CIA2
        if CIA2_BASE <= addr < CIA2_BASE + 0x10:
            return self._read_cia2(addr - CIA2_BASE)
        
        return 0
    
    def _write_io(self, addr: int, value: int) -> None:
        """Write to I/O registers"""
        # VIC registers
        if VIC_BASE <= addr < VIC_BASE + 0x40:
            self._write_vic(addr - VIC_BASE, value)
            return
        
        # SID registers
        if SID_BASE <= addr < SID_BASE + 0x20:
            return  # SID not implemented yet
        
        # CIA1
        if CIA1_BASE <= addr < CIA1_BASE + 0x10:
            self._write_cia1(addr - CIA1_BASE, value)
            return
        
        # CIA2
        if CIA2_BASE <= addr < CIA2_BASE + 0x10:
            self._write_cia2(addr - CIA2_BASE, value)
            return
    
    def _read_vic(self, reg: int) -> int:
        """Read VIC-II register"""
        # Most VIC registers are write-only, return 0 for now
        return 0
    
    def _write_vic(self, reg: int, value: int) -> None:
        """Write VIC-II register"""
        # Store VIC register state
        if not hasattr(self, '_vic_regs'):
            self._vic_regs = bytearray(0x40)
        self._vic_regs[reg] = value
    
    def _read_cia1(self, reg: int) -> int:
        """Read CIA1 register"""
        # Timer A low byte
        if reg == 0x04:
            return self.cia1_timer_a.counter & 0xFF
        # Timer A high byte
        elif reg == 0x05:
            return (self.cia1_timer_a.counter >> 8) & 0xFF
        # Timer B low byte
        elif reg == 0x06:
            return self.cia1_timer_b.counter & 0xFF
        # Timer B high byte
        elif reg == 0x07:
            return (self.cia1_timer_b.counter >> 8) & 0xFF
        # Interrupt Control Register (ICR)
        elif reg == 0x0D:
            # Reading ICR acknowledges interrupts
            result = self.cia1_icr
            self.cia1_icr = 0
            self.pending_irq = False
            return result
        # Control Register A
        elif reg == 0x0E:
            result = 0
            if self.cia1_timer_a.running:
                result |= 0x01
            if self.cia1_timer_a.one_shot:
                result |= 0x08
            if self.cia1_timer_a.input_mode != 0:
                result |= (self.cia1_timer_a.input_mode << 5)
            return result
        # Control Register B
        elif reg == 0x0F:
            result = 0
            if self.cia1_timer_b.running:
                result |= 0x01
            if self.cia1_timer_b.one_shot:
                result |= 0x08
            if self.cia1_timer_b.input_mode != 0:
                result |= (self.cia1_timer_b.input_mode << 5)
            return result
        # Other registers (keyboard, joystick, etc.) - return 0 for now
        return 0
    
    def _write_cia1(self, reg: int, value: int) -> None:
        """Write CIA1 register"""
        # Timer A latch low byte
        if reg == 0x04:
            self.cia1_timer_a.latch = (self.cia1_timer_a.latch & 0xFF00) | value
            if not self.cia1_timer_a.running:
                self.cia1_timer_a.counter = (self.cia1_timer_a.counter & 0xFF00) | value
        # Timer A latch high byte
        elif reg == 0x05:
            self.cia1_timer_a.latch = (self.cia1_timer_a.latch & 0x00FF) | (value << 8)
            if not self.cia1_timer_a.running:
                self.cia1_timer_a.counter = (self.cia1_timer_a.counter & 0x00FF) | (value << 8)
        # Timer B latch low byte
        elif reg == 0x06:
            self.cia1_timer_b.latch = (self.cia1_timer_b.latch & 0xFF00) | value
            if not self.cia1_timer_b.running:
                self.cia1_timer_b.counter = (self.cia1_timer_b.counter & 0xFF00) | value
        # Timer B latch high byte
        elif reg == 0x07:
            self.cia1_timer_b.latch = (self.cia1_timer_b.latch & 0x00FF) | (value << 8)
            if not self.cia1_timer_b.running:
                self.cia1_timer_b.counter = (self.cia1_timer_b.counter & 0x00FF) | (value << 8)
        # Interrupt Control Register (ICR)
        elif reg == 0x0D:
            if value & 0x80:  # Set bits
                # Enable interrupts for bits set in lower 7 bits
                if value & 0x01:  # Timer A IRQ
                    self.cia1_timer_a.irq_enabled = True
                if value & 0x02:  # Timer B IRQ
                    self.cia1_timer_b.irq_enabled = True
            else:  # Clear bits
                if value & 0x01:  # Timer A IRQ
                    self.cia1_timer_a.irq_enabled = False
                if value & 0x02:  # Timer B IRQ
                    self.cia1_timer_b.irq_enabled = False
        # Control Register A
        elif reg == 0x0E:
            # Bit 0: Start/stop timer
            if value & 0x01:
                if not self.cia1_timer_a.running:
                    self.cia1_timer_a.counter = self.cia1_timer_a.latch
                self.cia1_timer_a.running = True
            else:
                self.cia1_timer_a.running = False
            # Bit 3: One-shot mode
            self.cia1_timer_a.one_shot = (value & 0x08) != 0
            # Bits 5-6: Input mode
            self.cia1_timer_a.input_mode = (value >> 5) & 0x03
        # Control Register B
        elif reg == 0x0F:
            # Bit 0: Start/stop timer
            if value & 0x01:
                if not self.cia1_timer_b.running:
                    self.cia1_timer_b.counter = self.cia1_timer_b.latch
                self.cia1_timer_b.running = True
            else:
                self.cia1_timer_b.running = False
            # Bit 3: One-shot mode
            self.cia1_timer_b.one_shot = (value & 0x08) != 0
            # Bits 5-6: Input mode
            self.cia1_timer_b.input_mode = (value >> 5) & 0x03
    
    def _read_cia2(self, reg: int) -> int:
        """Read CIA2 register"""
        # Serial bus, etc.
        return 0
    
    def _write_cia2(self, reg: int, value: int) -> None:
        """Write CIA2 register"""
        pass


class CPU6502:
    """6502 CPU emulator"""
    
    def __init__(self, memory: MemoryMap):
        self.memory = memory
        self.state = CPUState()
        # PC will be set from reset vector after ROMs are loaded
        # Don't read it here as ROMs might not be loaded yet
        self.state.pc = 0x0000
        
    def _read_word(self, addr: int) -> int:
        """Read 16-bit word (little-endian)"""
        low = self.memory.read(addr)
        high = self.memory.read((addr + 1) & 0xFFFF)
        return low | (high << 8)
    
    def _get_flag(self, flag: int) -> bool:
        """Get processor flag"""
        return (self.state.p & flag) != 0
    
    def _set_flag(self, flag: int, value: bool) -> None:
        """Set processor flag"""
        if value:
            self.state.p |= flag
        else:
            self.state.p &= ~flag
    
    def _update_flags(self, value: int) -> None:
        """Update Z and N flags based on value"""
        value &= 0xFF
        self._set_flag(0x02, value == 0)  # Z flag
        self._set_flag(0x80, (value & 0x80) != 0)  # N flag
    
    def step(self, udp_debug: Optional[UdpDebugLogger] = None) -> int:
        """Execute one instruction, return cycles"""
        if self.state.stopped:
            # If CPU is stopped (KIL), don't execute anything
            # Return 1 cycle to prevent infinite loops in the run loop
            return 1
        
        pc = self.state.pc
        opcode = self.memory.read(pc)
        
        # Log instruction execution if UDP debug is enabled (heavily sampled to reduce overhead)
        if udp_debug and udp_debug.enabled:
            # Only log every 1000th instruction or interesting addresses to reduce overhead
            # This reduces logging by 1000x while still capturing important events
            should_log = (
                (self.state.cycles % 10000 == 0) or  # Sample 0.01% of instructions
                (pc == 0xFFD2) or  # Always log CHROUT calls
                (pc == 0xFFCF) or  # CHRIN
                (pc == 0xFFE4) or  # GETIN
                (0xA000 <= pc < 0xA100)  # BASIC cold start area only
            )
            
            if should_log:
                # Minimal data to reduce JSON/serialization overhead
                udp_debug.send('cpu_step', {
                    'pc': pc,
                    'opcode': opcode,
                    'cycles': self.state.cycles
                })
        
        # Check if we're at a KERNAL vector that needs handling
        # CHRIN ($FFCF) - Input character from keyboard
        if pc == 0xFFCF:
            # CHRIN - return character from keyboard buffer
            # For now, return 0 (no input) so BASIC can continue
            # On boot, keyboard buffer should be empty
            kb_buf_len = self.memory.read(0xC6)  # Number of chars in buffer
            if kb_buf_len > 0:
                # Read from keyboard buffer
                kb_buf_ptr = self.memory.read(0xF7) | (self.memory.read(0xF8) << 8)
                if kb_buf_ptr == 0:
                    kb_buf_ptr = 0x0277  # Default keyboard buffer
                char = self.memory.read(kb_buf_ptr)
                # Remove from buffer
                kb_buf_len = (kb_buf_len - 1) & 0xFF
                self.memory.write(0xC6, kb_buf_len)
                self.memory.write(kb_buf_ptr, 0)  # Clear the character
                self.state.a = char
            else:
                # No input available - return 0
                self.state.a = 0
            
            # Return from JSR
            self.state.sp = (self.state.sp + 1) & 0xFF
            pc_low = self.memory.read(0x100 + self.state.sp)
            self.state.sp = (self.state.sp + 1) & 0xFF
            pc_high = self.memory.read(0x100 + self.state.sp)
            self.state.pc = ((pc_high << 8) | pc_low + 1) & 0xFFFF
            
            if udp_debug and udp_debug.enabled:
                udp_debug.send('chrin', {
                    'char': self.state.a,
                    'kb_buf_len': kb_buf_len
                })
            
            return 20  # Approximate cycles for CHRIN
        
        # CHROUT ($FFD2) - Output character to screen
        if pc == 0xFFD2:
            # This is CHROUT - character should be in accumulator
            char = self.state.a
            # Get cursor position from zero-page
            cursor_low = self.memory.read(0xD1)
            cursor_high = self.memory.read(0xD2)
            cursor_addr = cursor_low | (cursor_high << 8)
            
            # If cursor is 0 or invalid, start at screen base
            if cursor_addr < SCREEN_MEM or cursor_addr >= SCREEN_MEM + 1000:
                cursor_addr = SCREEN_MEM
            
            # Handle special characters
            if char == 0x0D:  # Carriage return
                # Move to start of next line
                row = (cursor_addr - SCREEN_MEM) // 40
                row = (row + 1) % 25
                cursor_addr = SCREEN_MEM + row * 40
            elif char == 0x93:  # Clear screen
                for addr in range(SCREEN_MEM, SCREEN_MEM + 1000):
                    self.memory.write(addr, 0x20)  # Space
                cursor_addr = SCREEN_MEM
            else:
                # Write character to screen
                if SCREEN_MEM <= cursor_addr < SCREEN_MEM + 1000:
                    self.memory.write(cursor_addr, char)
                    cursor_addr = (cursor_addr + 1) & 0xFFFF
                    # Wrap to next line if needed
                    if cursor_addr >= SCREEN_MEM + 1000:
                        cursor_addr = SCREEN_MEM
            
            # Update cursor position
            self.memory.write(0xD1, cursor_addr & 0xFF)
            self.memory.write(0xD2, (cursor_addr >> 8) & 0xFF)
            
            # Return from JSR (pop return address)
            self.state.sp = (self.state.sp + 1) & 0xFF
            pc_low = self.memory.read(0x100 + self.state.sp)
            self.state.sp = (self.state.sp + 1) & 0xFF
            pc_high = self.memory.read(0x100 + self.state.sp)
            self.state.pc = ((pc_high << 8) | pc_low + 1) & 0xFFFF
            
            # Log CHROUT call
            if udp_debug and udp_debug.enabled:
                udp_debug.send('chrout', {
                    'char': char,
                    'char_hex': f'${char:02X}',
                    'cursor_addr': cursor_addr,
                    'screen_addr': SCREEN_MEM
                })
            
            return 20  # Approximate cycles for CHROUT
        
        cycles = self._execute_opcode(opcode)
        self.state.cycles += cycles
        
        # Update CIA timers
        self._update_cia_timers(cycles)
        
        return cycles
    
    def _update_cia_timers(self, cycles: int) -> None:
        """Update CIA timers and check for IRQ"""
        # Update Timer A
        if self.memory.cia1_timer_a.update(cycles):
            self.memory.cia1_icr |= 0x01  # Timer A interrupt
            self.memory.cia1_icr |= 0x80  # IRQ flag
            self.memory.pending_irq = True
            self.memory.cia1_timer_a.reset()
        
        # Update Timer B (can be clocked by Timer A underflow)
        timer_a_underflow = False
        if self.memory.cia1_timer_a.counter <= 0 and self.memory.cia1_timer_a.running:
            timer_a_underflow = True
        
        if self.memory.cia1_timer_b.input_mode == 2:  # Timer A underflow mode
            if timer_a_underflow:
                if self.memory.cia1_timer_b.update(1):  # Count by 1
                    self.memory.cia1_icr |= 0x02  # Timer B interrupt
                    self.memory.cia1_icr |= 0x80  # IRQ flag
                    self.memory.pending_irq = True
                    self.memory.cia1_timer_b.reset()
        else:
            if self.memory.cia1_timer_b.update(cycles):
                self.memory.cia1_icr |= 0x02  # Timer B interrupt
                self.memory.cia1_icr |= 0x80  # IRQ flag
                self.memory.pending_irq = True
                self.memory.cia1_timer_b.reset()
    
    def _handle_irq(self, udp_debug: Optional[UdpDebugLogger] = None) -> None:
        """Handle IRQ interrupt"""
        # Clear pending IRQ flag before handling
        self.memory.pending_irq = False
        
        # Push PC and P to stack
        pc = self.state.pc
        self.memory.write(0x100 + self.state.sp, (pc >> 8) & 0xFF)
        self.state.sp = (self.state.sp - 1) & 0xFF
        self.memory.write(0x100 + self.state.sp, pc & 0xFF)
        self.state.sp = (self.state.sp - 1) & 0xFF
        self.memory.write(0x100 + self.state.sp, self.state.p | 0x10)  # Set B flag
        self.state.sp = (self.state.sp - 1) & 0xFF
        
        # Set interrupt disable flag
        self._set_flag(0x04, True)
        
        # Jump to IRQ vector
        irq_addr = self._read_word(IRQ_VECTOR)
        self.state.pc = irq_addr
        
        if udp_debug and udp_debug.enabled:
            udp_debug.send('irq', {
                'irq_addr': irq_addr,
                'irq_addr_hex': f'${irq_addr:04X}',
                'old_pc': pc,
                'old_pc_hex': f'${pc:04X}'
            })
    
    def _execute_opcode(self, opcode: int) -> int:
        """Execute opcode, return cycles"""
        # Complete 6502 opcode implementation
        
        # Load/Store instructions
        if opcode == 0xA9:  # LDA imm
            return self._lda_imm()
        elif opcode == 0xA5:  # LDA zp
            return self._lda_zp()
        elif opcode == 0xB5:  # LDA zpx
            return self._lda_zpx()
        elif opcode == 0xAD:  # LDA abs
            return self._lda_abs()
        elif opcode == 0xBD:  # LDA absx
            base = self._read_word(self.state.pc + 1)
            addr = (base + self.state.x) & 0xFFFF
            self.state.a = self.memory.read(addr)
            self._update_flags(self.state.a)
            self.state.pc = (self.state.pc + 3) & 0xFFFF
            return 4
        elif opcode == 0xB9:  # LDA absy
            return self._lda_absy()
        elif opcode == 0xA1:  # LDA indx
            return self._lda_indx()
        elif opcode == 0xB1:  # LDA indy
            return self._lda_indy()
        elif opcode == 0xA2:  # LDX imm
            return self._ldx_imm()
        elif opcode == 0xA6:  # LDX zp
            return self._ldx_zp()
        elif opcode == 0xAE:  # LDX abs
            return self._ldx_abs()
        elif opcode == 0xB6:  # LDX zpy
            zp_addr = (self.memory.read(self.state.pc + 1) + self.state.y) & 0xFF
            self.state.x = self.memory.read(zp_addr)
            self._update_flags(self.state.x)
            self.state.pc = (self.state.pc + 2) & 0xFFFF
            return 4
        elif opcode == 0xBE:  # LDX absy
            base = self._read_word(self.state.pc + 1)
            addr = (base + self.state.y) & 0xFFFF
            self.state.x = self.memory.read(addr)
            self._update_flags(self.state.x)
            self.state.pc = (self.state.pc + 3) & 0xFFFF
            return 4
        elif opcode == 0xA0:  # LDY imm
            return self._ldy_imm()
        elif opcode == 0xA4:  # LDY zp
            return self._ldy_zp()
        elif opcode == 0xAC:  # LDY abs
            return self._ldy_abs()
        elif opcode == 0x85:  # STA zp
            return self._sta_zp()
        elif opcode == 0x95:  # STA zpx
            return self._sta_zpx()
        elif opcode == 0x8D:  # STA abs
            return self._sta_abs()
        elif opcode == 0x9D:  # STA absx
            return self._sta_absx()
        elif opcode == 0x99:  # STA absy
            return self._sta_absy()
        elif opcode == 0x81:  # STA indx
            return self._sta_indx()
        elif opcode == 0x91:  # STA indy
            return self._sta_indy()
        elif opcode == 0x86:  # STX zp
            return self._stx_zp()
        elif opcode == 0x8E:  # STX abs
            return self._stx_abs()
        elif opcode == 0x84:  # STY zp
            return self._sty_zp()
        elif opcode == 0x8C:  # STY abs
            return self._sty_abs()
        
        # Arithmetic
        elif opcode == 0x69:  # ADC imm
            return self._adc_imm()
        elif opcode == 0x65:  # ADC zp
            return self._adc_zp()
        elif opcode == 0x6D:  # ADC abs
            return self._adc_abs()
        elif opcode == 0xE9:  # SBC imm
            return self._sbc_imm()
        elif opcode == 0xE5:  # SBC zp
            return self._sbc_zp()
        elif opcode == 0xE1:  # SBC indx
            zp_addr = (self.memory.read(self.state.pc + 1) + self.state.x) & 0xFF
            addr_low = self.memory.read(zp_addr)
            addr_high = self.memory.read((zp_addr + 1) & 0xFF)
            addr = addr_low | (addr_high << 8)
            value = self.memory.read(addr)
            carry = 1 if self._get_flag(0x01) else 0
            result = self.state.a - value - (1 - carry)
            self._set_flag(0x01, result >= 0)
            self._set_flag(0x40, ((self.state.a ^ value) & 0x80) != 0 and ((self.state.a ^ result) & 0x80) != 0)
            self.state.a = result & 0xFF
            self._update_flags(self.state.a)
            self.state.pc = (self.state.pc + 2) & 0xFFFF
            return 6
        elif opcode == 0xED:  # SBC abs
            return self._sbc_abs()
        elif opcode == 0xFD:  # SBC absx
            base = self._read_word(self.state.pc + 1)
            addr = (base + self.state.x) & 0xFFFF
            value = self.memory.read(addr)
            carry = 1 if self._get_flag(0x01) else 0
            result = self.state.a - value - (1 - carry)
            self._set_flag(0x01, result >= 0)
            self._set_flag(0x40, ((self.state.a ^ value) & 0x80) != 0 and ((self.state.a ^ result) & 0x80) != 0)
            self.state.a = result & 0xFF
            self._update_flags(self.state.a)
            self.state.pc = (self.state.pc + 3) & 0xFFFF
            return 4
        
        # Logic
        elif opcode == 0x29:  # AND imm
            return self._and_imm()
        elif opcode == 0x25:  # AND zp
            return self._and_zp()
        elif opcode == 0x2D:  # AND abs
            return self._and_abs()
        elif opcode == 0x09:  # ORA imm
            return self._ora_imm()
        elif opcode == 0x05:  # ORA zp
            return self._ora_zp()
        elif opcode == 0x0D:  # ORA abs
            return self._ora_abs()
        elif opcode == 0x49:  # EOR imm
            return self._eor_imm()
        elif opcode == 0x45:  # EOR zp
            return self._eor_zp()
        elif opcode == 0x4D:  # EOR abs
            return self._eor_abs()
        
        # Compare
        elif opcode == 0xC9:  # CMP imm
            return self._cmp_imm()
        elif opcode == 0xC5:  # CMP zp
            return self._cmp_zp()
        elif opcode == 0xCD:  # CMP abs
            return self._cmp_abs()
        elif opcode == 0xDD:  # CMP absx
            base = self._read_word(self.state.pc + 1)
            addr = (base + self.state.x) & 0xFFFF
            value = self.memory.read(addr)
            result = (self.state.a - value) & 0xFF
            self._set_flag(0x01, self.state.a >= value)
            self._update_flags(result)
            self.state.pc = (self.state.pc + 3) & 0xFFFF
            return 4
        elif opcode == 0xE0:  # CPX imm
            return self._cpx_imm()
        elif opcode == 0xE4:  # CPX zp
            return self._cpx_zp()
        elif opcode == 0xEC:  # CPX abs
            return self._cpx_abs()
        elif opcode == 0xC0:  # CPY imm
            return self._cpy_imm()
        elif opcode == 0xC4:  # CPY zp
            return self._cpy_zp()
        elif opcode == 0xCC:  # CPY abs
            return self._cpy_abs()
        elif opcode == 0xC1:  # CMP indx
            zp_addr = (self.memory.read(self.state.pc + 1) + self.state.x) & 0xFF
            addr = self.memory.read(zp_addr) | (self.memory.read((zp_addr + 1) & 0xFF) << 8)
            value = self.memory.read(addr)
            result = (self.state.a - value) & 0xFF
            self._set_flag(0x01, self.state.a >= value)
            self._update_flags(result)
            self.state.pc = (self.state.pc + 2) & 0xFFFF
            return 6
        elif opcode == 0xD1:  # CMP indy
            zp_addr = self.memory.read(self.state.pc + 1)
            base = self.memory.read(zp_addr) | (self.memory.read((zp_addr + 1) & 0xFF) << 8)
            addr = (base + self.state.y) & 0xFFFF
            value = self.memory.read(addr)
            result = (self.state.a - value) & 0xFF
            self._set_flag(0x01, self.state.a >= value)
            self._update_flags(result)
            self.state.pc = (self.state.pc + 2) & 0xFFFF
            return 5
        
        # Increment/Decrement
        elif opcode == 0xE6:  # INC zp
            return self._inc_zp()
        elif opcode == 0xEE:  # INC abs
            return self._inc_abs()
        elif opcode == 0xC6:  # DEC zp
            return self._dec_zp()
        elif opcode == 0xCE:  # DEC abs
            return self._dec_abs()
        elif opcode == 0xE8:  # INX
            return self._inx()
        elif opcode == 0xC8:  # INY
            return self._iny()
        elif opcode == 0xCA:  # DEX
            return self._dex()
        elif opcode == 0x88:  # DEY
            return self._dey()
        
        # Shifts
        elif opcode == 0x0A:  # ASL acc
            return self._asl_acc()
        elif opcode == 0x06:  # ASL zp
            return self._asl_zp()
        elif opcode == 0x0E:  # ASL abs
            return self._asl_abs()
        elif opcode == 0x4A:  # LSR acc
            return self._lsr_acc()
        elif opcode == 0x46:  # LSR zp
            return self._lsr_zp()
        elif opcode == 0x4E:  # LSR abs
            return self._lsr_abs()
        elif opcode == 0x2A:  # ROL acc
            return self._rol_acc()
        elif opcode == 0x26:  # ROL zp
            return self._rol_zp()
        elif opcode == 0x2E:  # ROL abs
            return self._rol_abs()
        elif opcode == 0x6A:  # ROR acc
            return self._ror_acc()
        elif opcode == 0x66:  # ROR zp
            return self._ror_zp()
        elif opcode == 0x6E:  # ROR abs
            return self._ror_abs()
        elif opcode == 0xFE:  # INC absx
            base = self._read_word(self.state.pc + 1)
            addr = (base + self.state.x) & 0xFFFF
            value = (self.memory.read(addr) + 1) & 0xFF
            self.memory.write(addr, value)
            self._update_flags(value)
            self.state.pc = (self.state.pc + 3) & 0xFFFF
            return 7
        
        # Branches
        elif opcode == 0x90:  # BCC
            return self._bcc()
        elif opcode == 0xB0:  # BCS
            return self._bcs()
        elif opcode == 0xF0:  # BEQ
            return self._beq()
        elif opcode == 0xD0:  # BNE
            return self._bne()
        elif opcode == 0x10:  # BPL
            return self._bpl()
        elif opcode == 0x30:  # BMI
            return self._bmi()
        elif opcode == 0x50:  # BVC
            return self._bvc()
        elif opcode == 0x70:  # BVS
            return self._bvs()
        
        # Jumps and Subroutines
        elif opcode == 0x4C:  # JMP abs
            return self._jmp_abs()
        elif opcode == 0x6C:  # JMP ind
            return self._jmp_ind()
        elif opcode == 0x20:  # JSR abs
            return self._jsr_abs()
        elif opcode == 0x60:  # RTS
            return self._rts()
        elif opcode == 0x40:  # RTI
            return self._rti()
        
        # Stack
        elif opcode == 0x48:  # PHA
            return self._pha()
        elif opcode == 0x68:  # PLA
            return self._pla()
        elif opcode == 0x08:  # PHP
            return self._php()
        elif opcode == 0x28:  # PLP
            return self._plp()
        elif opcode == 0x7A:  # PLY (undocumented - pull Y from stack)
            self.state.sp = (self.state.sp + 1) & 0xFF
            self.state.y = self.memory.read(0x100 + self.state.sp)
            self._update_flags(self.state.y)
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 4
        elif opcode == 0x7F:  # RRA absx (undocumented - ROR + ADC)
            base = self._read_word(self.state.pc + 1)
            addr = (base + self.state.x) & 0xFFFF
            value = self.memory.read(addr)
            carry = 1 if self._get_flag(0x01) else 0
            new_carry = (value & 0x01) != 0
            value = ((value >> 1) | (carry << 7)) & 0xFF
            self.memory.write(addr, value)
            self._set_flag(0x01, new_carry)
            # ADC part
            carry = 1 if self._get_flag(0x01) else 0
            result = self.state.a + value + carry
            self._set_flag(0x01, result > 0xFF)
            self.state.a = result & 0xFF
            self._update_flags(self.state.a)
            self.state.pc = (self.state.pc + 3) & 0xFFFF
            return 7
        elif opcode == 0xBF:  # LAX absy (undocumented - LDA + TAX)
            base = self._read_word(self.state.pc + 1)
            addr = (base + self.state.y) & 0xFFFF
            self.state.a = self.memory.read(addr)
            self.state.x = self.state.a
            self._update_flags(self.state.a)
            self.state.pc = (self.state.pc + 3) & 0xFFFF
            return 4
        elif opcode == 0xFF:  # ISC absx (undocumented - increment memory, then subtract with carry)
            base = self._read_word(self.state.pc + 1)
            addr = (base + self.state.x) & 0xFFFF
            value = (self.memory.read(addr) + 1) & 0xFF
            self.memory.write(addr, value)
            # SBC part
            carry = 1 if self._get_flag(0x01) else 0
            result = self.state.a - value - (1 - carry)
            self._set_flag(0x01, result >= 0)
            self._set_flag(0x40, ((self.state.a ^ value) & 0x80) != 0 and ((self.state.a ^ result) & 0x80) != 0)
            self.state.a = result & 0xFF
            self._update_flags(self.state.a)
            self.state.pc = (self.state.pc + 3) & 0xFFFF
            return 7
        
        # Transfers
        elif opcode == 0xAA:  # TAX
            return self._tax()
        elif opcode == 0xA8:  # TAY
            return self._tay()
        elif opcode == 0x8A:  # TXA
            return self._txa()
        elif opcode == 0x98:  # TYA
            return self._tya()
        elif opcode == 0xBA:  # TSX
            return self._tsx()
        elif opcode == 0x9A:  # TXS
            self.state.sp = self.state.x
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 2
        
        # Flags
        elif opcode == 0x18:  # CLC
            self._set_flag(0x01, False)
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 2
        elif opcode == 0x38:  # SEC
            self._set_flag(0x01, True)
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 2
        elif opcode == 0x58:  # CLI
            self._set_flag(0x04, False)
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 2
        elif opcode == 0x78:  # SEI
            self._set_flag(0x04, True)
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 2
        elif opcode == 0xD8:  # CLD
            self._set_flag(0x08, False)
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 2
        elif opcode == 0xF8:  # SED
            self._set_flag(0x08, True)
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 2
        elif opcode == 0xB8:  # CLV
            self._set_flag(0x40, False)
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 2
        
        # Other
        elif opcode == 0x00:  # BRK
            return self._brk()
        elif opcode == 0x02:  # KIL (undocumented - kill processor, halts CPU)
            # KIL halts the processor - set stopped flag
            self.state.stopped = True
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 0
        elif opcode == 0xEA:  # NOP
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 2
        # NOP variants (documented and undocumented)
        elif opcode in [0x80, 0x82, 0x89, 0xC2, 0xE2]:  # NOP imm (documented - consume 1 byte operand)
            self.state.pc = (self.state.pc + 2) & 0xFFFF
            return 2
        elif opcode in [0x04, 0x44, 0x64]:  # NOP zp (undocumented - consume 1 byte operand)
            self.state.pc = (self.state.pc + 2) & 0xFFFF
            return 3
        elif opcode in [0x14, 0x1C, 0x3C, 0x5C, 0x7C, 0xDC, 0xFC]:  # NOP absx (undocumented - consume 2 byte operand)
            self.state.pc = (self.state.pc + 3) & 0xFFFF
            return 4
        elif opcode == 0x24:  # BIT zp
            return self._bit_zp()
        elif opcode == 0x2C:  # BIT abs
            return self._bit_abs()
        else:
            # Unknown opcode - just advance PC (this shouldn't happen with valid C64 code)
            print(f"Warning: Unknown opcode ${opcode:02X} at PC=${self.state.pc:04X}")
            # Advance PC by 1 byte (minimum instruction size)
            self.state.pc = (self.state.pc + 1) & 0xFFFF
            return 2
    
    def _brk(self) -> int:
        """BRK instruction"""
        # Push PC+2 and P onto stack
        pc_high = (self.state.pc + 2) >> 8
        pc_low = (self.state.pc + 2) & 0xFF
        self.memory.write(0x100 + self.state.sp, pc_high)
        self.state.sp = (self.state.sp - 1) & 0xFF
        self.memory.write(0x100 + self.state.sp, pc_low)
        self.state.sp = (self.state.sp - 1) & 0xFF
        self.memory.write(0x100 + self.state.sp, self.state.p | 0x10)  # Set B flag
        self.state.sp = (self.state.sp - 1) & 0xFF
        self._set_flag(0x04, True)  # Set I flag
        self.state.pc = self._read_word(0xFFFE)  # IRQ vector
        return 7
    
    def _jmp_abs(self) -> int:
        """JMP absolute"""
        addr = self._read_word(self.state.pc + 1)
        self.state.pc = addr
        return 3
    
    def _jsr_abs(self) -> int:
        """JSR absolute"""
        addr = self._read_word(self.state.pc + 1)
        # Push return address - 1 onto stack
        return_addr = (self.state.pc + 2) & 0xFFFF
        pc_high = (return_addr - 1) >> 8
        pc_low = (return_addr - 1) & 0xFF
        self.memory.write(0x100 + self.state.sp, pc_high)
        self.state.sp = (self.state.sp - 1) & 0xFF
        self.memory.write(0x100 + self.state.sp, pc_low)
        self.state.sp = (self.state.sp - 1) & 0xFF
        self.state.pc = addr
        return 6
    
    def _rts(self) -> int:
        """RTS"""
        self.state.sp = (self.state.sp + 1) & 0xFF
        pc_low = self.memory.read(0x100 + self.state.sp)
        self.state.sp = (self.state.sp + 1) & 0xFF
        pc_high = self.memory.read(0x100 + self.state.sp)
        self.state.pc = ((pc_high << 8) | pc_low + 1) & 0xFFFF
        return 6
    
    def _lda_imm(self) -> int:
        """LDA immediate"""
        self.state.a = self.memory.read(self.state.pc + 1)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 2
    
    def _lda_zp(self) -> int:
        """LDA zero page"""
        zp_addr = self.memory.read(self.state.pc + 1)
        self.state.a = self.memory.read(zp_addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _lda_abs(self) -> int:
        """LDA absolute"""
        addr = self._read_word(self.state.pc + 1)
        self.state.a = self.memory.read(addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    def _sta_zp(self) -> int:
        """STA zero page"""
        zp_addr = self.memory.read(self.state.pc + 1)
        self.memory.write(zp_addr, self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _sta_abs(self) -> int:
        """STA absolute"""
        addr = self._read_word(self.state.pc + 1)
        self.memory.write(addr, self.state.a)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    # Additional opcode implementations (simplified - add more as needed)
    def _lda_zpx(self) -> int:
        zp_addr = (self.memory.read(self.state.pc + 1) + self.state.x) & 0xFF
        self.state.a = self.memory.read(zp_addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 4
    
    def _lda_absx(self) -> int:
        base = self._read_word(self.state.pc + 1)
        addr = (base + self.state.x) & 0xFFFF
        self.state.a = self.memory.read(addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    def _lda_absy(self) -> int:
        base = self._read_word(self.state.pc + 1)
        addr = (base + self.state.y) & 0xFFFF
        self.state.a = self.memory.read(addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    def _lda_indx(self) -> int:
        zp_addr = (self.memory.read(self.state.pc + 1) + self.state.x) & 0xFF
        addr = self.memory.read(zp_addr) | (self.memory.read((zp_addr + 1) & 0xFF) << 8)
        self.state.a = self.memory.read(addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 6
    
    def _lda_indy(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        base = self.memory.read(zp_addr) | (self.memory.read((zp_addr + 1) & 0xFF) << 8)
        addr = (base + self.state.y) & 0xFFFF
        self.state.a = self.memory.read(addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 5
    
    def _ldx_imm(self) -> int:
        self.state.x = self.memory.read(self.state.pc + 1)
        self._update_flags(self.state.x)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 2
    
    def _ldx_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        self.state.x = self.memory.read(zp_addr)
        self._update_flags(self.state.x)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _ldx_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        self.state.x = self.memory.read(addr)
        self._update_flags(self.state.x)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    def _ldy_imm(self) -> int:
        self.state.y = self.memory.read(self.state.pc + 1)
        self._update_flags(self.state.y)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 2
    
    def _ldy_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        self.state.y = self.memory.read(zp_addr)
        self._update_flags(self.state.y)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _ldy_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        self.state.y = self.memory.read(addr)
        self._update_flags(self.state.y)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    def _sta_zpx(self) -> int:
        zp_addr = (self.memory.read(self.state.pc + 1) + self.state.x) & 0xFF
        self.memory.write(zp_addr, self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 4
    
    def _sta_absx(self) -> int:
        base = self._read_word(self.state.pc + 1)
        addr = (base + self.state.x) & 0xFFFF
        self.memory.write(addr, self.state.a)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 5
    
    def _sta_absy(self) -> int:
        base = self._read_word(self.state.pc + 1)
        addr = (base + self.state.y) & 0xFFFF
        self.memory.write(addr, self.state.a)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 5
    
    def _sta_indx(self) -> int:
        zp_addr = (self.memory.read(self.state.pc + 1) + self.state.x) & 0xFF
        addr = self.memory.read(zp_addr) | (self.memory.read((zp_addr + 1) & 0xFF) << 8)
        self.memory.write(addr, self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 6
    
    def _sta_indy(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        base = self.memory.read(zp_addr) | (self.memory.read((zp_addr + 1) & 0xFF) << 8)
        addr = (base + self.state.y) & 0xFFFF
        self.memory.write(addr, self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 6
    
    def _stx_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        self.memory.write(zp_addr, self.state.x)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _stx_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        self.memory.write(addr, self.state.x)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    def _sty_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        self.memory.write(zp_addr, self.state.y)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _sty_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        self.memory.write(addr, self.state.y)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    # Arithmetic operations (simplified)
    def _adc_imm(self) -> int:
        value = self.memory.read(self.state.pc + 1)
        carry = 1 if self._get_flag(0x01) else 0
        result = self.state.a + value + carry
        self._set_flag(0x01, result > 0xFF)
        self.state.a = result & 0xFF
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 2
    
    def _adc_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = self.memory.read(zp_addr)
        carry = 1 if self._get_flag(0x01) else 0
        result = self.state.a + value + carry
        self._set_flag(0x01, result > 0xFF)
        self.state.a = result & 0xFF
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _adc_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = self.memory.read(addr)
        carry = 1 if self._get_flag(0x01) else 0
        result = self.state.a + value + carry
        self._set_flag(0x01, result > 0xFF)
        self.state.a = result & 0xFF
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    def _sbc_imm(self) -> int:
        value = self.memory.read(self.state.pc + 1)
        carry = 1 if self._get_flag(0x01) else 0
        result = self.state.a - value - (1 - carry)
        self._set_flag(0x01, result >= 0)
        self.state.a = result & 0xFF
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 2
    
    def _sbc_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = self.memory.read(zp_addr)
        carry = 1 if self._get_flag(0x01) else 0
        result = self.state.a - value - (1 - carry)
        self._set_flag(0x01, result >= 0)
        # Set overflow flag
        self._set_flag(0x40, ((self.state.a ^ value) & 0x80) != 0 and ((self.state.a ^ result) & 0x80) != 0)
        self.state.a = result & 0xFF
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _sbc_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = self.memory.read(addr)
        carry = 1 if self._get_flag(0x01) else 0
        result = self.state.a - value - (1 - carry)
        self._set_flag(0x01, result >= 0)
        self.state.a = result & 0xFF
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    # Logic operations
    def _and_imm(self) -> int:
        self.state.a &= self.memory.read(self.state.pc + 1)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 2
    
    def _and_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        self.state.a &= self.memory.read(zp_addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _and_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        self.state.a &= self.memory.read(addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    def _ora_imm(self) -> int:
        self.state.a |= self.memory.read(self.state.pc + 1)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 2
    
    def _ora_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        self.state.a |= self.memory.read(zp_addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _ora_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        self.state.a |= self.memory.read(addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    def _eor_imm(self) -> int:
        self.state.a ^= self.memory.read(self.state.pc + 1)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 2
    
    def _eor_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        self.state.a ^= self.memory.read(zp_addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _eor_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        self.state.a ^= self.memory.read(addr)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    # Compare operations
    def _cmp_imm(self) -> int:
        value = self.memory.read(self.state.pc + 1)
        result = (self.state.a - value) & 0xFF
        self._set_flag(0x01, self.state.a >= value)
        self._update_flags(result)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 2
    
    def _cmp_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = self.memory.read(zp_addr)
        result = (self.state.a - value) & 0xFF
        self._set_flag(0x01, self.state.a >= value)
        self._update_flags(result)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _cmp_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = self.memory.read(addr)
        result = (self.state.a - value) & 0xFF
        self._set_flag(0x01, self.state.a >= value)
        self._update_flags(result)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    def _cpx_imm(self) -> int:
        value = self.memory.read(self.state.pc + 1)
        result = (self.state.x - value) & 0xFF
        self._set_flag(0x01, self.state.x >= value)
        self._update_flags(result)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 2
    
    def _cpx_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = self.memory.read(zp_addr)
        result = (self.state.x - value) & 0xFF
        self._set_flag(0x01, self.state.x >= value)
        self._update_flags(result)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _cpx_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = self.memory.read(addr)
        result = (self.state.x - value) & 0xFF
        self._set_flag(0x01, self.state.x >= value)
        self._update_flags(result)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    def _cpy_imm(self) -> int:
        value = self.memory.read(self.state.pc + 1)
        result = (self.state.y - value) & 0xFF
        self._set_flag(0x01, self.state.y >= value)
        self._update_flags(result)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 2
    
    def _cpy_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = self.memory.read(zp_addr)
        result = (self.state.y - value) & 0xFF
        self._set_flag(0x01, self.state.y >= value)
        self._update_flags(result)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _cpy_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = self.memory.read(addr)
        result = (self.state.y - value) & 0xFF
        self._set_flag(0x01, self.state.y >= value)
        self._update_flags(result)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4
    
    # Increment/Decrement
    def _inc_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = (self.memory.read(zp_addr) + 1) & 0xFF
        self.memory.write(zp_addr, value)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 5
    
    def _inc_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = (self.memory.read(addr) + 1) & 0xFF
        self.memory.write(addr, value)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 6
    
    def _dec_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = (self.memory.read(zp_addr) - 1) & 0xFF
        self.memory.write(zp_addr, value)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 5
    
    def _dec_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = (self.memory.read(addr) - 1) & 0xFF
        self.memory.write(addr, value)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 6
    
    def _inx(self) -> int:
        self.state.x = (self.state.x + 1) & 0xFF
        self._update_flags(self.state.x)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _iny(self) -> int:
        self.state.y = (self.state.y + 1) & 0xFF
        self._update_flags(self.state.y)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _dex(self) -> int:
        self.state.x = (self.state.x - 1) & 0xFF
        self._update_flags(self.state.x)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _dey(self) -> int:
        self.state.y = (self.state.y - 1) & 0xFF
        self._update_flags(self.state.y)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    # Shifts
    def _asl_acc(self) -> int:
        self._set_flag(0x01, (self.state.a & 0x80) != 0)
        self.state.a = (self.state.a << 1) & 0xFF
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _asl_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = self.memory.read(zp_addr)
        self._set_flag(0x01, (value & 0x80) != 0)
        value = (value << 1) & 0xFF
        self.memory.write(zp_addr, value)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 5
    
    def _asl_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = self.memory.read(addr)
        self._set_flag(0x01, (value & 0x80) != 0)
        value = (value << 1) & 0xFF
        self.memory.write(addr, value)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 6
    
    def _lsr_acc(self) -> int:
        self._set_flag(0x01, (self.state.a & 0x01) != 0)
        self.state.a = (self.state.a >> 1) & 0xFF
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _lsr_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = self.memory.read(zp_addr)
        self._set_flag(0x01, (value & 0x01) != 0)
        value = (value >> 1) & 0xFF
        self.memory.write(zp_addr, value)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 5
    
    def _lsr_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = self.memory.read(addr)
        self._set_flag(0x01, (value & 0x01) != 0)
        value = (value >> 1) & 0xFF
        self.memory.write(addr, value)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 6
    
    def _rol_acc(self) -> int:
        carry = 1 if self._get_flag(0x01) else 0
        new_carry = (self.state.a & 0x80) != 0
        self.state.a = ((self.state.a << 1) | carry) & 0xFF
        self._set_flag(0x01, new_carry)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _rol_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = self.memory.read(zp_addr)
        carry = 1 if self._get_flag(0x01) else 0
        new_carry = (value & 0x80) != 0
        value = ((value << 1) | carry) & 0xFF
        self.memory.write(zp_addr, value)
        self._set_flag(0x01, new_carry)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 5
    
    def _rol_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = self.memory.read(addr)
        carry = 1 if self._get_flag(0x01) else 0
        new_carry = (value & 0x80) != 0
        value = ((value << 1) | carry) & 0xFF
        self.memory.write(addr, value)
        self._set_flag(0x01, new_carry)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 6
    
    def _ror_acc(self) -> int:
        carry = 1 if self._get_flag(0x01) else 0
        new_carry = (self.state.a & 0x01) != 0
        self.state.a = ((self.state.a >> 1) | (carry << 7)) & 0xFF
        self._set_flag(0x01, new_carry)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _ror_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = self.memory.read(zp_addr)
        carry = 1 if self._get_flag(0x01) else 0
        new_carry = (value & 0x01) != 0
        value = ((value >> 1) | (carry << 7)) & 0xFF
        self.memory.write(zp_addr, value)
        self._set_flag(0x01, new_carry)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 5
    
    def _ror_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = self.memory.read(addr)
        carry = 1 if self._get_flag(0x01) else 0
        new_carry = (value & 0x01) != 0
        value = ((value >> 1) | (carry << 7)) & 0xFF
        self.memory.write(addr, value)
        self._set_flag(0x01, new_carry)
        self._update_flags(value)
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 6
    
    # Branches
    def _bcc(self) -> int:
        return self._branch(not self._get_flag(0x01))
    
    def _bcs(self) -> int:
        return self._branch(self._get_flag(0x01))
    
    def _beq(self) -> int:
        return self._branch(self._get_flag(0x02))
    
    def _bne(self) -> int:
        return self._branch(not self._get_flag(0x02))
    
    def _bpl(self) -> int:
        return self._branch(not self._get_flag(0x80))
    
    def _bmi(self) -> int:
        return self._branch(self._get_flag(0x80))
    
    def _bvc(self) -> int:
        return self._branch(not self._get_flag(0x40))
    
    def _bvs(self) -> int:
        return self._branch(self._get_flag(0x40))
    
    def _branch(self, condition: bool) -> int:
        """Branch if condition is true"""
        offset = self.memory.read(self.state.pc + 1)
        if offset & 0x80:
            offset = offset - 256
        if condition:
            self.state.pc = (self.state.pc + 2 + offset) & 0xFFFF
            return 3
        else:
            self.state.pc = (self.state.pc + 2) & 0xFFFF
            return 2
    
    # Jumps
    def _jmp_ind(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        # Handle page boundary bug
        if (addr & 0xFF) == 0xFF:
            low = self.memory.read(addr)
            high = self.memory.read(addr & 0xFF00)
        else:
            low = self.memory.read(addr)
            high = self.memory.read(addr + 1)
        self.state.pc = low | (high << 8)
        return 5
    
    # Stack operations
    def _pha(self) -> int:
        self.memory.write(0x100 + self.state.sp, self.state.a)
        self.state.sp = (self.state.sp - 1) & 0xFF
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 3
    
    def _pla(self) -> int:
        self.state.sp = (self.state.sp + 1) & 0xFF
        self.state.a = self.memory.read(0x100 + self.state.sp)
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 4
    
    def _php(self) -> int:
        self.memory.write(0x100 + self.state.sp, self.state.p | 0x10)  # Set B flag
        self.state.sp = (self.state.sp - 1) & 0xFF
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 3
    
    def _plp(self) -> int:
        self.state.sp = (self.state.sp + 1) & 0xFF
        self.state.p = self.memory.read(0x100 + self.state.sp) & 0xEF  # Clear B flag
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 4
    
    # Transfers
    def _tax(self) -> int:
        self.state.x = self.state.a
        self._update_flags(self.state.x)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _tay(self) -> int:
        self.state.y = self.state.a
        self._update_flags(self.state.y)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _txa(self) -> int:
        self.state.a = self.state.x
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _tya(self) -> int:
        self.state.a = self.state.y
        self._update_flags(self.state.a)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _tsx(self) -> int:
        self.state.x = self.state.sp
        self._update_flags(self.state.x)
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    def _txs(self) -> int:
        self.state.sp = self.state.x
        self.state.pc = (self.state.pc + 1) & 0xFFFF
        return 2
    
    # Other
    def _rti(self) -> int:
        self.state.sp = (self.state.sp + 1) & 0xFF
        self.state.p = self.memory.read(0x100 + self.state.sp) & 0xEF
        self.state.sp = (self.state.sp + 1) & 0xFF
        pc_low = self.memory.read(0x100 + self.state.sp)
        self.state.sp = (self.state.sp + 1) & 0xFF
        pc_high = self.memory.read(0x100 + self.state.sp)
        self.state.pc = (pc_low | (pc_high << 8)) & 0xFFFF
        return 6
    
    def _bit_zp(self) -> int:
        zp_addr = self.memory.read(self.state.pc + 1)
        value = self.memory.read(zp_addr)
        self._set_flag(0x40, (value & 0x40) != 0)  # V flag
        self._set_flag(0x80, (value & 0x80) != 0)  # N flag
        self._set_flag(0x02, (self.state.a & value) == 0)  # Z flag
        self.state.pc = (self.state.pc + 2) & 0xFFFF
        return 3
    
    def _bit_abs(self) -> int:
        addr = self._read_word(self.state.pc + 1)
        value = self.memory.read(addr)
        self._set_flag(0x40, (value & 0x40) != 0)  # V flag
        self._set_flag(0x80, (value & 0x80) != 0)  # N flag
        self._set_flag(0x02, (self.state.a & value) == 0)  # Z flag
        self.state.pc = (self.state.pc + 3) & 0xFFFF
        return 4


class UdpDebugLogger:
    """UDP debug logger for tracing emulator execution (async)"""
    
    def __init__(self, port: int = 64738, host: str = "127.0.0.1"):
        self.port = port
        self.host = host
        self.sock = None
        self.enabled = False
        self.queue = queue.Queue(maxsize=10000)  # Buffer up to 10k events
        self.worker_thread = None
        self.running = False
        
    def enable(self) -> None:
        """Enable UDP debug logging"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.enabled = True
            self.running = True
            # Start worker thread for async sending
            self.worker_thread = threading.Thread(target=self._worker, daemon=True)
            self.worker_thread.start()
        except Exception as e:
            print(f"Warning: Failed to create UDP socket for debug: {e}", file=sys.stderr)
            self.enabled = False
    
    def _worker(self) -> None:
        """Worker thread that sends UDP messages asynchronously"""
        while self.running:
            try:
                # Get message from queue with timeout
                message = self.queue.get(timeout=0.1)
                if message is None:  # Shutdown signal
                    break
                self.sock.sendto(message, (self.host, self.port))
                self.queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                pass  # Silently ignore UDP errors
    
    def send(self, event_type: str, data: Dict) -> None:
        """Queue debug event for async sending (non-blocking)"""
        if not self.enabled:
            return
        
        try:
            message = {
                'timestamp': datetime.now().isoformat(),
                'type': event_type,
                'data': data
            }
            json_msg = json.dumps(message)
            message_bytes = json_msg.encode('utf-8') + b"\n"
            
            # Try to put in queue (non-blocking if queue is full)
            try:
                self.queue.put_nowait(message_bytes)
            except queue.Full:
                # Queue is full, drop oldest message and add new one
                try:
                    self.queue.get_nowait()
                    self.queue.put_nowait(message_bytes)
                except queue.Empty:
                    pass
        except Exception:
            pass  # Silently ignore errors
    
    def close(self) -> None:
        """Close UDP socket and stop worker thread"""
        self.running = False
        if self.queue:
            try:
                self.queue.put_nowait(None)  # Signal shutdown
            except queue.Full:
                pass
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
            self.enabled = False


class C64Emulator:
    """Main C64 emulator"""
    
    def __init__(self):
        self.memory = MemoryMap()
        self.cpu = CPU6502(self.memory)
        self.running = False
        self.text_screen = [[' '] * 40 for _ in range(25)]
        self.text_colors = [[7] * 40 for _ in range(25)]  # Default: yellow on blue
        self.debug = False
        self.udp_debug = None  # Will be set if UDP debugging is enabled
        self.screen_update_thread = None
        self.screen_update_interval = 0.1  # Update screen every 100ms
        self.screen_lock = threading.Lock()
        
    def load_roms(self, rom_dir: str = "lib/assets") -> None:
        """Load C64 ROM files"""
        import os
        
        # Load BASIC ROM
        basic_path = os.path.join(rom_dir, "basic.901226-01.bin")
        if os.path.exists(basic_path):
            with open(basic_path, "rb") as f:
                self.memory.basic_rom = f.read()
                print(f"Loaded BASIC ROM: {len(self.memory.basic_rom)} bytes")
        else:
            print(f"Warning: BASIC ROM not found at {basic_path}")
        
        # Load KERNAL ROM
        kernal_path = os.path.join(rom_dir, "kernal.901227-03.bin")
        if os.path.exists(kernal_path):
            with open(kernal_path, "rb") as f:
                self.memory.kernal_rom = f.read()
                print(f"Loaded KERNAL ROM: {len(self.memory.kernal_rom)} bytes")
            # Set reset vector in RAM (KERNAL ROM has it at $FFFC-$FFFD)
            if len(self.memory.kernal_rom) >= (0x10000 - ROM_KERNAL_START):
                reset_offset = 0xFFFC - ROM_KERNAL_START
                reset_low = self.memory.kernal_rom[reset_offset]
                reset_high = self.memory.kernal_rom[reset_offset + 1]
                self.memory.ram[0xFFFC] = reset_low
                self.memory.ram[0xFFFD] = reset_high
                print(f"Reset vector: ${reset_high:02X}{reset_low:02X}")
        else:
            print(f"Warning: KERNAL ROM not found at {kernal_path}")
        
        # Load Character ROM
        char_path = os.path.join(rom_dir, "characters.901225-01.bin")
        if os.path.exists(char_path):
            with open(char_path, "rb") as f:
                self.memory.char_rom = f.read()
                print(f"Loaded Character ROM: {len(self.memory.char_rom)} bytes")
        else:
            print(f"Warning: Character ROM not found at {char_path}")
        
        # Initialize C64 state
        self._initialize_c64()
        
        # Set CPU PC from reset vector (after ROMs are loaded and memory is initialized)
        reset_low = self.memory.read(0xFFFC)
        reset_high = self.memory.read(0xFFFD)
        reset_addr = reset_low | (reset_high << 8)
        self.cpu.state.pc = reset_addr
        print(f"CPU reset vector: ${reset_addr:04X}")
    
    def _initialize_c64(self) -> None:
        """Initialize C64 to a known state"""
        # Memory configuration register ($01)
        # Bits 0-2: Memory configuration
        # 0x37 = %00110111 = BASIC ROM + KERNAL ROM + I/O enabled
        self.memory.ram[0x01] = 0x37
        
        # Initialize screen memory with spaces (don't pre-fill - let KERNAL/BASIC do it)
        # The C64 typically clears screen during initialization
        for addr in range(SCREEN_MEM, SCREEN_MEM + 1000):
            self.memory.ram[addr] = 0x20  # Space character
        
        # Initialize color memory (default: light blue = 14, but we'll use white = 1)
        for addr in range(COLOR_MEM, COLOR_MEM + 1000):
            self.memory.ram[addr] = 1  # White
        
        # Initialize VIC registers (simplified)
        # VIC register $D018: Screen and character memory
        # Bit 1-3: Screen memory (default $0400 = %000 = 0)
        # Bit 4-7: Character memory (default $1000 = %010 = 2)
        # So $D018 = %00010000 = $10
        if hasattr(self.memory, '_vic_regs'):
            self.memory._vic_regs[0x18] = 0x10  # Screen at $0400, chars at $1000
        
        # Initialize stack pointer
        self.cpu.state.sp = 0xFF
        
        # Initialize zero-page variables used by KERNAL
        # $C3-$C4: Temporary pointer used by vector copy routine
        # Typically initialized to point to RAM vector area (0x0314)
        self.memory.ram[0xC3] = 0x14  # Temporary pointer (low)
        self.memory.ram[0xC4] = 0x03  # Temporary pointer (high) - points to $0314
        
        # Initialize some zero-page variables
        self.memory.ram[0x0288] = 0x0E  # Cursor color (light blue)
        self.memory.ram[0x0286] = 0x0E  # Background color (light blue)
        
        # Initialize cursor position (points to screen start)
        self.memory.ram[0xD1] = SCREEN_MEM & 0xFF  # Cursor column (low byte)
        self.memory.ram[0xD2] = (SCREEN_MEM >> 8) & 0xFF  # Cursor row (high byte)
        
        # Initialize KERNAL reset vector at $8000-$8001 to point to BASIC cold start
        # The KERNAL does JMP ($8000) to jump to BASIC after initialization
        # BASIC cold start is typically at $A483 (standard C64 BASIC entry point)
        basic_cold_start = 0xA483
        self.memory.ram[0x8000] = basic_cold_start & 0xFF
        self.memory.ram[0x8001] = (basic_cold_start >> 8) & 0xFF
        
        # Initialize BASIC pointers for empty program
        basic_start = 0x0801
        self.memory.ram[0x002B] = basic_start & 0xFF
        self.memory.ram[0x002C] = (basic_start >> 8) & 0xFF
        self.memory.ram[0x002D] = basic_start & 0xFF
        self.memory.ram[0x002E] = (basic_start >> 8) & 0xFF
        self.memory.ram[0x002F] = basic_start & 0xFF
        self.memory.ram[0x0030] = (basic_start >> 8) & 0xFF
        self.memory.ram[0x0031] = basic_start & 0xFF
        self.memory.ram[0x0032] = (basic_start >> 8) & 0xFF
        self.memory.ram[0x0033] = basic_start & 0xFF
        self.memory.ram[0x0034] = (basic_start >> 8) & 0xFF
        
        # Mark end of BASIC program (empty program marker)
        self.memory.ram[0x0801] = 0x00
        self.memory.ram[0x0802] = 0x00
        
        # Initialize keyboard buffer
        self.memory.ram[0xC6] = 0  # Number of characters in buffer
        
        # Initialize zero-page status register $6C (used by KERNAL error handler)
        # This is typically initialized to 0 on boot
        # The KERNAL checks this at $FE6E with SBC $6C - if result is 0, it halts
        self.memory.ram[0x6C] = 0  # Status register (typically 0 = no error)
        
        # Initialize KERNAL vectors to defaults
        # These are typically set by KERNAL during boot, but we initialize them here
        # to prevent infinite loops if KERNAL doesn't set them
        
        # IRQ vector ($0314) - points to KERNAL IRQ handler
        self.memory.ram[0x0314] = 0x31
        self.memory.ram[0x0315] = 0xEA  # $EA31
        
        # BRK vector ($0316) - points to KERNAL BRK handler  
        # BRK handler is typically at $FE66 in KERNAL ROM
        self.memory.ram[0x0316] = 0x66
        self.memory.ram[0x0317] = 0xFE  # $FE66
        
        # NMI vector ($0318) - points to KERNAL NMI handler
        # NMI handler is typically at $FE47 in KERNAL ROM
        self.memory.ram[0x0318] = 0x47
        self.memory.ram[0x0319] = 0xFE  # $FE47
        
        # Initialize CIA1 timers (typical C64 boot values)
        # Timer A is often used for jiffy clock (60Hz = ~16666 cycles at 1MHz)
        # For now, set to a reasonable default
        self.memory.cia1_timer_a.latch = 0xFFFF
        self.memory.cia1_timer_a.counter = 0xFFFF
        self.memory.cia1_timer_b.latch = 0xFFFF
        self.memory.cia1_timer_b.counter = 0xFFFF
        
        print("C64 initialized")
    
    def load_prg(self, prg_path: str) -> None:
        """Load a PRG file into memory"""
        with open(prg_path, "rb") as f:
            data = f.read()
        
        if len(data) < 2:
            raise ValueError("PRG file too small")
        
        load_addr = data[0] | (data[1] << 8)
        prg_data = data[2:]
        
        # Write PRG data to memory
        for i, byte_val in enumerate(prg_data):
            addr = (load_addr + i) & 0xFFFF
            self.memory.write(addr, byte_val)
        
        print(f"Loaded PRG: {len(prg_data)} bytes at ${load_addr:04X}")
        
        # If loaded at $0801 (BASIC), set up BASIC pointers
        if load_addr == 0x0801:
            # Set BASIC start pointer
            self.memory.ram[0x002B] = 0x01
            self.memory.ram[0x002C] = 0x08
            # Set BASIC end pointer
            end_addr = load_addr + len(prg_data)
            self.memory.ram[0x002D] = end_addr & 0xFF
            self.memory.ram[0x002E] = (end_addr >> 8) & 0xFF
    
    def _screen_update_worker(self) -> None:
        """Worker thread that periodically updates the screen"""
        while self.running:
            try:
                self._update_text_screen()
                time.sleep(self.screen_update_interval)
            except Exception:
                pass
    
    def run(self, max_cycles: int = 1000000) -> None:
        """Run the emulator"""
        self.running = True
        cycles = 0
        last_pc = None
        stuck_count = 0
        
        # Start screen update thread
        self.screen_update_thread = threading.Thread(target=self._screen_update_worker, daemon=True)
        self.screen_update_thread.start()
        
        # Log start of execution
        if self.udp_debug and self.udp_debug.enabled:
            self.udp_debug.send('execution_start', {
                'max_cycles': max_cycles,
                'initial_pc': self.cpu.state.pc,
                'initial_pc_hex': f'${self.cpu.state.pc:04X}'
            })
        
        # Main CPU emulation loop (runs as fast as possible)
        last_time = time.time()
        last_cycle_check = 0
        
        while self.running and cycles < max_cycles:
            step_cycles = self.cpu.step(self.udp_debug)
            cycles += step_cycles
            
            # Calculate cycles per second periodically
            if cycles - last_cycle_check >= 100000:
                current_time = time.time()
                elapsed = current_time - last_time
                if elapsed > 0:
                    self.cycles_per_second = (cycles - last_cycle_check) / elapsed
                last_time = current_time
                last_cycle_check = cycles
            
            # Detect if we're stuck (but ignore if CPU is stopped - that's expected)
            if self.cpu.state.stopped:
                # CPU is stopped (KIL instruction) - this is expected, just break
                if self.debug:
                    print(f"CPU stopped at PC=${self.cpu.state.pc:04X} (KIL instruction)")
                break
            elif self.cpu.state.pc == last_pc:
                stuck_count += 1
                if stuck_count > 1000:
                    if self.debug:
                        opcode = self.memory.read(self.cpu.state.pc)
                        print(f"Warning: PC stuck at ${self.cpu.state.pc:04X} (opcode ${opcode:02X}) for {stuck_count} steps")
                        print(f"  This usually means an opcode is not implemented or not advancing PC correctly")
                    # Don't try to advance - this masks the real problem
                    # Instead, stop execution to prevent infinite loops
                    self.running = False
                    break
            else:
                stuck_count = 0
            last_pc = self.cpu.state.pc
            
            # Periodic status logging (less frequent to avoid overhead)
            if self.debug and cycles % 100000 == 0:
                state = self.get_cpu_state()
                print(f"Cycles: {cycles}, PC=${state['pc']:04X}, A=${state['a']:02X}")
            
            # Log periodic status if UDP debug is enabled (less frequent)
            if self.udp_debug and self.udp_debug.enabled and cycles % 100000 == 0:
                state = self.get_cpu_state()
                self.udp_debug.send('status', {
                    'cycles': cycles,
                    'pc': state['pc'],
                    'pc_hex': f'${state["pc"]:04X}',
                    'a': state['a'],
                    'x': state['x'],
                    'y': state['y'],
                    'sp': state['sp'],
                    'p': state['p']
                })
        
        # Log end of execution
        if self.udp_debug and self.udp_debug.enabled:
            self.udp_debug.send('execution_end', {
                'total_cycles': cycles,
                'final_pc': self.cpu.state.pc,
                'final_pc_hex': f'${self.cpu.state.pc:04X}'
            })
        
        # Final screen update
        self._update_text_screen()
    
    def _update_text_screen(self) -> None:
        """Update text screen from screen memory (thread-safe)"""
        screen_base = SCREEN_MEM
        color_base = COLOR_MEM
        
        # Use lock to ensure thread-safe access
        with self.screen_lock:
            for row in range(25):
                for col in range(40):
                    addr = screen_base + row * 40 + col
                    char_code = self.memory.read(addr)
                    color_code = self.memory.read(color_base + row * 40 + col) & 0x0F
                
                # Convert C64 screen codes to ASCII
                # C64 screen codes: 0-63 for various characters
                char = ' '
                if char_code == 0x00:  # @
                    char = '@'
                elif 0x01 <= char_code <= 0x1A:  # A-Z
                    char = chr(ord('A') + char_code - 1)
                elif char_code == 0x20:  # Space
                    char = ' '
                elif 0x30 <= char_code <= 0x39:  # 0-9
                    char = chr(ord('0') + char_code - 0x30)
                elif 0x21 <= char_code <= 0x2F:  # ! " # $ % & ' ( ) * + , - . /
                    # Map common punctuation
                    if char_code == 0x21:
                        char = '!'
                    elif char_code == 0x22:
                        char = '"'
                    elif char_code == 0x27:
                        char = "'"
                    elif char_code == 0x2C:
                        char = ','
                    elif char_code == 0x2D:
                        char = '-'
                    elif char_code == 0x2E:
                        char = '.'
                    elif char_code == 0x2F:
                        char = '/'
                    else:
                        char = chr(char_code) if 0x20 <= char_code <= 0x7E else ' '
                elif 0x3A <= char_code <= 0x3F:  # : ; < = > ?
                    char = chr(char_code)
                elif 0x40 <= char_code <= 0x5A:  # @ A-Z (shifted, but same as 0x41-0x5A)
                    if char_code == 0x40:
                        char = '@'
                    else:
                        char = chr(char_code)
                elif 0x20 <= char_code <= 0x7E:  # Direct ASCII (fallback)
                    char = chr(char_code)
                else:
                    char = ' '
                
                    self.text_screen[row][col] = char
                    self.text_colors[row][col] = color_code
    
    def render_text_screen(self) -> str:
        """Render text screen as string (thread-safe)"""
        with self.screen_lock:
            lines = []
            for row in self.text_screen:
                lines.append(''.join(row))
            return '\n'.join(lines)
    
    def dump_memory(self, start: int = 0x0000, end: int = 0x10000) -> bytes:
        """Dump memory range as bytes"""
        return bytes(self.memory.ram[start:end])
    
    def get_cpu_state(self) -> Dict:
        """Get current CPU state"""
        return {
            'pc': self.cpu.state.pc,
            'a': self.cpu.state.a,
            'x': self.cpu.state.x,
            'y': self.cpu.state.y,
            'sp': self.cpu.state.sp,
            'p': self.cpu.state.p,
            'cycles': self.cpu.state.cycles
        }
    
    def set_cpu_state(self, state: Dict) -> None:
        """Set CPU state"""
        if 'pc' in state:
            self.cpu.state.pc = state['pc'] & 0xFFFF
        if 'a' in state:
            self.cpu.state.a = state['a'] & 0xFF
        if 'x' in state:
            self.cpu.state.x = state['x'] & 0xFF
        if 'y' in state:
            self.cpu.state.y = state['y'] & 0xFF
        if 'sp' in state:
            self.cpu.state.sp = state['sp'] & 0xFF
        if 'p' in state:
            self.cpu.state.p = state['p'] & 0xFF


class EmulatorServer:
    """TCP/UDP server for controlling the emulator"""
    
    def __init__(self, emu: C64Emulator, tcp_port: Optional[int] = None, udp_port: Optional[int] = None):
        self.emu = emu
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.running = False
        
    def start(self) -> None:
        """Start the server"""
        self.running = True
        
        if self.tcp_port:
            tcp_thread = threading.Thread(target=self._tcp_server, daemon=True)
            tcp_thread.start()
            print(f"TCP server listening on port {self.tcp_port}")
        
        if self.udp_port:
            udp_thread = threading.Thread(target=self._udp_server, daemon=True)
            udp_thread.start()
            print(f"UDP server listening on port {self.udp_port}")
    
    def _tcp_server(self) -> None:
        """TCP server thread"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('localhost', self.tcp_port))
        sock.listen(5)
        
        while self.running:
            try:
                conn, addr = sock.accept()
                threading.Thread(target=self._handle_tcp_client, args=(conn, addr), daemon=True).start()
            except Exception as e:
                if self.running:
                    print(f"TCP server error: {e}")
    
    def _udp_server(self) -> None:
        """UDP server thread"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('localhost', self.udp_port))
        
        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                response = self._handle_command(data.decode('utf-8', errors='ignore'))
                if response:
                    sock.sendto(response.encode('utf-8'), addr)
            except Exception as e:
                if self.running:
                    print(f"UDP server error: {e}")
    
    def _handle_tcp_client(self, conn: socket.socket, addr: Tuple) -> None:
        """Handle TCP client connection"""
        try:
            while self.running:
                data = conn.recv(1024)
                if not data:
                    break
                command = data.decode('utf-8', errors='ignore').strip()
                response = self._handle_command(command)
                if response:
                    conn.sendall(response.encode('utf-8') + b'\n')
        except Exception as e:
            print(f"TCP client error: {e}")
        finally:
            conn.close()
    
    def _handle_command(self, command: str) -> str:
        """Handle a command and return response"""
        parts = command.split()
        if not parts:
            return "OK"
        
        cmd = parts[0].upper()
        
        if cmd == "STATUS":
            state = self.emu.get_cpu_state()
            return f"PC=${state['pc']:04X} A=${state['a']:02X} X=${state['x']:02X} Y=${state['y']:02X} SP=${state['sp']:02X} P=${state['p']:02X} CYCLES={state['cycles']}"
        
        elif cmd == "STEP":
            cycles = self.emu.cpu.step()
            return f"OK CYCLES={cycles}"
        
        elif cmd == "STEPS":
            count = int(parts[1]) if len(parts) > 1 else 1
            total_cycles = 0
            for _ in range(count):
                total_cycles += self.emu.cpu.step()
            return f"OK CYCLES={total_cycles}"
        
        elif cmd == "RUN":
            max_cycles = int(parts[1]) if len(parts) > 1 else 1000000
            cycles = 0
            while cycles < max_cycles:
                cycles += self.emu.cpu.step()
            return f"OK CYCLES={cycles}"
        
        elif cmd == "MEMORY":
            if len(parts) < 2:
                return "ERROR: Missing address"
            addr = int(parts[1].replace('$', '').replace('0x', ''), 16)
            value = self.emu.memory.read(addr)
            return f"${addr:04X}={value:02X}"
        
        elif cmd == "WRITE":
            if len(parts) < 3:
                return "ERROR: Missing address or value"
            addr = int(parts[1].replace('$', '').replace('0x', ''), 16)
            value = int(parts[2].replace('$', '').replace('0x', ''), 16)
            self.emu.memory.write(addr, value)
            return "OK"
        
        elif cmd == "DUMP":
            start = int(parts[1].replace('$', '').replace('0x', ''), 16) if len(parts) > 1 else 0x0000
            end = int(parts[2].replace('$', '').replace('0x', ''), 16) if len(parts) > 2 else 0x10000
            dump = self.emu.dump_memory(start, end)
            # Return as hex string
            return dump.hex()
        
        elif cmd == "SCREEN":
            self.emu._update_text_screen()
            return self.emu.render_text_screen()
        
        elif cmd == "LOAD":
            if len(parts) < 2:
                return "ERROR: Missing PRG file path"
            try:
                self.emu.load_prg(parts[1])
                return "OK"
            except Exception as e:
                return f"ERROR: {e}"
        
        elif cmd == "STOP":
            self.emu.running = False
            return "OK"
        
        elif cmd == "QUIT" or cmd == "EXIT":
            self.running = False
            self.emu.running = False
            return "OK"
        
        else:
            return f"ERROR: Unknown command '{cmd}'"


def main():
    ap = argparse.ArgumentParser(description="C64 Emulator (text mode)")
    ap.add_argument("prg_file", nargs="?", help="PRG file to load and run")
    ap.add_argument("--rom-dir", default="lib/assets", help="Directory containing ROM files")
    ap.add_argument("--tcp-port", type=int, help="TCP port for control interface")
    ap.add_argument("--udp-port", type=int, help="UDP port for control interface")
    ap.add_argument("--max-cycles", type=int, default=1000000, help="Maximum cycles to run")
    ap.add_argument("--dump-memory", help="Dump memory to file after execution")
    ap.add_argument("--debug", action="store_true", help="Enable debug output")
    ap.add_argument("--udp-debug", action="store_true", help="Send debug events via UDP")
    ap.add_argument("--udp-debug-port", type=int, default=64738, help="UDP port for debug events (default: 64738)")
    ap.add_argument("--udp-debug-host", type=str, default="127.0.0.1", help="UDP host for debug events (default: 127.0.0.1)")
    ap.add_argument("--screen-update-interval", type=float, default=0.1, help="Screen update interval in seconds (default: 0.1)")
    
    args = ap.parse_args()
    
    emu = C64Emulator()
    emu.debug = args.debug
    emu.screen_update_interval = args.screen_update_interval
    
    # Setup UDP debug logging if requested
    if args.udp_debug:
        emu.udp_debug = UdpDebugLogger(port=args.udp_debug_port, host=args.udp_debug_host)
        emu.udp_debug.enable()
        print(f"UDP debug logging enabled (async): {args.udp_debug_host}:{args.udp_debug_port}")
    
    # Pass UDP debug logger to memory
    if emu.udp_debug:
        emu.memory.udp_debug = emu.udp_debug
    
    # Load ROMs
    print("Loading ROMs...")
    emu.load_roms(args.rom_dir)
    
    # Load PRG if provided
    if args.prg_file:
        emu.load_prg(args.prg_file)
    
    # Initialize CPU
    reset_vector = emu.memory.read(0xFFFC) | (emu.memory.read(0xFFFD) << 8)
    emu.cpu.state.pc = reset_vector
    print(f"Reset vector: ${reset_vector:04X}")
    
    if args.debug:
        print(f"Initial CPU state: PC=${emu.cpu.state.pc:04X}, A=${emu.cpu.state.a:02X}, X=${emu.cpu.state.x:02X}, Y=${emu.cpu.state.y:02X}")
        print(f"Memory config ($01): ${emu.memory.ram[0x01]:02X}")
        print(f"Screen memory sample ($0400-$040F): {[hex(emu.memory.ram[0x0400 + i]) for i in range(16)]}")
    
    # Start server if requested
    server = None
    if args.tcp_port or args.udp_port:
        server = EmulatorServer(emu, tcp_port=args.tcp_port, udp_port=args.udp_port)
        server.start()
        print("Server started. Use commands like: STATUS, STEP, RUN, MEMORY, DUMP, SCREEN, LOAD")
        print("Press Ctrl+C to stop")
    
    # Run emulator
    try:
        if server:
            # If server is running, don't auto-run - wait for commands
            print("Emulator ready. Waiting for commands...")
            while server.running and emu.running:
                time.sleep(0.1)
        else:
            print("Running emulator...")
            emu.run(args.max_cycles)
    except KeyboardInterrupt:
        print("\nStopping emulator...")
        emu.running = False
        if server:
            server.running = False
    
    # Dump memory if requested
    if args.dump_memory:
        memory_dump = emu.dump_memory()
        with open(args.dump_memory, 'wb') as f:
            f.write(bytes([0x00, 0x00]))  # PRG header
            f.write(memory_dump)
        print(f"Memory dumped to {args.dump_memory}")
    
    # Show screen
    if not server or not server.running:
        print("\nScreen output:")
        emu._update_text_screen()
        print(emu.render_text_screen())
    
    # Stop screen update thread
    emu.running = False
    if emu.screen_update_thread and emu.screen_update_thread.is_alive():
        emu.screen_update_thread.join(timeout=1.0)
    
    # Close UDP debug logger
    if emu.udp_debug:
        emu.udp_debug.close()


if __name__ == "__main__":
    main()
