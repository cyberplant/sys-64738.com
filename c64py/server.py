"""
TCP/UDP Server for controlling the emulator
"""

from __future__ import annotations

import socket
import threading
from typing import Optional, Tuple

from .emulator import C64

class EmulatorServer:
    """TCP/UDP server for controlling the emulator"""
    
    def __init__(self, emu: C64, tcp_port: Optional[int] = None, udp_port: Optional[int] = None):
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
            max_cycles = int(parts[1]) if len(parts) > 1 else None
            cycles = 0
            while max_cycles is None or cycles < max_cycles:
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
            # For server mode, always return plain text
            return self.emu.render_text_screen(no_colors=True)
        
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


