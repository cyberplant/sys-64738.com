/* global loadProgramFromUrl */

// Minimal C64 BASIC v2 tokenizer + PRG builder (inspired by petcat -w2 -h).
// Produces a BASIC program PRG that loads at $0801.

(function() {
    const LOAD_ADDR = 0x0801;

    // BASIC v2 token table (C64). Longest matches must win (e.g. PRINT# before PRINT).
    // Reference: CBM BASIC 2.0 keyword tokens 0x80-0xCB.
    const KEYWORDS = [
        ['PRINT#', 0x98],
        ['INPUT#', 0x84],
        ['TAB(', 0xA3],
        ['SPC(', 0xA6],
        ['STR$', 0xC4],
        ['CHR$', 0xC7],
        ['LEFT$', 0xC8],
        ['RIGHT$', 0xC9],
        ['MID$', 0xCA],
        ['GOTO', 0x89],
        ['GOSUB', 0x8D],
        ['THEN', 0xA7],
        ['STEP', 0xA9],
        ['RESTORE', 0x8C],
        ['RETURN', 0x8E],
        ['VERIFY', 0x95],
        ['DEF', 0x96],
        ['POKE', 0x97],
        ['PRINT', 0x99],
        ['CONT', 0x9A],
        ['LIST', 0x9B],
        ['CLR', 0x9C],
        ['CMD', 0x9D],
        ['SYS', 0x9E],
        ['OPEN', 0x9F],
        ['CLOSE', 0xA0],
        ['GET', 0xA1],
        ['NEW', 0xA2],
        ['TO', 0xA4],
        ['FN', 0xA5],
        ['NOT', 0xA8],
        ['AND', 0xAF],
        ['OR', 0xB0],
        ['SGN', 0xB4],
        ['INT', 0xB5],
        ['ABS', 0xB6],
        ['USR', 0xB7],
        ['FRE', 0xB8],
        ['POS', 0xB9],
        ['SQR', 0xBA],
        ['RND', 0xBB],
        ['LOG', 0xBC],
        ['EXP', 0xBD],
        ['COS', 0xBE],
        ['SIN', 0xBF],
        ['TAN', 0xC0],
        ['ATN', 0xC1],
        ['PEEK', 0xC2],
        ['LEN', 0xC3],
        ['VAL', 0xC5],
        ['ASC', 0xC6],
        ['GO', 0xCB],
        ['END', 0x80],
        ['FOR', 0x81],
        ['NEXT', 0x82],
        ['DATA', 0x83],
        ['INPUT', 0x85],
        ['DIM', 0x86],
        ['READ', 0x87],
        ['LET', 0x88],
        ['RUN', 0x8A],
        ['IF', 0x8B],
        ['REM', 0x8F],
        ['STOP', 0x90],
        ['ON', 0x91],
        ['WAIT', 0x92],
        ['LOAD', 0x93],
        ['SAVE', 0x94],

        // Operators / relations (BASIC stores these as tokens too)
        ['+', 0xAA],
        ['-', 0xAB],
        ['*', 0xAC],
        ['/', 0xAD],
        ['^', 0xAE],
        ['>', 0xB1],
        ['=', 0xB2],
        ['<', 0xB3]
    ].sort((a, b) => b[0].length - a[0].length);

    const KEYWORD_SET = new Set(KEYWORDS.map(([k]) => k));

    function isWordChar(ch) {
        return /[A-Za-z0-9]/.test(ch || '');
    }

    function encodeCharToPetsciiByte(ch) {
        // Very small ASCII->PETSCII-ish mapping:
        // - Force letters to uppercase (matches typical BASIC listings).
        // - Keep ASCII for punctuation/digits/space.
        if (ch === '\t') ch = ' ';
        const code = ch.charCodeAt(0);
        if (code >= 0x61 && code <= 0x7A) {
            return code - 0x20; // a-z -> A-Z
        }
        if (code >= 0x20 && code <= 0x7E) {
            return code & 0xFF;
        }
        // Replace unsupported chars
        return 0x3F; // '?'
    }

    function tokenizeBasicLine(text) {
        const out = [];
        let i = 0;
        let inString = false;
        let inRem = false;

        while (i < text.length) {
            const ch = text[i];

            if (inRem) {
                out.push(encodeCharToPetsciiByte(ch));
                i++;
                continue;
            }

            if (inString) {
                out.push(encodeCharToPetsciiByte(ch));
                if (ch === '"') inString = false;
                i++;
                continue;
            }

            if (ch === '"') {
                inString = true;
                out.push(encodeCharToPetsciiByte(ch));
                i++;
                continue;
            }

            // Shorthand: ? = PRINT
            if (ch === '?') {
                out.push(0x99);
                i++;
                continue;
            }

            // Try keyword/operator match at this position.
            const prev = i > 0 ? text[i - 1] : '';
            const restUpper = text.slice(i).toUpperCase();

            let matched = false;
            for (const [kw, token] of KEYWORDS) {
                if (!restUpper.startsWith(kw)) continue;

                // Boundary checks to avoid tokenizing inside identifiers (e.g., PRINTA).
                const next = text[i + kw.length] || '';
                const kwLast = kw[kw.length - 1];
                const kwStartsWithAlpha = /[A-Z]/.test(kw[0]);
                const kwEndsLikeWord = /[A-Z0-9$]/.test(kwLast);

                if (kwStartsWithAlpha && isWordChar(prev)) {
                    continue;
                }
                if (kwEndsLikeWord && isWordChar(next)) {
                    continue;
                }

                out.push(token);
                i += kw.length;
                matched = true;

                if (kw === 'REM') {
                    inRem = true;
                }
                break;
            }

            if (matched) continue;

            out.push(encodeCharToPetsciiByte(ch));
            i++;
        }

        return out;
    }

    function parseBasicSource(source) {
        const norm = String(source || '')
            .replace(/\r\n/g, '\n')
            .replace(/\r/g, '\n');

        const rawLines = norm.split('\n');
        const lines = [];

        let nextAuto = 10;
        for (const raw of rawLines) {
            const trimmed = raw.replace(/\s+$/g, '');
            if (!trimmed.trim()) continue;

            const m = trimmed.match(/^\s*(\d+)\s*(.*)$/);
            if (m) {
                lines.push({ number: parseInt(m[1], 10), text: m[2] || '' });
            } else {
                lines.push({ number: nextAuto, text: trimmed.trimStart() });
                nextAuto += 10;
            }
        }

        // Sort like BASIC does.
        lines.sort((a, b) => a.number - b.number);

        // Validate duplicates/out-of-range.
        for (let i = 0; i < lines.length; i++) {
            const n = lines[i].number;
            if (!Number.isFinite(n) || n < 0 || n > 63999) {
                throw new Error(`Invalid line number: ${lines[i].number}`);
            }
            if (i > 0 && n === lines[i - 1].number) {
                throw new Error(`Duplicate line number: ${n}`);
            }
        }

        return lines;
    }

    function compileBasicV2ToPrg(source) {
        const lines = parseBasicSource(source);

        // Each line (without link) is: [lineNoLo lineNoHi][tokenized...][0x00]
        const compiled = lines.map((l) => {
            const tokenBytes = tokenizeBasicLine(l.text);
            return {
                number: l.number,
                body: new Uint8Array([
                    l.number & 0xFF,
                    (l.number >> 8) & 0xFF,
                    ...tokenBytes,
                    0x00
                ])
            };
        });

        // Compute addresses and build final program (without PRG header).
        const lineStarts = [];
        let offset = 0;

        // Each stored line is: [linkLo linkHi] + body
        for (const entry of compiled) {
            lineStarts.push(LOAD_ADDR + offset);
            offset += 2 + entry.body.length;
        }
        const endMarkerAddr = LOAD_ADDR + offset;

        // Program bytes (linked list + 00 00 end marker).
        const programLen = offset + 2;
        const program = new Uint8Array(programLen);

        let writeAt = 0;
        for (let idx = 0; idx < compiled.length; idx++) {
            const nextAddr = (idx + 1 < compiled.length) ? lineStarts[idx + 1] : endMarkerAddr;
            program[writeAt++] = nextAddr & 0xFF;
            program[writeAt++] = (nextAddr >> 8) & 0xFF;
            program.set(compiled[idx].body, writeAt);
            writeAt += compiled[idx].body.length;
        }

        // End marker (two zeros)
        program[writeAt++] = 0x00;
        program[writeAt++] = 0x00;

        // PRG header (load address, little-endian) + program bytes
        const prg = new Uint8Array(2 + program.length);
        prg[0] = LOAD_ADDR & 0xFF;
        prg[1] = (LOAD_ADDR >> 8) & 0xFF;
        prg.set(program, 2);
        return prg;
    }

    // --- Basic syntax highlighting (simple, no external deps) ---

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function highlightLine(line) {
        // Leading line number
        const m = line.match(/^(\s*)(\d+)(\s*)(.*)$/);
        let prefix = '';
        let rest = line;
        if (m) {
            prefix = `${escapeHtml(m[1])}<span class="bas-ln">${escapeHtml(m[2])}</span>${escapeHtml(m[3])}`;
            rest = m[4] || '';
        }

        let out = '';
        let i = 0;
        let inString = false;
        let inRem = false;

        while (i < rest.length) {
            const ch = rest[i];

            if (inRem) {
                out += `<span class="bas-com">${escapeHtml(rest.slice(i))}</span>`;
                break;
            }

            if (inString) {
                const j = rest.indexOf('"', i);
                if (j === -1) {
                    out += `<span class="bas-str">${escapeHtml(rest.slice(i))}</span>`;
                    break;
                }
                out += `<span class="bas-str">${escapeHtml(rest.slice(i, j + 1))}</span>`;
                i = j + 1;
                inString = false;
                continue;
            }

            if (ch === '"') {
                inString = true;
                i++;
                out += `<span class="bas-str">"</span>`;
                continue;
            }

            if (ch === '?') {
                out += `<span class="bas-kw">?</span>`;
                i++;
                continue;
            }

            // Keyword match
            const prev = i > 0 ? rest[i - 1] : '';
            const up = rest.slice(i).toUpperCase();
            let matched = false;
            for (const [kw] of KEYWORDS) {
                if (!KEYWORD_SET.has(kw)) continue;
                if (!up.startsWith(kw)) continue;

                const next = rest[i + kw.length] || '';
                const kwLast = kw[kw.length - 1];
                const kwStartsWithAlpha = /[A-Z]/.test(kw[0]);
                const kwEndsLikeWord = /[A-Z0-9$]/.test(kwLast);

                if (kwStartsWithAlpha && isWordChar(prev)) continue;
                if (kwEndsLikeWord && isWordChar(next)) continue;

                const rawKw = rest.slice(i, i + kw.length);
                out += `<span class="bas-kw">${escapeHtml(rawKw)}</span>`;
                i += kw.length;
                matched = true;
                if (kw === 'REM') inRem = true;
                break;
            }
            if (matched) continue;

            // Numbers
            const num = rest.slice(i).match(/^\d+(\.\d+)?/);
            if (num) {
                out += `<span class="bas-num">${escapeHtml(num[0])}</span>`;
                i += num[0].length;
                continue;
            }

            out += escapeHtml(ch);
            i++;
        }

        return prefix + out;
    }

    function renderHighlight(text) {
        const lines = String(text || '')
            .replace(/\r\n/g, '\n')
            .replace(/\r/g, '\n')
            .split('\n');
        // Always end with a newline so caret positioning matches pre height.
        return lines.map(highlightLine).join('\n') + '\n';
    }

    function setStatus(message, kind) {
        const el = document.getElementById('dev-status');
        if (!el) return;
        el.textContent = message;
        el.classList.remove('is-ok', 'is-warn', 'is-err');
        if (kind === 'ok') el.classList.add('is-ok');
        if (kind === 'warn') el.classList.add('is-warn');
        if (kind === 'err') el.classList.add('is-err');
    }

    function bootEditor() {
        const editor = document.getElementById('basic-editor');
        const highlight = document.getElementById('basic-highlight');
        const runBtn = document.getElementById('run-btn');
        if (!editor || !highlight || !runBtn) return;

        // Show build sha (and avoid caching for the build-info fetch).
        (function() {
            const shaEl = document.getElementById('build-sha');
            if (!shaEl) return;

            const cfgSha = (window.SYS64738_CONFIG && window.SYS64738_CONFIG.buildSha) ? String(window.SYS64738_CONFIG.buildSha) : '';
            if (cfgSha) shaEl.textContent = cfgSha;

            fetch(`build-info.json?t=${Date.now()}`, { cache: 'no-store' })
                .then((r) => (r.ok ? r.json() : Promise.reject(new Error('build-info.json not found'))))
                .then((info) => {
                    if (info && info.sha) shaEl.textContent = String(info.sha);
                })
                .catch(() => {
                    // ignore (local dev may not have build-info.json)
                });
        })();

        // When the editor is focused, keep the emulator from receiving keystrokes.
        // This is important for VICE.js (document-level handlers) and is a safety net in general.
        function swallowIfEditing(e) {
            if (document.activeElement === editor) {
                e.stopImmediatePropagation();
            }
        }
        document.addEventListener('keydown', swallowIfEditing, true);
        document.addEventListener('keypress', swallowIfEditing, true);
        document.addEventListener('keyup', swallowIfEditing, true);

        function sync() {
            highlight.innerHTML = renderHighlight(editor.value);
            // Keep scroll positions aligned.
            highlight.scrollTop = editor.scrollTop;
            highlight.scrollLeft = editor.scrollLeft;
        }

        editor.addEventListener('input', sync);
        editor.addEventListener('scroll', sync);

        runBtn.addEventListener('click', function() {
            try {
                const prg = compileBasicV2ToPrg(editor.value);
                const blob = new Blob([prg], { type: 'application/octet-stream' });
                const url = URL.createObjectURL(blob);

                if (typeof loadProgramFromUrl !== 'function') {
                    throw new Error('Emulator loader is not available yet');
                }

                setStatus(`Compiled ${prg.length} bytes. Loading...`, 'ok');
                loadProgramFromUrl(url, 'dev.prg');

                setTimeout(() => URL.revokeObjectURL(url), 5000);
            } catch (e) {
                setStatus(String(e && e.message ? e.message : e), 'err');
                // eslint-disable-next-line no-console
                console.error(e);
            }
        });

        // Load initial content (prefer src/main.bas if served)
        fetch('src/main.bas')
            .then((r) => (r.ok ? r.text() : Promise.reject(new Error('src/main.bas not found'))))
            .then((t) => {
                editor.value = t;
                sync();
            })
            .catch(() => {
                editor.value = [
                    '10 PRINT "HELLO FROM DEV.HTML"',
                    '20 FOR I=1 TO 200:NEXT I',
                    '30 GOTO 10'
                ].join('\n');
                sync();
            });
    }

    // Wait for DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootEditor);
    } else {
        bootEditor();
    }
})();

