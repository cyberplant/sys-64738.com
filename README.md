# sys-64738.com

A website that serves as a Commodore 64 emulator, where the web content is provided as a C64 program that the emulator loads.

## Overview

This project creates a web-based C64 emulator where you can:
- Load and run C64 programs (`.prg`, `.d64`, `.t64`, `.crt` files)
- Modify the C64 program files to change the web content
- Provide an authentic retro computing experience in the browser

## Features

- Full C64 emulation in the browser
- Load programs from local files or URLs
- Clean, retro-styled UI
- Responsive design

## Setup

**Note**: While JSC64 can work when opening the HTML file directly, it's recommended to use a local web server for best results, especially when loading programs.

### Option 1: Direct (Simple Testing)
You can open `index.html` directly in your browser, though some features may be limited.

### Option 2: Using Python (Recommended)
```bash
python3 -m http.server 8000
```
Then open `http://localhost:8000` in your browser.

### Option 3: Using Node.js http-server
```bash
npx http-server -p 8000
```

### Option 4: Using PHP
```bash
php -S localhost:8000
```

After starting a server (or opening directly):
1. Navigate to the page in your browser
2. Wait for "Emulator ready" message
3. Click "Load Program" to load a C64 program file (`.prg` format)
4. The emulator will start and run your program

## Loading Programs

### From Local File
Click the "Load Program" button and select a C64 program file from your computer.

### From URL (Programmatic)
You can load a program programmatically using the browser console:

```javascript
loadProgramFromUrl('https://example.com/path/to/program.prg', 'My Program');
```

## File Structure

- `index.html` - Main HTML file with emulator container
- `styles.css` - Styling for the retro-themed UI
- `app.js` - JavaScript code for emulator integration and program loading
- `lib/` - Local JavaScript libraries (jQuery and JSC64 with all dependencies)
  - `lib/assets/` - C64 ROM files (kernal, basic, and character ROMs)
- `programs/` - (Optional) Directory to store your C64 program files

All dependencies are stored locally - no CDN required! The C64 ROM files are included in `lib/assets/`.

## Creating Your C64 Program

To modify the web content, you'll need to:
1. Create or modify a C64 program using a C64 development tool
2. Export it as a `.prg` file
3. Load it into the emulator

The program you create will be what users see and interact with when they visit your website.

## Emulator

Currently using **JSC64** for C64 emulation. JSC64 is a jQuery-based emulator that's simple to use and works well in browsers.

- **GitHub**: https://github.com/reggino/jsc64
- **Demo**: https://reggino.github.io/jsc64/
- **API**: Uses `jsc64.loadPrg(url)` method to load programs

### Alternative Emulators

If you need to switch to a different emulator:

1. **ty64** - Lightweight, native JavaScript (no jQuery)
   - Documentation: https://ty64.krissz.hu/documentation/en/

2. **EmulatorJS** - More complex setup, supports many systems
   - Requires server headers and data directory
   - Documentation: https://emulatorjs.org/

To switch emulators, update the script tags in `index.html` and modify the initialization code in `app.js`.

## Notes

- Make sure your C64 programs are compatible with the emulator
- Some programs may require specific C64 configurations
- Test your programs thoroughly before deploying

## License

Check the licenses of the emulator libraries you use.
