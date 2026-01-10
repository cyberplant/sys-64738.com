// C64 Emulator Integration (VICE.js default, JSC64 fallback)
let emulator = null; // JSC64 uses this as the jQuery container

function shouldAutoLoadMain() {
    // Pages may override emulator startup behavior (e.g. dev.html).
    // Default: auto-load programs/main.prg like index.html/debug.html.
    try {
        return !(window.SYS64738_CONFIG && window.SYS64738_CONFIG.autoLoadMain === false);
    } catch (_) {
        return true;
    }
}

function getJSC64KeyboardEventListener() {
    // JSC64 accepts a jQuery object to attach keyboard listeners to.
    // Default behavior keeps legacy pages working (document-level).
    try {
        const cfg = window.SYS64738_CONFIG || {};
        const sel = cfg && cfg.jsc64KeyboardListenerSelector;
        if (sel) {
            const el = $(sel);
            if (el && el.length > 0) return el;
        }
    } catch (_) {
        // ignore
    }
    return $(document);
}

const EmulatorBackend = {
    VICE: 'vice',
    JSC64: 'jsc64'
};

let activeBackend = null;

const viceState = {
    scriptEl: null,
    running: false,
    canvas: null,
    lastStart: null,
    audioUnlockInstalled: false,
    audioUnlockHandler: null
};

// VICE.js audio policy:
// - Start muted (no WebAudio) to avoid buffer overruns before a user gesture.
// - Show a button that explicitly enables audio and reboots VICE with sound on.
const viceAudioState = {
    enabled: false
};

// Initialize when the page loads (jQuery is used by the debug UI + legacy JSC64 path)
$(document).ready(function() {
    activeBackend = detectBackendPreference();
    initializeEmulator();
    setupFileInput();
});

function detectBackendPreference() {
    // Priority: query string (?emu=vice|jsc64) -> localStorage -> default (VICE)
    try {
        const params = new URLSearchParams(window.location.search);
        const fromQuery = (params.get('emu') || '').toLowerCase();
        if (fromQuery === EmulatorBackend.VICE || fromQuery === EmulatorBackend.JSC64) {
            localStorage.setItem('sys64738.emu', fromQuery);
            return fromQuery;
        }
        const fromStorage = (localStorage.getItem('sys64738.emu') || '').toLowerCase();
        if (fromStorage === EmulatorBackend.VICE || fromStorage === EmulatorBackend.JSC64) {
            return fromStorage;
        }
    } catch (_) {
        // ignore
    }
    return EmulatorBackend.VICE;
}

function initializeEmulator() {
    const container = $('#emulator-container');

    try {
        if (activeBackend === EmulatorBackend.VICE) {
            initVICEAuto();
            return;
        }

        // Legacy / fallback: JSC64
        ensureJSC64Loaded()
            .then(() => {
                setTimeout(() => initJSC64(), 100);
            })
            .catch((error) => {
                console.error('Failed to load JSC64:', error);
                showError('Emulator library failed to load. Please refresh the page.');
            });
    } catch (error) {
        console.error('Error initializing emulator:', error);
        showError('Failed to initialize emulator. Check console for details.');
    }
}

function loadScript(src) {
    return new Promise((resolve, reject) => {
        const el = document.createElement('script');
        el.src = src;
        el.async = true;
        el.onload = () => resolve();
        el.onerror = (e) => reject(e);
        document.head.appendChild(el);
    });
}

function ensureJSC64Loaded() {
    if (typeof window.$ === 'undefined') {
        return Promise.reject(new Error('jQuery is not loaded'));
    }
    if (typeof $.fn.jsc64 !== 'undefined') {
        return Promise.resolve();
    }

    // JSC64 expects this global to resolve ROM/assets paths.
    window.JSC64_BASEPATH = 'lib/';

    // Load in order.
    return loadScript('lib/jquery.jsc64classes.js').then(() => loadScript('lib/jquery.jsc64.js'));
}

function initJSC64() {
    const container = $('#emulator-container');

    // Initialize JSC64
    // The jsc64() function takes an optional keyboardEventListener parameter.
    // Default is document-level; some pages (dev.html) scope it to the emulator container.
    container.jsc64(getJSC64KeyboardEventListener());

    // Get the JSC64 instance from the container's data
    emulator = container;

    // Scale canvas to fill container
    scaleCanvas();

    // Re-scale on window resize
    $(window).on('resize', scaleCanvas);

    console.log('C64 Emulator initialized (JSC64)');

    // Try to auto-load the compiled program if it exists (unless disabled by page config)
    if (shouldAutoLoadMain()) {
        autoLoadProgram();
    }

    // Update status (only if program-info element exists - debug page)
    const programInfo = $('#program-info');
    if (programInfo.length > 0) {
        programInfo.text('Emulator ready. Click "Load Program" to start.');
        programInfo.css('color', '#00cc00');
    }
}

function setProgramInfo(message, color = '#00cc00') {
    const programInfo = $('#program-info');
    if (programInfo.length > 0) {
        programInfo.text(message);
        programInfo.css('color', color);
    }
}

function audioDetected() {
    // From vice.js README examples
    return (typeof Audio === 'function' && typeof new Audio().mozSetup === 'function') ||
        (typeof AudioContext === 'function') ||
        (typeof webkitAudioContext === 'function');
}

function canEnableViceAudio() {
    return audioDetected();
}

function ensureViceAudioOverlay() {
    if (activeBackend !== EmulatorBackend.VICE) return;

    const container = document.getElementById('emulator-container');
    if (!container) return;

    let overlay = document.getElementById('vice-audio-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'vice-audio-overlay';
        overlay.className = 'vice-audio-overlay';
        overlay.innerHTML = [
            '<div class="vice-audio-card">',
            '  <div class="vice-audio-title">Audio is OFF</div>',
            '  <div class="vice-audio-sub">Press to enable sound</div>',
            '  <button type="button" id="vice-audio-enable-btn" class="btn vice-audio-btn">Turn audio ON</button>',
            '</div>'
        ].join('\n');
        container.appendChild(overlay);

        const btn = document.getElementById('vice-audio-enable-btn');
        if (btn) {
            btn.addEventListener('click', function() {
                requestEnableViceAudio();
            });
        }
    }

    // Update visibility/message based on current state/support.
    if (viceAudioState.enabled) {
        overlay.style.display = 'none';
        return;
    }

    if (!canEnableViceAudio()) {
        overlay.style.display = '';
        overlay.classList.add('is-disabled');
        const title = overlay.querySelector('.vice-audio-title');
        const sub = overlay.querySelector('.vice-audio-sub');
        const btn = overlay.querySelector('#vice-audio-enable-btn');
        if (title) title.textContent = 'Audio unavailable';
        if (sub) sub.textContent = 'Your browser does not support WebAudio.';
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Audio not supported';
        }
        return;
    }

    overlay.style.display = '';
    overlay.classList.remove('is-disabled');
    const title = overlay.querySelector('.vice-audio-title');
    const sub = overlay.querySelector('.vice-audio-sub');
    const btn = overlay.querySelector('#vice-audio-enable-btn');
    if (title) title.textContent = 'Audio is OFF';
    if (sub) sub.textContent = 'Press to enable sound';
    if (btn) {
        btn.disabled = false;
        btn.textContent = 'Turn audio ON';
    }
}

function primeViceAudioContextForGesture() {
    // Create/resume AudioContext within a user gesture, so VICE.js can use it later
    // without hitting autoplay restrictions.
    try {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return;
        window.SDL = window.SDL || {};
        if (!window.SDL.audioContext) {
            window.SDL.audioContext = new AC();
        }
        const ctx = window.SDL.audioContext;
        if (ctx && typeof ctx.resume === 'function' && ctx.state === 'suspended') {
            // Best-effort; some browsers still gate resume.
            ctx.resume().catch(() => {});
        }
    } catch (_) {
        // ignore
    }
}

function requestEnableViceAudio() {
    if (viceAudioState.enabled) return;
    if (!canEnableViceAudio()) return;

    // Must be called from a user gesture (button click).
    primeViceAudioContextForGesture();
    viceAudioState.enabled = true;

    // Update UI promptly.
    try {
        const overlay = document.getElementById('vice-audio-overlay');
        if (overlay) {
            const btn = overlay.querySelector('#vice-audio-enable-btn');
            const sub = overlay.querySelector('.vice-audio-sub');
            if (btn) {
                btn.disabled = true;
                btn.textContent = 'Enabling...';
            }
            if (sub) sub.textContent = 'Restarting emulator with sound...';
        }
    } catch (_) {
        // ignore
    }

    // Reboot VICE with sound enabled (fresh args). Preserve the last loaded program.
    if (activeBackend === EmulatorBackend.VICE) {
        const last = viceState.lastStart || {};
        startVICE({
            programName: last.programName,
            programUrl: last.programUrl,
            programBytes: last.programBytes
        });
    }
}

function initVICEAuto() {
    // Create a canvas and boot VICE.js, auto-starting programs/main.prg if present.
    console.log('C64 Emulator initializing (VICE.js)');

    // Scale on resize (VICE uses a single canvas)
    $(window).off('resize', scaleCanvas).on('resize', scaleCanvas);

    setProgramInfo('Starting emulator (VICE.js)...', '#00cc00');

    if (shouldAutoLoadMain()) {
        // Default behavior mirrors the existing JSC64 auto-load behavior.
        startVICE({
            programName: 'main.prg',
            programUrl: 'programs/main.prg'
        });
    } else {
        // Boot emulator without autostarting a program (dev.html uses RUN to load programs).
        startVICE({});
        setProgramInfo('Emulator ready. Use the editor RUN button to load a program.', '#00cc00');
    }
}

function teardownVICE() {
    viceState.running = false;
    viceState.canvas = null;

    // Try to stop the runtime if it exposes a quit hook (not guaranteed).
    try {
        if (window.Module && typeof window.Module.quit === 'function') {
            window.Module.quit(0, new Error('VICE reboot'));
        }
    } catch (_) {
        // ignore
    }

    // Remove injected script so we can re-inject on reboot.
    if (viceState.scriptEl && viceState.scriptEl.parentNode) {
        viceState.scriptEl.parentNode.removeChild(viceState.scriptEl);
    }
    viceState.scriptEl = null;

    // Clear container and any lingering global Module reference.
    try {
        delete window.Module;
    } catch (_) {
        window.Module = undefined;
    }

    const container = document.getElementById('emulator-container');
    if (container) {
        container.innerHTML = '';
    }
}

function ensureVICECanvas() {
    const container = document.getElementById('emulator-container');
    if (!container) {
        throw new Error('Missing #emulator-container');
    }

    // Recreate content; VICE requires a canvas without border/padding.
    container.innerHTML = '';

    const canvas = document.createElement('canvas');
    canvas.id = 'vice-canvas';
    canvas.style.border = '0px none';
    canvas.style.padding = '0';
    canvas.style.margin = '0';
    container.appendChild(canvas);

    viceState.canvas = canvas;
    return canvas;
}

function loadViceRuntime() {
    return new Promise((resolve, reject) => {
        const el = document.createElement('script');
        el.src = 'lib/vice/x64.js';
        el.async = true;
        el.onload = () => resolve();
        el.onerror = (e) => reject(e);
        document.head.appendChild(el);
        viceState.scriptEl = el;
    });
}

function buildViceArguments(programName) {
    // Start muted by default. Only enable sound after the user explicitly requests it.
    // NOTE: VICE uses "+sound" to disable sound and "-sound" to enable sound.
    // If sound is enabled but WebAudio is still gesture-blocked, VICE can overrun its
    // internal buffers. We avoid that by starting with sound explicitly OFF.
    const audioArgs = (viceAudioState.enabled && audioDetected())
        ? ['-sound', '-soundsync', '0', '-soundrate', '22050', '-soundfragsize', '2']
        : ['+sound'];

    // VICE autostart works for PRG/D64 etc.
    if (!programName) {
        return audioArgs;
    }
    return ['-autostart', programName].concat(audioArgs);
}

function startVICE({ programName, programUrl, programBytes }) {
    // Remember what we last booted so we can reboot with audio enabled.
    viceState.lastStart = { programName, programUrl, programBytes };

    teardownVICE();

    const canvas = ensureVICECanvas();
    ensureViceAudioOverlay();
    const viceArgs = buildViceArguments(programName);

    function loadFiles() {
        if (typeof FS === 'undefined' || !FS.createDataFile) {
            throw new Error('VICE FS is not available');
        }

        if (programBytes) {
            if (!programName) {
                throw new Error('Missing programName for programBytes');
            }
            FS.createDataFile('/', programName, new Uint8Array(programBytes), true, true);
            return;
        }

        if (programUrl) {
            if (!programName) {
                throw new Error('Missing programName for programUrl');
            }
            // Block program start until we fetch the file.
            const depId = `fetch:${programUrl}`;
            addRunDependency(depId);
            fetch(programUrl)
                .then((response) => {
                    if (!response.ok) {
                        throw new Error(`Failed to fetch ${programUrl} (${response.status})`);
                    }
                    return response.arrayBuffer();
                })
                .then((buf) => {
                    FS.createDataFile('/', programName, new Uint8Array(buf), true, true);
                })
                .catch((err) => {
                    console.warn('VICE autoload failed:', err);
                    setProgramInfo('Auto-load failed (program not found). Use debug.html to load a file, or run ./compile.sh to generate programs/main.prg.', '#ffaa00');
                })
                .finally(() => {
                    removeRunDependency(depId);
                });
        }
    }

    // Global Module is consumed by VICE.js (Emscripten output).
    window.Module = {
        preRun: [loadFiles],
        arguments: viceArgs,
        canvas,
        print: function(text) {
            // Keep noisy output out of the UI but available for debugging.
            if (text) console.log(text);
        },
        printErr: function(text) {
            if (text) console.warn(text);
        },
        onRuntimeInitialized: function() {
            viceState.running = true;
            console.log('C64 Emulator initialized (VICE.js)');
            setProgramInfo('Emulator ready (VICE.js).', '#00cc00');
            // Only install auto-resume after the user has opted in to sound.
            if (viceAudioState.enabled) {
                installViceAudioUnlock();
            }
            ensureViceAudioOverlay();
            // Apply scaling once the canvas exists.
            setTimeout(scaleCanvas, 50);
        }
    };

    loadViceRuntime().catch((e) => {
        console.error('Failed to load VICE.js runtime, falling back to JSC64:', e);
        setProgramInfo('VICE.js failed to load; falling back to JSC64...', '#ffaa00');
        activeBackend = EmulatorBackend.JSC64;
        initializeEmulator();
    });
}

function resumeViceAudio() {
    if (!viceAudioState.enabled) return;
    // VICE.js (Emscripten SDL) stores the WebAudio context at SDL.audioContext.
    const ctx = (typeof window.SDL !== 'undefined' && window.SDL && window.SDL.audioContext)
        ? window.SDL.audioContext
        : null;

    if (!ctx || typeof ctx.resume !== 'function') {
        return;
    }

    // If the browser blocked audio on page load, the context is usually "suspended".
    if (ctx.state === 'suspended') {
        ctx.resume().catch((e) => {
            // Still blocked or failed; nothing else we can do without further user gestures.
            console.warn('Could not resume AudioContext:', e);
        });
    }
}

function installViceAudioUnlock() {
    if (viceState.audioUnlockInstalled) return;
    viceState.audioUnlockInstalled = true;

    // After audio is enabled, keep it resilient to tab focus changes, etc.
    viceState.audioUnlockHandler = () => resumeViceAudio();

    // Capture phase to run ASAP on the gesture.
    document.addEventListener('pointerdown', viceState.audioUnlockHandler, { capture: true, passive: true });
    document.addEventListener('touchstart', viceState.audioUnlockHandler, { capture: true, passive: true });
    document.addEventListener('keydown', viceState.audioUnlockHandler, { capture: true, passive: true });
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
                            // Clear BASIC area first to prevent memory corruption from old programs
                            clearBASICArea();
                            // Load the program (exactly like manual load)
                            emulator.loadPrg(url);

                            // Fix BASIC pointers immediately after loading (before RUN command executes)
                            const jsc64Instance = $('#emulator-container').data('c64');
                            if (jsc64Instance && jsc64Instance._mem) {
                                const mem = jsc64Instance._mem;
                                const firstLink = mem.read(0x0801) | (mem.read(0x0802) << 8);
                                // If we have a valid link, fix pointers
                                if (firstLink > 0x0801 && firstLink < 0xA000) {
                                    fixBASICPointers();
                                } else {
                                    console.log('Auto-load: Skipping fixBASICPointers - program may not be loaded correctly');
                                }
                            }

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

    // Use the canvas' intrinsic size when available (VICE.js uses a single canvas;
    // JSC64 uses multiple canvases). Fall back to typical C64 framing.
    const firstCanvas = canvases.get(0);
    const c64Width = (firstCanvas && firstCanvas.width) ? firstCanvas.width : 403;
    const c64Height = (firstCanvas && firstCanvas.height) ? firstCanvas.height : 284;
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
    if (activeBackend === EmulatorBackend.VICE) {
        return loadProgramVICE(file);
    }
    return loadProgramJSC64(file);
}

function loadProgramVICE(file) {
    const reader = new FileReader();

    setProgramInfo(`Loading ${file.name} (VICE.js)...`, '#00cc00');

    reader.onload = function(e) {
        const arrayBuffer = e.target.result;
        try {
            // Reboot emulator with the new program in its virtual FS.
            startVICE({
                programName: file.name,
                programBytes: arrayBuffer
            });
        } catch (error) {
            console.error('Error loading program (VICE.js):', error);
            setProgramInfo(`Error loading ${file.name}: ${error.message}`, '#ff0000');
        }
    };

    reader.onerror = function() {
        setProgramInfo('Error reading file', '#ff0000');
    };

    reader.readAsArrayBuffer(file);
}

function loadProgramJSC64(file) {
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
                    // Clear BASIC area first to prevent memory corruption from old programs
                    clearBASICArea();
                    // JSC64 uses loadPrg method on the container
                    emulator.loadPrg(url);
                    // Fix BASIC pointers immediately after loading (before RUN command executes)
                    // loadPrg is synchronous, so memory is written by the time it returns
                    const jsc64Instance = $('#emulator-container').data('c64');
                    if (jsc64Instance && jsc64Instance._mem) {
                        const mem = jsc64Instance._mem;
                        const firstLink = mem.read(0x0801) | (mem.read(0x0802) << 8);
                        // If we have a valid link, fix pointers
                        if (firstLink > 0x0801 && firstLink < 0xA000) {
                            fixBASICPointers();
                        } else {
                            console.log('Skipping fixBASICPointers - program may not be loaded correctly');
                        }
                    }
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

    // 0x33-0x34: End of BASIC program
    mem.write(0x33, endAddr & 0xFF);
    mem.write(0x34, (endAddr >> 8) & 0xFF);

    // 0x37-0x38: Start of free memory
    // On a real C64, this is typically 0xA000 (40KB) with default screen at 0x0400
    // This leaves room for variables and arrays between endAddr and freeMemStart
    const freeMemStart = 0xA000;
    mem.write(0x37, freeMemStart & 0xFF);
    mem.write(0x38, (freeMemStart >> 8) & 0xFF);

    // 0x31-0x32: End of BASIC arrays (should point to free memory start)
    // This allows arrays to grow from arrays start (0x2F-0x30) up to free memory
    mem.write(0x31, freeMemStart & 0xFF);
    mem.write(0x32, (freeMemStart >> 8) & 0xFF);

    // Also set the input buffer pointer (0x7A-0x7B) to point to input buffer
    const inputBuffer = 0x0200;
    mem.write(0x7A, inputBuffer & 0xFF);
    mem.write(0x7B, (inputBuffer >> 8) & 0xFF);

    // Don't clear keyboard buffer here - loadPrg may have injected a RUN command
    // that we want to preserve

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
    if (activeBackend === EmulatorBackend.VICE) {
        const programName = name || (String(url).split('/').pop() || 'program.prg');
        setProgramInfo(`Loading ${programName} (VICE.js)...`, '#00cc00');
        try {
            startVICE({
                programName,
                programUrl: url
            });
        } catch (error) {
            console.error('Error loading program from URL (VICE.js):', error);
            setProgramInfo(`Error loading ${programName}: ${error.message}`, '#ff0000');
        }
        return;
    }

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
        // Clear BASIC area first to prevent memory corruption from old programs
        clearBASICArea();
        // JSC64 loadPrg writes directly to memory
        emulator.loadPrg(url);
        // Fix BASIC pointers immediately after loading (before RUN command executes)
        const jsc64Instance = $('#emulator-container').data('c64');
        if (jsc64Instance && jsc64Instance._mem) {
            const mem = jsc64Instance._mem;
            const firstLink = mem.read(0x0801) | (mem.read(0x0802) << 8);
            // If we have a valid link, fix pointers
            if (firstLink > 0x0801 && firstLink < 0xA000) {
                fixBASICPointers();
            } else {
                console.log('Skipping fixBASICPointers - program may not be loaded correctly');
            }
        }
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

