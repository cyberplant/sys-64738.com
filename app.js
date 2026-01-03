// C64 Emulator Integration using JSC64
let emulator = null;

// Initialize the emulator when the page loads
$(document).ready(function() {
    initializeEmulator();
    setupFileInput();
});

function initializeEmulator() {
    const container = $('#emulator-container');
    
    try {
        // Check if jQuery and JSC64 are loaded
        if (typeof $ === 'undefined' || typeof $.fn.jsc64 === 'undefined') {
            // Wait a bit for scripts to load
            setTimeout(() => {
                if (typeof $ !== 'undefined' && typeof $.fn.jsc64 !== 'undefined') {
                    // Wait a bit more to ensure all dependency scripts are loaded
                    setTimeout(() => {
                        initJSC64();
                    }, 100);
                } else {
                    console.error('JSC64 not loaded. Check the script files.');
                    showError('Emulator library failed to load. Please refresh the page.');
                }
            }, 500);
        } else {
            // Wait a bit to ensure all dependency scripts are loaded
            setTimeout(() => {
                initJSC64();
            }, 100);
        }
    } catch (error) {
        console.error('Error initializing emulator:', error);
        showError('Failed to initialize emulator. Check console for details.');
    }
}

function initJSC64() {
    const container = $('#emulator-container');
    
    // Initialize JSC64
    // The jsc64() function takes an optional keyboardEventListener parameter
    // If not provided, it defaults to $(document)
    // We'll pass $(document) explicitly to ensure it's a jQuery object
    container.jsc64($(document));
    
    // Get the JSC64 instance from the container's data
    emulator = container;
    
    // Scale canvas to fill container
    scaleCanvas();
    
    // Re-scale on window resize
    $(window).on('resize', scaleCanvas);
    
    console.log('C64 Emulator initialized (JSC64)');
    
    // Try to auto-load the compiled program if it exists
    autoLoadProgram();
    
    // Update status (only if program-info element exists - debug page)
    const programInfo = $('#program-info');
    if (programInfo.length > 0) {
        programInfo.text('Emulator ready. Click "Load Program" to start.');
        programInfo.css('color', '#00cc00');
    }
}

function autoLoadProgram() {
    // Try to load the compiled main.prg if it exists
    const programPath = 'programs/main.prg';
    
    // Wait for emulator to be fully ready
    function waitForEmulatorAndLoad(retries = 20, delay = 250) {
        if (retries === 0) {
            console.log('Auto-load: Emulator not ready after retries');
            return;
        }
        
        // Check if emulator is fully ready
        const jsc64Instance = $('#emulator-container').data('c64');
        if (!jsc64Instance || !jsc64Instance._renderer || !jsc64Instance._renderer.frameTimer || !jsc64Instance._mem) {
            // Emulator not ready yet, retry
            setTimeout(() => waitForEmulatorAndLoad(retries - 1, delay), delay);
            return;
        }
        
        // Emulator is ready, fetch and load the program
        // Use the same approach as manual loading
        fetch(programPath)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Program not found');
                }
                return response.arrayBuffer();
            })
            .then(arrayBuffer => {
                // Create blob and URL like manual load does
                const blob = new Blob([arrayBuffer], { type: 'application/octet-stream' });
                const url = URL.createObjectURL(blob);
                
                // Use the same timing as manual load (100ms delay before loadPrg)
                setTimeout(() => {
                    if (emulator && typeof emulator.loadPrg === 'function') {
                        try {
                            // Load the program (exactly like manual load)
                            emulator.loadPrg(url);
                            
                            // Try to fix BASIC pointers after loading (only if needed)
                            setTimeout(() => {
                                const jsc64Instance = $('#emulator-container').data('c64');
                                if (jsc64Instance && jsc64Instance._mem) {
                                    const mem = jsc64Instance._mem;
                                    const firstLink = mem.read(0x0801) | (mem.read(0x0802) << 8);
                                    // If we have a valid link, try to fix pointers
                                    if (firstLink > 0x0801 && firstLink < 0xA000) {
                                        fixBASICPointers();
                                    } else {
                                        console.log('Auto-load: Skipping fixBASICPointers - program may not need it');
                                    }
                                }
                            }, 400);
                            
                            const programInfo = $('#program-info');
                            if (programInfo.length > 0) {
                                programInfo.text('Auto-loaded: main.prg');
                                programInfo.css('color', '#00cc00');
                            }
                            console.log('Auto-loaded main.prg successfully');
                            
                            // Clean up the object URL after a delay
                            setTimeout(() => {
                                URL.revokeObjectURL(url);
                            }, 2000);
                        } catch (error) {
                            console.error('Error auto-loading program:', error);
                            const programInfo = $('#program-info');
                            if (programInfo.length > 0) {
                                programInfo.text('Auto-load failed. Use "Load Program" button.');
                                programInfo.css('color', '#ffaa00');
                            }
                        }
                    } else {
                        console.warn('Emulator or loadPrg not available for auto-load');
                    }
                }, 200); // Small delay to ensure emulator is stable
            })
            .catch(error => {
                // Program not found - that's okay, user can load manually
                console.log('Auto-load: Program not found, user can load manually');
            });
    }
    
    // Start trying to load after emulator initialization delay
    setTimeout(() => waitForEmulatorAndLoad(), 3000);
}

function scaleCanvas() {
    const container = $('#emulator-container');
    const canvases = container.find('canvas');
    
    if (canvases.length === 0) {
        // Canvases not created yet, try again in a bit
        setTimeout(scaleCanvas, 100);
        return;
    }
    
    // C64 native resolution: 403x284
    const c64Width = 403;
    const c64Height = 284;
    const c64Aspect = c64Width / c64Height;
    
    // Container dimensions
    const containerWidth = container.width();
    const containerHeight = container.height();
    const containerAspect = containerWidth / containerHeight;
    
    let scale, newWidth, newHeight;
    
    // Calculate scale to fill container while maintaining aspect ratio
    if (containerAspect > c64Aspect) {
        // Container is wider - fit to height
        scale = containerHeight / c64Height;
        newHeight = containerHeight;
        newWidth = c64Width * scale;
    } else {
        // Container is taller - fit to width
        scale = containerWidth / c64Width;
        newWidth = containerWidth;
        newHeight = c64Height * scale;
    }
    
    // Apply scale to all canvases
    canvases.css({
        'width': newWidth + 'px',
        'height': newHeight + 'px',
        'position': 'absolute',
        'top': '50%',
        'left': '50%',
        'transform': 'translate(-50%, -50%)',
        'image-rendering': 'pixelated',
        'image-rendering': 'crisp-edges'
    });
}

function showError(message) {
    const programInfo = $('#program-info');
    if (programInfo.length > 0) {
        programInfo.text(message);
        programInfo.css('color', '#ff0000');
    }
    console.error(message);
}

function setupFileInput() {
    // Only setup file input if the controls bar exists (debug page)
    if ($('#load-program-btn').length > 0) {
        $('#load-program-btn').on('click', function() {
            $('#file-input').click();
        });
        
        $('#file-input').on('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                loadProgram(file);
            }
        });
    }
}

function loadProgram(file) {
    const programInfo = $('#program-info');
    const reader = new FileReader();
    
    if (programInfo.length > 0) {
        programInfo.text(`Loading ${file.name}...`);
        programInfo.css('color', '#00cc00');
    }
    
    reader.onload = function(e) {
        const arrayBuffer = e.target.result;
        
        // Verify PRG file format (should start with load address)
        const view = new DataView(arrayBuffer);
        if (arrayBuffer.byteLength < 2) {
            if (programInfo.length > 0) {
                programInfo.text('Error: File too small to be a valid PRG');
                programInfo.css('color', '#ff0000');
            }
            return;
        }
        
        const loadAddress = view.getUint16(0, true); // Little endian
        console.log(`PRG file load address: $${loadAddress.toString(16).toUpperCase()}`);
        
        if (loadAddress !== 0x0801 && loadAddress !== 0x0800) {
            console.warn(`Warning: Load address is $${loadAddress.toString(16).toUpperCase()}, expected $0801 for BASIC programs`);
        }
        
        const blob = new Blob([arrayBuffer], { type: 'application/octet-stream' });
        const url = URL.createObjectURL(blob);
        
        // Wait a bit to ensure emulator is ready
        setTimeout(() => {
            // Load the program into JSC64
            // JSC64 stores the instance in the container's data, and loadPrg is a jQuery method
            if (emulator && typeof emulator.loadPrg === 'function') {
                try {
                    // JSC64 uses loadPrg method on the container
                    // Note: loadPrg writes directly to memory, so we don't need to clear first
                    emulator.loadPrg(url);
                    // Try to fix BASIC pointers after loading (only if needed)
                    // Wait a bit longer to ensure program is fully loaded
                    setTimeout(() => {
                        // Only fix pointers if program appears to need it
                        const jsc64Instance = $('#emulator-container').data('c64');
                        if (jsc64Instance && jsc64Instance._mem) {
                            const mem = jsc64Instance._mem;
                            const firstLink = mem.read(0x0801) | (mem.read(0x0802) << 8);
                            // If we have a valid link, try to fix pointers
                            if (firstLink > 0x0801 && firstLink < 0xA000) {
                                fixBASICPointers();
                            } else {
                                console.log('Skipping fixBASICPointers - program may not need it');
                            }
                        }
                    }, 400);
                    if (programInfo.length > 0) {
                        programInfo.text(`Loaded: ${file.name}`);
                        programInfo.css('color', '#00cc00');
                    }
                    
                    // Clean up the object URL after a delay
                    setTimeout(() => {
                        URL.revokeObjectURL(url);
                    }, 2000);
                } catch (error) {
                    console.error('Error loading program:', error);
                    if (programInfo.length > 0) {
                        programInfo.text(`Error loading ${file.name}: ${error.message}`);
                        programInfo.css('color', '#ff0000');
                    }
                }
            } else {
                if (!emulator) {
                    if (programInfo.length > 0) {
                        programInfo.text('Emulator not initialized. Please wait...');
                    }
                } else {
                    if (programInfo.length > 0) {
                        programInfo.text('JSC64 loadPrg method not available.');
                    }
                }
                if (programInfo.length > 0) {
                    programInfo.css('color', '#ff0000');
                }
            }
        }, 100);
    };
    
    reader.onerror = function() {
        if (programInfo.length > 0) {
            programInfo.text('Error reading file');
            programInfo.css('color', '#ff0000');
        }
    };
    
    reader.readAsArrayBuffer(file);
}

// Clear BASIC program area and variables before loading (for clean state)
function clearBASICArea() {
    const jsc64Instance = $('#emulator-container').data('c64');
    if (!jsc64Instance || !jsc64Instance._mem) {
        return;
    }
    
    const mem = jsc64Instance._mem;
    
    // Clear the BASIC program area (0x0801 to 0x9FFF)
    for (let addr = 0x0801; addr < 0xA000; addr++) {
        mem.write(addr, 0);
    }
    
    // Clear the variable area (0x1000 to 0x1FFF) to prevent OUT OF MEMORY
    for (let addr = 0x1000; addr < 0x2000; addr++) {
        mem.write(addr, 0);
    }
    
    // Reset BASIC pointers to initial state (empty program)
    const emptyProgramAddr = 0x0801;
    mem.write(0x2B, emptyProgramAddr & 0xFF);
    mem.write(0x2C, (emptyProgramAddr >> 8) & 0xFF);
    mem.write(0x2D, emptyProgramAddr & 0xFF);
    mem.write(0x2E, (emptyProgramAddr >> 8) & 0xFF);
    mem.write(0x2F, emptyProgramAddr & 0xFF);
    mem.write(0x30, (emptyProgramAddr >> 8) & 0xFF);
    mem.write(0x31, emptyProgramAddr & 0xFF);
    mem.write(0x32, (emptyProgramAddr >> 8) & 0xFF);
    mem.write(0x33, emptyProgramAddr & 0xFF);
    mem.write(0x34, (emptyProgramAddr >> 8) & 0xFF);
    
    // Set end of BASIC to a safe location (before screen memory at 0x0400)
    // C64 typically uses 0x0800-0x9FFF for BASIC, with screen at 0x0400
    const safeEndAddr = 0x9FFF;
    mem.write(0x37, safeEndAddr & 0xFF);
    mem.write(0x38, (safeEndAddr >> 8) & 0xFF);
    
    // Clear keyboard buffer and input
    mem.write(0xC6, 0); // Number of characters in keyboard buffer
    mem.write(0x0277, 0); // Clear keyboard buffer area
    
    // Mark end of program at start address (empty program marker: 00 00)
    mem.write(0x0801, 0);
    mem.write(0x0802, 0);
    
    // Clear some other important zero-page locations
    mem.write(0x0289, 0x78); // Default input buffer size
    mem.write(0x028A, 0x78); // Default input buffer size (high)
    
    console.log('Cleared BASIC area and reset pointers');
}

// Fix BASIC pointers after loading a program
// This mimics what the C64 does when loading a BASIC program
function fixBASICPointers() {
    const jsc64Instance = $('#emulator-container').data('c64');
    if (!jsc64Instance || !jsc64Instance._mem) {
        console.warn('Cannot fix BASIC pointers: emulator not ready');
        return;
    }
    
    const mem = jsc64Instance._mem;
    const startAddr = 0x0801;
    
    // First, verify the program is actually loaded by checking the first few bytes
    // A valid BASIC program should have a link to the next line at the start
    // The link should be > startAddr and < 0xA000
    const byte0 = mem.read(startAddr);
    const byte1 = mem.read(startAddr + 1);
    const firstLink = byte0 | (byte1 << 8);
    
    console.log(`fixBASICPointers: Checking at $${startAddr.toString(16)}: $${byte0.toString(16).padStart(2, '0')} $${byte1.toString(16).padStart(2, '0')} (link: $${firstLink.toString(16)})`);
    
    // Validate the link - it should point to the next line
    // Valid links are between startAddr+1 and 0xA000
    if (firstLink === 0) {
        console.warn('fixBASICPointers: Program appears empty (link is 0), skipping pointer fix');
        return;
    }
    
    if (firstLink <= startAddr || firstLink >= 0xA000) {
        console.warn(`fixBASICPointers: Invalid link $${firstLink.toString(16)} at $${startAddr.toString(16)}, program may not be loaded. Skipping.`);
        return; // Don't retry, just skip - the program might work without pointer fix
    }
    
    // Find the end of the BASIC program
    // BASIC programs are linked lists: each line starts with a link to the next line
    // The end is marked by a link of 0x0000
    let currentAddr = startAddr;
    let endAddr = startAddr;
    let maxIterations = 1000; // Safety limit
    let iterations = 0;
    
    // Traverse the linked list of BASIC lines
    while (currentAddr < 0xA000 && iterations < maxIterations) {
        iterations++;
        
        // Read the link to next line (2 bytes, little endian)
        const linkLow = mem.read(currentAddr);
        const linkHigh = mem.read(currentAddr + 1);
        const link = linkLow | (linkHigh << 8);
        
        if (link === 0) {
            // Found the end marker (00 00)
            endAddr = currentAddr + 2; // End is after the 00 00 marker
            break;
        }
        
        if (link <= startAddr || link >= 0xA000) {
            // Invalid link - stop traversal and use current position as end
            console.warn(`fixBASICPointers: Invalid link $${link.toString(16)} at $${currentAddr.toString(16)}, stopping traversal`);
            // Try to find end by looking for 00 00 pattern nearby
            let searchAddr = currentAddr + 2;
            let found = false;
            while (searchAddr < 0xA000 && searchAddr < currentAddr + 500 && !found) {
                if (mem.read(searchAddr) === 0 && mem.read(searchAddr + 1) === 0) {
                    endAddr = searchAddr + 2;
                    console.log(`fixBASICPointers: Found end marker at $${endAddr.toString(16)} by searching`);
                    found = true;
                    break;
                }
                searchAddr++;
            }
            if (!found) {
                // Estimate end based on typical program size
                endAddr = currentAddr + 200; // Safe estimate
                console.log(`fixBASICPointers: Using estimated end at $${endAddr.toString(16)}`);
            }
            break;
        }
        
        // Move to next line
        currentAddr = link;
    }
    
    if (endAddr === startAddr) {
        console.warn('Could not find end of BASIC program');
        // Try to estimate end by looking at program size
        // Our program is about 65 bytes, so end should be around 0x0801 + 65
        endAddr = 0x0801 + 100; // Safe estimate
        console.log(`Using estimated end address: $${endAddr.toString(16)}`);
    }
    
    // Set all BASIC memory pointers (as C64 does after LOAD)
    // These are the zero-page pointers the C64 uses
    
    // 0x2B-0x2C: Start of BASIC program ($0801)
    mem.write(0x2B, startAddr & 0xFF);
    mem.write(0x2C, (startAddr >> 8) & 0xFF);
    
    // 0x2D-0x2E: Start of BASIC variables (immediately after program)
    mem.write(0x2D, endAddr & 0xFF);
    mem.write(0x2E, (endAddr >> 8) & 0xFF);
    
    // 0x2F-0x30: Start of BASIC arrays (same as variables initially)
    mem.write(0x2F, endAddr & 0xFF);
    mem.write(0x30, (endAddr >> 8) & 0xFF);
    
    // 0x31-0x32: End of BASIC arrays (same as variables initially)
    mem.write(0x31, endAddr & 0xFF);
    mem.write(0x32, (endAddr >> 8) & 0xFF);
    
    // 0x33-0x34: End of BASIC program
    mem.write(0x33, endAddr & 0xFF);
    mem.write(0x34, (endAddr >> 8) & 0xFF);
    
    // 0x37-0x38: Start of free memory (should be end of program, but ensure it's safe)
    // Make sure free memory doesn't overlap with program
    const freeMemStart = Math.max(endAddr, 0x0801 + 100);
    mem.write(0x37, freeMemStart & 0xFF);
    mem.write(0x38, (freeMemStart >> 8) & 0xFF);
    
    // Also set the input buffer pointer (0x7A-0x7B) to point to input buffer
    const inputBuffer = 0x0200;
    mem.write(0x7A, inputBuffer & 0xFF);
    mem.write(0x7B, (inputBuffer >> 8) & 0xFF);
    
    // Clear keyboard buffer to prevent issues
    mem.write(0xC6, 0);
    
    // Ensure input buffer size is set correctly
    mem.write(0x0289, 0x78);
    mem.write(0x028A, 0x78);
    
    console.log(`Fixed BASIC pointers: start=$${startAddr.toString(16)}, end=$${endAddr.toString(16)}, free=$${freeMemStart.toString(16)}`);
    
    // Verify by reading back
    const verifyStart = mem.read(0x2B) | (mem.read(0x2C) << 8);
    const verifyEnd = mem.read(0x2D) | (mem.read(0x2E) << 8);
    console.log(`Verified: start=$${verifyStart.toString(16)}, end=$${verifyEnd.toString(16)}`);
}

// Alternative: Load program from URL
function loadProgramFromUrl(url, name) {
    if (!emulator || typeof emulator.loadPrg !== 'function') {
        console.error('Emulator not initialized or loadPrg not available');
        const programInfo = $('#program-info');
        programInfo.text('Emulator not ready');
        programInfo.css('color', '#ff0000');
        return;
    }
    
    const programInfo = $('#program-info');
    if (programInfo.length > 0) {
        programInfo.text(`Loading ${name || 'Program'}...`);
        programInfo.css('color', '#00cc00');
    }
    
    try {
        // JSC64 loadPrg writes directly to memory
        emulator.loadPrg(url);
        // Try to fix BASIC pointers after loading (only if needed)
        setTimeout(() => {
            const jsc64Instance = $('#emulator-container').data('c64');
            if (jsc64Instance && jsc64Instance._mem) {
                const mem = jsc64Instance._mem;
                const firstLink = mem.read(0x0801) | (mem.read(0x0802) << 8);
                // If we have a valid link, try to fix pointers
                if (firstLink > 0x0801 && firstLink < 0xA000) {
                    fixBASICPointers();
                } else {
                    console.log('Skipping fixBASICPointers - program may not need it');
                }
            }
        }, 400);
        if (programInfo.length > 0) {
            programInfo.text(`Loaded: ${name || 'Program'}`);
            programInfo.css('color', '#00cc00');
        }
    } catch (error) {
        console.error('Error loading program from URL:', error);
        if (programInfo.length > 0) {
            programInfo.text(`Error loading ${name || 'Program'}: ${error.message}`);
            programInfo.css('color', '#ff0000');
        }
    }
}

// Export for use in console or other scripts
window.loadProgramFromUrl = loadProgramFromUrl;

