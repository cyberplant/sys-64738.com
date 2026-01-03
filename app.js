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
    
    // Update status
    const programInfo = $('#program-info');
    programInfo.text('Emulator ready. Click "Load Program" to start.');
    programInfo.css('color', '#00cc00');
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
    programInfo.text(message);
    programInfo.css('color', '#ff0000');
}

function setupFileInput() {
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

function loadProgram(file) {
    const programInfo = $('#program-info');
    const reader = new FileReader();
    
    programInfo.text(`Loading ${file.name}...`);
    programInfo.css('color', '#00cc00');
    
    reader.onload = function(e) {
        const arrayBuffer = e.target.result;
        const blob = new Blob([arrayBuffer], { type: 'application/octet-stream' });
        const url = URL.createObjectURL(blob);
        
        // Load the program into JSC64
        // JSC64 stores the instance in the container's data, and loadPrg is a jQuery method
        if (emulator && typeof emulator.loadPrg === 'function') {
            try {
                // JSC64 uses loadPrg method on the container
                emulator.loadPrg(url);
                programInfo.text(`Loaded: ${file.name}`);
                programInfo.css('color', '#00cc00');
                
                // Clean up the object URL after a delay
                setTimeout(() => {
                    URL.revokeObjectURL(url);
                }, 2000);
            } catch (error) {
                console.error('Error loading program:', error);
                programInfo.text(`Error loading ${file.name}: ${error.message}`);
                programInfo.css('color', '#ff0000');
            }
        } else {
            if (!emulator) {
                programInfo.text('Emulator not initialized. Please wait...');
            } else {
                programInfo.text('JSC64 loadPrg method not available.');
            }
            programInfo.css('color', '#ff0000');
        }
    };
    
    reader.onerror = function() {
        programInfo.text('Error reading file');
        programInfo.css('color', '#ff0000');
    };
    
    reader.readAsArrayBuffer(file);
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
    programInfo.text(`Loading ${name || 'Program'}...`);
    programInfo.css('color', '#00cc00');
    
    try {
        emulator.loadPrg(url);
        programInfo.text(`Loaded: ${name || 'Program'}`);
        programInfo.css('color', '#00cc00');
    } catch (error) {
        console.error('Error loading program from URL:', error);
        programInfo.text(`Error loading ${name || 'Program'}: ${error.message}`);
        programInfo.css('color', '#ff0000');
    }
}

// Export for use in console or other scripts
window.loadProgramFromUrl = loadProgramFromUrl;

