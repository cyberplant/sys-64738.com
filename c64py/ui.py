"""
Textual User Interface
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from rich.console import Console
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static, Header, Footer, RichLog

if TYPE_CHECKING:
    from .emulator import C64

class TextualInterface(App):
    """Textual-based interface with TCSS styling"""

    BINDINGS = [
        ("ctrl+x", "quit", "Quit the emulator"),
        ("ctrl+r", "random_screen", "Fill screen with random characters"),
        ("ctrl+k", "dump_screen", "Dump screen memory to debug logs"),
    ]

    CSS = """
    Screen {
        background: $surface;
        layout: vertical;
    }

    #c64-display {
        border: solid $primary;
        margin: 0 1;
        padding: 0;
        height: 40fr;
        width: 10fr;
        background: #0000AA;
        color: #FFFFFF;
    }

    Screen.fullscreen #c64-display {
        border: none;
        margin: 0;
        padding: 0;
        height: 100%;
        width: 100%;
    }

    #debug-panel {
        border: solid $secondary;
        margin: 0 1;
        overflow-y: scroll;
        padding: 0 1;
        height: 35%;
    }

    #status-bar {
        border: solid $primary;
        margin: 0 1;
        padding: 0 1;
        height: 4;
        background: $primary;
        color: $surface;
    }
    """

    def __init__(self, emulator, max_cycles=10000000, fullscreen=False):
        super().__init__()
        self.emulator = emulator
        self.max_cycles = max_cycles
        self.max_logs = 1000
        self.current_cycle = 0
        self.emulator_thread = None
        self.running = False
        self.fullscreen = fullscreen
        # Widget references (set in on_mount)
        self.c64_display = None
        self.debug_logs = None
        self.status_bar = None

    def compose(self) -> ComposeResult:
        if not self.fullscreen:
            yield Header()
        yield RichLog(id="c64-display", auto_scroll=False)
        if not self.fullscreen:
            yield RichLog(id="debug-panel", auto_scroll=True)
            yield Static("Initializing...", id="status-bar")
        if not self.fullscreen:
            yield Footer()

    def on_mount(self):
        """Called when the app is mounted"""
        if self.fullscreen:
            # In fullscreen mode, add the fullscreen class to the screen
            self.screen.add_class("fullscreen")
        
        self.c64_display = self.query_one("#c64-display", RichLog)
        self.c64_display.write("Loading C64...")
        
        if not self.fullscreen:
            self.debug_logs = self.query_one("#debug-panel", RichLog)
            self.status_bar = self.query_one("#status-bar", Static)

        # Debug: check if widgets are found (only in non-fullscreen mode)
        if not self.fullscreen:
            self.add_debug_log(f"Widgets found: c64={self.c64_display is not None}, debug={self.debug_logs is not None}, status={self.status_bar is not None}")

        # Buffered messages are handled automatically in add_debug_log

        # Start emulator in background thread
        self.running = True
        self.emulator_thread = threading.Thread(target=self._run_emulator, daemon=True)
        self.emulator_thread.start()

        # Update UI periodically
        self.set_interval(0.1, self._update_ui)

    def _run_emulator(self):
        """Run the emulator in background thread"""
        try:
            # For Textual interface, run without the screen update worker
            # since UI updates are handled by _update_ui
            self.emulator.running = True
            cycles = 0
            max_cycles = self.max_cycles
            last_pc = None
            stuck_count = 0
            consecutive_cr_count = 0  # Track consecutive CR calls

            while self.emulator.running:
                if cycles >= max_cycles:
                    if hasattr(self.emulator, 'autoquit') and self.emulator.autoquit:
                        self.emulator.running = False
                    break

                step_cycles = self.emulator.cpu.step(self.emulator.udp_debug, cycles)
                cycles += step_cycles
                self.emulator.current_cycles = cycles

                # Stuck detection
                pc = self.emulator.cpu.state.pc
                if pc == last_pc:
                    stuck_count += 1
                    if stuck_count > 1000:
                        self.add_debug_log(f"⚠️ PC stuck at ${pc:04X} for {stuck_count} steps - stopping")
                        self.emulator.running = False
                        break
                else:
                    stuck_count = 0
                last_pc = pc

                # Detect excessive consecutive CR calls (potential infinite loop)
                if hasattr(self.emulator.cpu, 'last_chrout_char') and self.emulator.cpu.last_chrout_char == 0x0D:
                    self.consecutive_cr_count += 1
                    if self.consecutive_cr_count > 500:  # Allow some CRs but not infinite
                        self.add_debug_log(f"⚠️ Detected {self.consecutive_cr_count} consecutive CR calls - possible infinite loop, stopping")
                        #self.emulator.running = False
                        #break
                else:
                    self.consecutive_cr_count = 0

                # Simple stuck detection
                #if cycles % 10000 == 0:
                    #if hasattr(self.emulator, 'interface') and self.emulator.interface:
                        #self.emulator.interface.add_debug_log(f"🔄 Emulator progress: {cycles} cycles")

            # Log why we stopped
            if hasattr(self, 'add_debug_log'):
                if cycles >= max_cycles:
                    self.add_debug_log(f"🛑 Stopped at cycle {cycles} (reached max_cycles={max_cycles})")
                else:
                    self.add_debug_log(f"🛑 Stopped at cycle {cycles} (unknown reason, stuck_count={stuck_count})")

        except Exception as e:
            if hasattr(self, 'add_debug_log'):
                self.add_debug_log(f"❌ Emulator error: {e}")

    def _update_ui(self):
        """Update the UI periodically"""
        if self.emulator and not self.emulator.running:
            # Emulator has stopped (e.g., due to autoquit), exit the app
            self.add_debug_log("🛑 Emulator stopped, exiting...")
            # Capture last lines of log before exiting
            last_lines = self._get_last_log_lines(20)
            self.exit()
            # Print captured logs to console after UI shutdown
            if last_lines:
                print("\n=== Last log messages ===")
                for line in last_lines:
                    print(line)
            return

        if self.emulator:
            # Update text screen from memory
            self.emulator._update_text_screen()

            # Update screen display
            screen_content = self.emulator.render_text_screen(no_colors=False)
            
            # Debug: Check if screen has any non-space content
            non_space_count = sum(1 for c in screen_content if c not in (' ', '\n'))
            if non_space_count > 0 and not hasattr(self, '_screen_debug_logged'):
                # Sample first few characters from screen memory
                sample_chars = []
                for addr in range(SCREEN_MEM, SCREEN_MEM + 20):
                    char_code = self.emulator.memory.read(addr)
                    sample_chars.append(f"${char_code:02X}")
                self.add_debug_log(f"📺 Screen has {non_space_count} non-space chars. First 20 bytes: {', '.join(sample_chars)}")
                self._screen_debug_logged = True
            
            # For RichLog, clear and write new content
            self.c64_display.clear()
            self.c64_display.write(screen_content)

            # Update status bar with actual cycle count from emulator (only in non-fullscreen mode)
            if not self.fullscreen:
                emu = self.emulator
                # Read cursor position from memory
                cursor_row = emu.memory.read(0xD3)
                cursor_col = emu.memory.read(0xD8)
                status_text = f"🎮 C64 | Cycle: {emu.current_cycles:,} | PC: ${emu.cpu.state.pc:04X} | A: ${emu.cpu.state.a:02X} | X: ${emu.cpu.state.x:02X} | Y: ${emu.cpu.state.y:02X} | SP: ${emu.cpu.state.sp:02X} | Cursor: {cursor_row},{cursor_col}"
                if self.status_bar:
                    self.status_bar.update(status_text)

            # Debug: show screen content periodically
            if hasattr(self.emulator, 'debug') and self.emulator.debug:
                non_spaces = sum(1 for row in self.emulator.text_screen for char in row if char != ' ')
                if non_spaces > 0:
                    first_line = ''.join(self.emulator.text_screen[0]).rstrip()
                    if first_line:
                        self.add_debug_log(f"📝 Screen content: '{first_line}'")

    def add_debug_log(self, message: str):
        """Add a debug message"""
        # Skip debug logging in fullscreen mode
        if self.fullscreen:
            return
            
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"

        # Buffer message if widget not ready yet
        if not hasattr(self, 'debug_messages'):
            self.debug_messages = []
            self.max_logs = 1000  # Keep more messages

        self.debug_messages.append(formatted_message)
        if len(self.debug_messages) > self.max_logs:
            self.debug_messages.pop(0)

        # Update widget if it's available
        if self.debug_logs:
            # If this is the first time, write all buffered messages
            if not hasattr(self, '_debug_initialized'):
                for msg in self.debug_messages:
                    self.debug_logs.write(msg)
                self._debug_initialized = True
            else:
                # Just write the latest message
                self.debug_logs.write(formatted_message)

    def _get_last_log_lines(self, count: int = 20) -> List[str]:
        """Get the last N lines from the debug log"""
        if hasattr(self, 'debug_messages'):
            return self.debug_messages[-count:] if len(self.debug_messages) > count else self.debug_messages
        return []

    def update_screen(self, screen_content: str):
        """Stub method for compatibility - Textual updates automatically"""
        pass

    def update_status(self):
        """Stub method for compatibility - Textual updates automatically"""
        pass

    def check_input(self):
        """Stub method for compatibility - Textual handles input automatically"""
        return False

    def action_quit(self):
        """Quit the emulator"""
        self.running = False
        if self.emulator:
            self.emulator.running = False
        self.exit()

    def action_random_screen(self):
        """Fill screen with random characters for testing"""
        import random
        if self.emulator:
            # Fill screen memory with random visible characters
            for addr in range(0x0400, 0x0400 + 1000):  # Full screen
                # Use random printable ASCII characters (0x20-0x7E)
                char_code = random.randint(0x20, 0x7E)
                self.emulator.memory.ram[addr] = char_code
            self.add_debug_log("🎲 Filled screen with random characters")
            # Trigger immediate screen update
            self.emulator._update_text_screen()

    def action_dump_screen(self):
        """Dump screen memory sample to debug logs"""
        if self.emulator:
            # Dump first few lines of screen memory
            lines = []
            for row in range(min(5, 25)):  # First 5 rows
                line_start = 0x0400 + row * 40
                line_data = []
                for col in range(min(20, 40)):  # First 20 columns
                    char_code = self.emulator.memory.ram[line_start + col]
                    # Convert to printable char or show code
                    if 32 <= char_code <= 126:
                        line_data.append(chr(char_code))
                    else:
                        line_data.append(f'${char_code:02X}')
                lines.append(f"Row {row}: {''.join(line_data)}")
            self.add_debug_log("📺 Screen memory dump:")
            for line in lines:
                self.add_debug_log(f"  {line}")


