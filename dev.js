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

    // --- 6502 assembler (minimal but practical) ---

    const BRANCH_MNEMONICS = new Set(['BPL', 'BMI', 'BVC', 'BVS', 'BCC', 'BCS', 'BNE', 'BEQ']);

    // Legal 6502 opcodes (common subset is still broad; we include the standard set)
    const OPCODES = {
        ADC: { imm: 0x69, zp: 0x65, zpx: 0x75, abs: 0x6D, absx: 0x7D, absy: 0x79, indx: 0x61, indy: 0x71 },
        AND: { imm: 0x29, zp: 0x25, zpx: 0x35, abs: 0x2D, absx: 0x3D, absy: 0x39, indx: 0x21, indy: 0x31 },
        ASL: { acc: 0x0A, zp: 0x06, zpx: 0x16, abs: 0x0E, absx: 0x1E },
        BCC: { rel: 0x90 }, BCS: { rel: 0xB0 }, BEQ: { rel: 0xF0 }, BMI: { rel: 0x30 }, BNE: { rel: 0xD0 }, BPL: { rel: 0x10 }, BVC: { rel: 0x50 }, BVS: { rel: 0x70 },
        BIT: { zp: 0x24, abs: 0x2C },
        BRK: { imp: 0x00 },
        CLC: { imp: 0x18 }, CLD: { imp: 0xD8 }, CLI: { imp: 0x58 }, CLV: { imp: 0xB8 },
        CMP: { imm: 0xC9, zp: 0xC5, zpx: 0xD5, abs: 0xCD, absx: 0xDD, absy: 0xD9, indx: 0xC1, indy: 0xD1 },
        CPX: { imm: 0xE0, zp: 0xE4, abs: 0xEC },
        CPY: { imm: 0xC0, zp: 0xC4, abs: 0xCC },
        DEC: { zp: 0xC6, zpx: 0xD6, abs: 0xCE, absx: 0xDE },
        DEX: { imp: 0xCA }, DEY: { imp: 0x88 },
        EOR: { imm: 0x49, zp: 0x45, zpx: 0x55, abs: 0x4D, absx: 0x5D, absy: 0x59, indx: 0x41, indy: 0x51 },
        INC: { zp: 0xE6, zpx: 0xF6, abs: 0xEE, absx: 0xFE },
        INX: { imp: 0xE8 }, INY: { imp: 0xC8 },
        JMP: { abs: 0x4C, ind: 0x6C },
        JSR: { abs: 0x20 },
        LDA: { imm: 0xA9, zp: 0xA5, zpx: 0xB5, abs: 0xAD, absx: 0xBD, absy: 0xB9, indx: 0xA1, indy: 0xB1 },
        LDX: { imm: 0xA2, zp: 0xA6, zpy: 0xB6, abs: 0xAE, absy: 0xBE },
        LDY: { imm: 0xA0, zp: 0xA4, zpx: 0xB4, abs: 0xAC, absx: 0xBC },
        LSR: { acc: 0x4A, zp: 0x46, zpx: 0x56, abs: 0x4E, absx: 0x5E },
        NOP: { imp: 0xEA },
        ORA: { imm: 0x09, zp: 0x05, zpx: 0x15, abs: 0x0D, absx: 0x1D, absy: 0x19, indx: 0x01, indy: 0x11 },
        PHA: { imp: 0x48 }, PHP: { imp: 0x08 }, PLA: { imp: 0x68 }, PLP: { imp: 0x28 },
        ROL: { acc: 0x2A, zp: 0x26, zpx: 0x36, abs: 0x2E, absx: 0x3E },
        ROR: { acc: 0x6A, zp: 0x66, zpx: 0x76, abs: 0x6E, absx: 0x7E },
        RTI: { imp: 0x40 }, RTS: { imp: 0x60 },
        SBC: { imm: 0xE9, zp: 0xE5, zpx: 0xF5, abs: 0xED, absx: 0xFD, absy: 0xF9, indx: 0xE1, indy: 0xF1 },
        SEC: { imp: 0x38 }, SED: { imp: 0xF8 }, SEI: { imp: 0x78 },
        STA: { zp: 0x85, zpx: 0x95, abs: 0x8D, absx: 0x9D, absy: 0x99, indx: 0x81, indy: 0x91 },
        STX: { zp: 0x86, zpy: 0x96, abs: 0x8E },
        STY: { zp: 0x84, zpx: 0x94, abs: 0x8C },
        TAX: { imp: 0xAA }, TAY: { imp: 0xA8 }, TSX: { imp: 0xBA }, TXA: { imp: 0x8A }, TXS: { imp: 0x9A }, TYA: { imp: 0x98 }
    };

    function stripAsmComment(line) {
        // Strip ';' and '//' comments, ignoring them inside double quotes.
        let inStr = false;
        for (let i = 0; i < line.length; i++) {
            const ch = line[i];
            if (ch === '"') inStr = !inStr;
            if (!inStr && ch === ';') return line.slice(0, i);
            if (!inStr && ch === '/' && line[i + 1] === '/') return line.slice(0, i);
        }
        return line;
    }

    function parseAsmStringLiteral(s) {
        // s includes surrounding quotes
        const raw = s.slice(1, -1);
        const out = [];
        for (let i = 0; i < raw.length; i++) {
            const ch = raw[i];
            if (ch === '\\') {
                const n = raw[i + 1] || '';
                if (n === 'n') { out.push(0x0D); i++; continue; } // CR (C64 newline)
                if (n === 'r') { out.push(0x0D); i++; continue; }
                if (n === 't') { out.push(0x09); i++; continue; }
                if (n === '"') { out.push(0x22); i++; continue; }
                if (n === '\\') { out.push(0x5C); i++; continue; }
                if (n === 'x') {
                    const h = raw.slice(i + 2, i + 4);
                    if (!/^[0-9a-fA-F]{2}$/.test(h)) throw new Error(`Invalid \\x escape: \\x${h}`);
                    out.push(parseInt(h, 16) & 0xFF);
                    i += 3;
                    continue;
                }
                // Unknown escape: treat literally (best-effort)
            }
            out.push(encodeCharToPetsciiByte(ch));
        }
        return out;
    }

    function tokenizeExpr(expr) {
        const s = String(expr || '').trim();
        const tokens = [];
        let i = 0;
        while (i < s.length) {
            const ch = s[i];
            if (/\s/.test(ch)) { i++; continue; }
            if (ch === '(' || ch === ')' || ch === '+' || ch === '-' || ch === '<' || ch === '>' ) {
                tokens.push({ t: ch });
                i++;
                continue;
            }
            if (ch === '*') {
                tokens.push({ t: 'PC' });
                i++;
                continue;
            }
            if (ch === '$') {
                const m = s.slice(i + 1).match(/^[0-9a-fA-F]+/);
                if (!m) throw new Error(`Invalid hex literal near: ${s.slice(i)}`);
                tokens.push({ t: 'num', v: parseInt(m[0], 16) });
                i += 1 + m[0].length;
                continue;
            }
            if (ch === '%') {
                const m = s.slice(i + 1).match(/^[01]+/);
                if (!m) throw new Error(`Invalid binary literal near: ${s.slice(i)}`);
                tokens.push({ t: 'num', v: parseInt(m[0], 2) });
                i += 1 + m[0].length;
                continue;
            }
            if (/[0-9]/.test(ch)) {
                const m = s.slice(i).match(/^\d+/);
                tokens.push({ t: 'num', v: parseInt(m[0], 10) });
                i += m[0].length;
                continue;
            }
            if (/[A-Za-z_.]/.test(ch)) {
                const m = s.slice(i).match(/^[A-Za-z_.][A-Za-z0-9_.]*/);
                tokens.push({ t: 'id', v: m[0] });
                i += m[0].length;
                continue;
            }
            throw new Error(`Unexpected character in expression: '${ch}'`);
        }
        return tokens;
    }

    function evalExpr(expr, symbols, pc) {
        const tokens = tokenizeExpr(expr);
        let idx = 0;

        function peek() { return tokens[idx] || null; }
        function take() { return tokens[idx++] || null; }

        function parsePrimary() {
            const tok = take();
            if (!tok) throw new Error('Unexpected end of expression');
            if (tok.t === 'num') return tok.v | 0;
            if (tok.t === 'PC') return pc | 0;
            if (tok.t === 'id') {
                const key = tok.v;
                if (!Object.prototype.hasOwnProperty.call(symbols, key)) {
                    throw new Error(`Unknown symbol: ${key}`);
                }
                return symbols[key] | 0;
            }
            if (tok.t === '(') {
                const v = parseAddSub();
                const close = take();
                if (!close || close.t !== ')') throw new Error('Missing )');
                return v;
            }
            throw new Error(`Unexpected token: ${tok.t}`);
        }

        function parseUnary() {
            const tok = peek();
            if (tok && (tok.t === '+' || tok.t === '-' || tok.t === '<' || tok.t === '>')) {
                take();
                const v = parseUnary();
                if (tok.t === '+') return v;
                if (tok.t === '-') return -v;
                if (tok.t === '<') return v & 0xFF;
                if (tok.t === '>') return (v >> 8) & 0xFF;
            }
            return parsePrimary();
        }

        function parseAddSub() {
            let v = parseUnary();
            while (true) {
                const tok = peek();
                if (!tok || (tok.t !== '+' && tok.t !== '-')) break;
                take();
                const rhs = parseUnary();
                v = (tok.t === '+') ? (v + rhs) : (v - rhs);
            }
            return v;
        }

        const val = parseAddSub();
        if (idx !== tokens.length) {
            throw new Error('Unexpected tokens at end of expression');
        }
        return val | 0;
    }

    function splitCsvArgs(s) {
        const out = [];
        let cur = '';
        let inStr = false;
        for (let i = 0; i < s.length; i++) {
            const ch = s[i];
            if (ch === '"') {
                inStr = !inStr;
                cur += ch;
                continue;
            }
            if (!inStr && ch === ',') {
                out.push(cur.trim());
                cur = '';
                continue;
            }
            cur += ch;
        }
        if (cur.trim()) out.push(cur.trim());
        return out;
    }

    function detectAddrMode(mnemonic, operandRaw, symbols, pc, pass) {
        const op = (operandRaw || '').trim();
        const upper = mnemonic.toUpperCase();
        if (!op) return { mode: 'imp' };
        if (op.toUpperCase() === 'A') return { mode: 'acc' };
        if (BRANCH_MNEMONICS.has(upper)) return { mode: 'rel', expr: op };
        if (op.startsWith('#')) return { mode: 'imm', expr: op.slice(1).trim() };

        const mIndX = op.match(/^\(\s*(.+)\s*,\s*X\s*\)$/i);
        if (mIndX) return { mode: 'indx', expr: mIndX[1].trim() };
        const mIndY = op.match(/^\(\s*(.+)\s*\)\s*,\s*Y\s*$/i);
        if (mIndY) return { mode: 'indy', expr: mIndY[1].trim() };
        const mInd = op.match(/^\(\s*(.+)\s*\)$/);
        if (mInd) return { mode: 'ind', expr: mInd[1].trim() };

        const mX = op.match(/^(.+)\s*,\s*X\s*$/i);
        if (mX) {
            const expr = mX[1].trim();
            const hasLabel = /[A-Za-z_.]/.test(expr);
            if (pass === 2 && !hasLabel) {
                const v = evalExpr(expr, symbols, pc);
                return (v >= 0 && v <= 0xFF) ? { mode: 'zpx', expr } : { mode: 'absx', expr };
            }
            // Pass 1 or label: default to absolute-indexed
            return { mode: hasLabel ? 'absx' : 'zpx', expr };
        }
        const mY = op.match(/^(.+)\s*,\s*Y\s*$/i);
        if (mY) {
            const expr = mY[1].trim();
            const hasLabel = /[A-Za-z_.]/.test(expr);
            if (pass === 2 && !hasLabel) {
                const v = evalExpr(expr, symbols, pc);
                return (v >= 0 && v <= 0xFF) ? { mode: 'zpy', expr } : { mode: 'absy', expr };
            }
            return { mode: hasLabel ? 'absy' : 'zpy', expr };
        }

        // Plain address
        const hasLabel = /[A-Za-z_.]/.test(op);
        if (pass === 2 && !hasLabel) {
            const v = evalExpr(op, symbols, pc);
            return (v >= 0 && v <= 0xFF) ? { mode: 'zp', expr: op } : { mode: 'abs', expr: op };
        }
        return { mode: hasLabel ? 'abs' : 'zp', expr: op };
    }

    function assemble6502(source, opts) {
        const options = opts || {};
        const forbidOrg = !!options.forbidOrg;
        let pc = (options.origin != null) ? (options.origin | 0) : 0x1000;
        let startPc = pc;
        let originExplicit = false;

        const norm = String(source || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
        const rawLines = norm.split('\n');

        const statements = [];
        const symbols = Object.create(null);
        let outputStarted = false;

        function defineSymbol(name, value) {
            const key = String(name);
            if (Object.prototype.hasOwnProperty.call(symbols, key)) {
                throw new Error(`Duplicate symbol: ${key}`);
            }
            symbols[key] = value | 0;
        }

        function parseLine(raw, lineNo) {
            const noComment = stripAsmComment(raw);
            const trimmed = noComment.trim();
            if (!trimmed) return null;

            // Label at start: foo:
            let rest = trimmed;
            const mLabel = rest.match(/^([A-Za-z_.][A-Za-z0-9_.]*)\s*:\s*(.*)$/);
            if (mLabel) {
                return { kind: 'label', name: mLabel[1], rest: (mLabel[2] || '').trim(), lineNo, raw };
            }

            // Constant: foo = expr
            const mEq = rest.match(/^([A-Za-z_.][A-Za-z0-9_.]*)\s*=\s*(.+)$/);
            if (mEq) {
                return { kind: 'equ', name: mEq[1], expr: mEq[2], lineNo, raw };
            }

            return { kind: 'stmt', text: rest, lineNo, raw };
        }

        // PASS 1: gather symbols and sizes (labels always abs; no zp optimization for label refs)
        for (let i = 0; i < rawLines.length; i++) {
            const rec = parseLine(rawLines[i], i + 1);
            if (!rec) continue;

            try {
                if (rec.kind === 'label') {
                    defineSymbol(rec.name, pc);
                    if (!rec.rest) continue;
                    // treat trailing part as statement
                    rec.kind = 'stmt';
                    rec.text = rec.rest;
                }

                if (rec.kind === 'equ') {
                    const v = evalExpr(rec.expr, symbols, pc);
                    defineSymbol(rec.name, v);
                    continue;
                }

                // ORG forms: "* = expr" / "*=expr"
                const orgMatch = rec.text.match(/^\*\s*=\s*(.+)$/);
                if (orgMatch) {
                    if (forbidOrg) {
                        throw new Error('.org/*= is not supported in dev.html ASM mode');
                    }
                    const v = evalExpr(orgMatch[1], symbols, pc) & 0xFFFF;
                    originExplicit = true;
                    if (!outputStarted) {
                        pc = v;
                        startPc = v;
                        continue;
                    }
                    if (v !== pc) {
                        throw new Error(`.org changed PC from $${pc.toString(16)} to $${v.toString(16)}; gaps are not supported`);
                    }
                    continue;
                }

                // Directives / instructions
                const text = rec.text;
                const m = text.match(/^([.A-Za-z][A-Za-z0-9_.]*)\s*(.*)$/);
                if (!m) throw new Error('ASM parse error');
                const head = m[1];
                const tail = (m[2] || '').trim();
                const upHead = head.toUpperCase();

                // ORG (.org expr)
                if (upHead === '.ORG') {
                    if (forbidOrg) {
                        throw new Error('.org/*= is not supported in dev.html ASM mode');
                    }
                    const v = evalExpr(tail, symbols, pc) & 0xFFFF;
                    originExplicit = true;
                    if (!outputStarted) {
                        pc = v;
                        startPc = v;
                        continue;
                    }
                    if (v !== pc) {
                        throw new Error(`.org changed PC from $${pc.toString(16)} to $${v.toString(16)}; gaps are not supported`);
                    }
                    continue;
                }

                if (upHead === '.BYTE' || upHead === '!BYTE') {
                    const args = splitCsvArgs(tail);
                    let size = 0;
                    for (const a of args) {
                        if (!a) continue;
                        if (/^".*"$/.test(a)) size += parseAsmStringLiteral(a).length;
                        else size += 1;
                    }
                    statements.push({ type: 'data', kind: 'byte', pc, args, lineNo: rec.lineNo, raw: rec.raw, size });
                    pc += size;
                    outputStarted = true;
                    continue;
                }
                if (upHead === '.WORD' || upHead === '!WORD') {
                    const args = splitCsvArgs(tail);
                    const size = args.filter(Boolean).length * 2;
                    statements.push({ type: 'data', kind: 'word', pc, args, lineNo: rec.lineNo, raw: rec.raw, size });
                    pc += size;
                    outputStarted = true;
                    continue;
                }
                if (upHead === '.TEXT' || upHead === '.ASCII' || upHead === '!TEXT') {
                    const arg = tail.trim();
                    if (!/^".*"$/.test(arg)) throw new Error('.text expects a quoted string');
                    const bytes = parseAsmStringLiteral(arg);
                    statements.push({ type: 'data', kind: 'text', pc, bytes, lineNo: rec.lineNo, raw: rec.raw, size: bytes.length });
                    pc += bytes.length;
                    outputStarted = true;
                    continue;
                }

                // Instruction
                const mnemonic = upHead;
                const operandRaw = tail;
                if (!Object.prototype.hasOwnProperty.call(OPCODES, mnemonic)) {
                    throw new Error(`Unknown mnemonic/directive '${head}'`);
                }
                const modeInfo = detectAddrMode(mnemonic, operandRaw, symbols, pc, 1);
                const mode = modeInfo.mode;
                const opcode = OPCODES[mnemonic][mode];
                if (opcode == null) {
                    throw new Error(`Addressing mode not supported for ${mnemonic} (${mode})`);
                }
                const size = (mode === 'imp' || mode === 'acc') ? 1 : (mode === 'imm' || mode === 'zp' || mode === 'zpx' || mode === 'zpy' || mode === 'indx' || mode === 'indy' || mode === 'rel') ? 2 : 3;
                statements.push({ type: 'ins', pc, mnemonic, mode, operand: modeInfo.expr || null, lineNo: rec.lineNo, raw: rec.raw, size });
                pc += size;
                outputStarted = true;
            } catch (e) {
                const msg = String(e && e.message ? e.message : e);
                if (/\bline\s+\d+\b/i.test(msg)) throw e;
                throw new Error(`Line ${rec.lineNo}: ${msg}`);
            }
        }

        const endPc = pc;
        const out = new Uint8Array(Math.max(0, endPc - startPc));

        // PASS 2: encode
        pc = startPc;
        let write = 0;
        for (const st of statements) {
            try {
                if (st.type === 'data') {
                    if (st.pc !== pc) throw new Error('Internal assembler error: PC mismatch (data)');
                    if (st.kind === 'text') {
                        out.set(new Uint8Array(st.bytes), write);
                        write += st.bytes.length;
                        pc += st.bytes.length;
                        continue;
                    }
                    if (st.kind === 'byte') {
                        for (const a of st.args) {
                            if (!a) continue;
                            if (/^".*"$/.test(a)) {
                                const bytes = parseAsmStringLiteral(a);
                                out.set(new Uint8Array(bytes), write);
                                write += bytes.length;
                                pc += bytes.length;
                            } else {
                                const v = evalExpr(a, symbols, pc) & 0xFF;
                                out[write++] = v;
                                pc += 1;
                            }
                        }
                        continue;
                    }
                    if (st.kind === 'word') {
                        for (const a of st.args) {
                            if (!a) continue;
                            const v = evalExpr(a, symbols, pc) & 0xFFFF;
                            out[write++] = v & 0xFF;
                            out[write++] = (v >> 8) & 0xFF;
                            pc += 2;
                        }
                        continue;
                    }
                    throw new Error('Internal assembler error: unknown data kind');
                }
                if (st.type === 'ins') {
                    if (st.pc !== pc) throw new Error('Internal assembler error: PC mismatch (ins)');
                    detectAddrMode(st.mnemonic, st.operand ? (st.mode === 'imm' ? '#' + st.operand : st.operand) : '', symbols, pc, 2);
                    const mode = st.mode; // keep mode chosen in pass1 (stable sizing)
                    const opcode = OPCODES[st.mnemonic][mode];
                    if (opcode == null) throw new Error(`Cannot encode ${st.mnemonic} (${mode})`);
                    out[write++] = opcode & 0xFF;
                    if (mode === 'imp' || mode === 'acc') {
                        pc += 1;
                        continue;
                    }
                    if (mode === 'rel') {
                        const target = evalExpr(st.operand, symbols, pc) & 0xFFFF;
                        const nextPc = (pc + 2) & 0xFFFF;
                        let off = (target - nextPc) | 0;
                        if (off < -128 || off > 127) {
                            throw new Error(`Branch out of range (offset ${off})`);
                        }
                        out[write++] = off & 0xFF;
                        pc += 2;
                        continue;
                    }
                    if (mode === 'imm' || mode === 'zp' || mode === 'zpx' || mode === 'zpy' || mode === 'indx' || mode === 'indy') {
                        const v = evalExpr(st.operand, symbols, pc) & 0xFF;
                        out[write++] = v;
                        pc += 2;
                        continue;
                    }
                    // abs / absx / absy / ind
                    const v = evalExpr(st.operand, symbols, pc) & 0xFFFF;
                    out[write++] = v & 0xFF;
                    out[write++] = (v >> 8) & 0xFF;
                    pc += 3;
                    continue;
                }
            } catch (e) {
                const msg = String(e && e.message ? e.message : e);
                if (/\bline\s+\d+\b/i.test(msg)) throw e;
                throw new Error(`Line ${st.lineNo}: ${msg}`);
            }
        }

        return { origin: startPc & 0xFFFF, originExplicit, bytes: out, symbols };
    }

    function compileAsmPokeLoaderToPrg(origin, bytes) {
        const o = origin & 0xFFFF;
        const n = bytes.length | 0;
        if (n <= 0) throw new Error('ASM produced 0 bytes');

        // Keep DATA lines short-ish.
        const chunkSize = 24;
        const lines = [];
        lines.push(`10 O=${o}:FORI=0TO${n - 1}:READA:POKEO+I,A:NEXT:SYSO`);
        let ln = 20;
        for (let i = 0; i < n; i += chunkSize) {
            const chunk = Array.prototype.slice.call(bytes, i, i + chunkSize);
            lines.push(`${ln} DATA ${chunk.join(',')}`);
            ln += 10;
        }
        return compileBasicV2ToPrg(lines.join('\n'));
    }

    function compileAsmAutoRunToPrg(source) {
        // Build a BASIC stub that does SYS <codeStart>, then append machine code bytes right after it.
        // We iterate because changing the SYS number of digits can change BASIC program length.
        let codeStart = 0x080D; // typical-ish initial guess
        let prgStub = null;
        for (let i = 0; i < 6; i++) {
            const stubSrc = `10 SYS ${codeStart}`;
            prgStub = compileBasicV2ToPrg(stubSrc);
            const nextCodeStart = (LOAD_ADDR + (prgStub.length - 2)) & 0xFFFF;
            if (nextCodeStart === codeStart) break;
            codeStart = nextCodeStart;
        }

        const asm = assemble6502(source, { origin: codeStart, forbidOrg: false });

        // If the user explicitly set origin (e.g. "*=$C000" or ".org $C000"), we can't append code
        // after the BASIC stub without breaking absolute addressing. In that case, build a BASIC
        // loader that POKEs the bytes into the requested address, then SYS there.
        if (asm.originExplicit && asm.origin !== codeStart) {
            const prg = compileAsmPokeLoaderToPrg(asm.origin, asm.bytes);
            return { prg, entry: asm.origin, size: asm.bytes.length, loadedVia: 'poke' };
        }

        const finalPrg = new Uint8Array(prgStub.length + asm.bytes.length);
        finalPrg.set(prgStub, 0);
        finalPrg.set(asm.bytes, prgStub.length);
        return { prg: finalPrg, entry: codeStart, size: asm.bytes.length, loadedVia: 'append' };
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

    // --- ASM syntax highlighting (simple, not a full parser) ---

    const ASM_MNEMONICS = new Set(Object.keys(OPCODES));
    const ASM_DIRECTIVES = new Set(['.BYTE', '.WORD', '.TEXT', '.ASCII', '.ORG', '*=']);

    function highlightAsmLine(line) {
        const raw = String(line || '');
        const noComment = stripAsmComment(raw);
        const comment = raw.slice(noComment.length);

        // Label at start
        let head = noComment;
        let out = '';
        const mLabel = head.match(/^(\s*)([A-Za-z_.][A-Za-z0-9_.]*)\s*:\s*(.*)$/);
        if (mLabel) {
            out += `${escapeHtml(mLabel[1])}<span class="asm-lbl">${escapeHtml(mLabel[2])}</span>:`;
            head = mLabel[3] || '';
        }

        // Tokenize first word (mnemonic/directive)
        const m = head.match(/^(\s*)([.A-Za-z*][A-Za-z0-9_.=]*)\b(.*)$/);
        if (m) {
            const pre = m[1] || '';
            const w = (m[2] || '');
            const rest = m[3] || '';
            const up = w.toUpperCase();
            out += escapeHtml(pre);
            if (ASM_MNEMONICS.has(up)) {
                out += `<span class="asm-op">${escapeHtml(w)}</span>`;
            } else if (ASM_DIRECTIVES.has(up) || up === '!BYTE' || up === '!WORD' || up === '!TEXT') {
                out += `<span class="asm-dir">${escapeHtml(w)}</span>`;
            } else {
                out += escapeHtml(w);
            }

            // Highlight quoted strings + numbers in the rest (small scanner to avoid HTML-escaping issues)
            let i = 0;
            while (i < rest.length) {
                const ch = rest[i];
                if (ch === '"') {
                    // quoted string (allow backslash escapes)
                    let j = i + 1;
                    let esc = false;
                    while (j < rest.length) {
                        const cj = rest[j];
                        if (esc) {
                            esc = false;
                            j++;
                            continue;
                        }
                        if (cj === '\\') { esc = true; j++; continue; }
                        if (cj === '"') { j++; break; }
                        j++;
                    }
                    const s = rest.slice(i, j);
                    out += `<span class="asm-str">${escapeHtml(s)}</span>`;
                    i = j;
                    continue;
                }

                // Hex / binary / decimal numbers
                const tail = rest.slice(i);
                const mHex = tail.match(/^\$[0-9a-fA-F]+/);
                if (mHex) {
                    out += `<span class="asm-num">${escapeHtml(mHex[0])}</span>`;
                    i += mHex[0].length;
                    continue;
                }
                const mBin = tail.match(/^%[01]+/);
                if (mBin) {
                    out += `<span class="asm-num">${escapeHtml(mBin[0])}</span>`;
                    i += mBin[0].length;
                    continue;
                }
                const mDec = tail.match(/^\d+/);
                if (mDec) {
                    out += `<span class="asm-num">${escapeHtml(mDec[0])}</span>`;
                    i += mDec[0].length;
                    continue;
                }

                out += escapeHtml(ch);
                i++;
            }
        } else {
            out += escapeHtml(head);
        }

        if (comment) {
            out += `<span class="asm-com">${escapeHtml(comment)}</span>`;
        }
        return out;
    }

    function renderAsmHighlight(text) {
        const lines = String(text || '')
            .replace(/\r\n/g, '\n')
            .replace(/\r/g, '\n')
            .split('\n');
        return lines.map(highlightAsmLine).join('\n') + '\n';
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
        const runBtn = document.getElementById('run-btn');
        const modeBasicBtn = document.getElementById('mode-basic');
        const modeAsmBtn = document.getElementById('mode-asm');
        const hintEl = document.getElementById('dev-hint');

        const basicEditor = document.getElementById('basic-editor');
        const basicHighlight = document.getElementById('basic-highlight');
        const basicGutter = document.getElementById('basic-gutter');
        const basicErrLine = document.getElementById('basic-error-line');
        const asmEditor = document.getElementById('asm-editor');
        const asmHighlight = document.getElementById('asm-highlight');
        const asmGutter = document.getElementById('asm-gutter');
        const asmErrLine = document.getElementById('asm-error-line');
        if (!runBtn || !modeBasicBtn || !modeAsmBtn || !basicEditor || !basicHighlight || !basicGutter || !basicErrLine || !asmEditor || !asmHighlight || !asmGutter || !asmErrLine) return;

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
            if (document.activeElement === basicEditor || document.activeElement === asmEditor) {
                e.stopImmediatePropagation();
            }
        }
        document.addEventListener('keydown', swallowIfEditing, true);
        document.addEventListener('keypress', swallowIfEditing, true);
        document.addEventListener('keyup', swallowIfEditing, true);

        function getLineCount(text) {
            return String(text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n').length;
        }

        function renderGutter(lineCount) {
            const n = Math.max(1, lineCount | 0);
            let out = '';
            for (let i = 1; i <= n; i++) out += i + '\n';
            return out;
        }

        function getLineHeightPx(editorEl) {
            const lh = parseFloat(window.getComputedStyle(editorEl).lineHeight || '');
            return Number.isFinite(lh) && lh > 0 ? lh : 19.6;
        }

        function setErrorLineMarker(mode, lineNo) {
            const isAsm = mode === 'asm';
            const editor = isAsm ? asmEditor : basicEditor;
            const marker = isAsm ? asmErrLine : basicErrLine;
            if (!marker) return;
            const n = (lineNo | 0);
            if (!n || n < 1) {
                marker.style.display = 'none';
                return;
            }

            const lineHeight = getLineHeightPx(editor);
            const paddingTop = 12; // matches CSS padding on textarea/highlight
            const y = paddingTop + (n - 1) * lineHeight - editor.scrollTop;
            marker.style.top = `calc(var(--editor-inset) + ${Math.max(0, y)}px)`;
            marker.style.display = '';
        }

        function extractLineNumberFromError(err) {
            const msg = String(err && err.message ? err.message : err);
            const m = msg.match(/\bline\s+(\d+)\b/i);
            if (!m) return null;
            const n = parseInt(m[1], 10);
            return Number.isFinite(n) ? n : null;
        }

        function scrollToLine(editorEl, lineNo) {
            const n = (lineNo | 0);
            if (!n || n < 1) return;
            const lh = getLineHeightPx(editorEl);
            const top = (n - 1) * lh;
            const target = Math.max(0, top - editorEl.clientHeight * 0.35);
            editorEl.scrollTop = target;
        }

        let basicLastGutterLines = 0;
        let asmLastGutterLines = 0;
        let basicErrorLine = null;
        let asmErrorLine = null;

        function syncBasic() {
            basicHighlight.innerHTML = renderHighlight(basicEditor.value);
            // Keep scroll positions aligned.
            basicHighlight.scrollTop = basicEditor.scrollTop;
            basicHighlight.scrollLeft = basicEditor.scrollLeft;

            const lc = getLineCount(basicEditor.value);
            if (lc !== basicLastGutterLines) {
                basicGutter.textContent = renderGutter(lc);
                basicLastGutterLines = lc;
            }
            basicGutter.scrollTop = basicEditor.scrollTop;
            setErrorLineMarker('basic', basicErrorLine);
        }

        function syncAsm() {
            asmHighlight.innerHTML = renderAsmHighlight(asmEditor.value);
            asmHighlight.scrollTop = asmEditor.scrollTop;
            asmHighlight.scrollLeft = asmEditor.scrollLeft;

            const lc = getLineCount(asmEditor.value);
            if (lc !== asmLastGutterLines) {
                asmGutter.textContent = renderGutter(lc);
                asmLastGutterLines = lc;
            }
            asmGutter.scrollTop = asmEditor.scrollTop;
            setErrorLineMarker('asm', asmErrorLine);
        }

        basicEditor.addEventListener('input', syncBasic);
        basicEditor.addEventListener('scroll', syncBasic);
        asmEditor.addEventListener('input', syncAsm);
        asmEditor.addEventListener('scroll', syncAsm);

        let activeMode = 'basic';

        function setMode(mode) {
            activeMode = (mode === 'asm') ? 'asm' : 'basic';
            const layers = document.querySelectorAll('.editor-layer');
            for (const el of layers) {
                const m = el.getAttribute('data-mode');
                if (m === activeMode) el.classList.add('is-active');
                else el.classList.remove('is-active');
            }
            if (activeMode === 'basic') {
                modeBasicBtn.classList.add('is-active');
                modeAsmBtn.classList.remove('is-active');
                modeBasicBtn.setAttribute('aria-selected', 'true');
                modeAsmBtn.setAttribute('aria-selected', 'false');
                if (hintEl) hintEl.textContent = 'Type C64 BASIC (with or without line numbers) and click RUN to compile to a tokenized PRG and load it into the emulator.';
                syncBasic();
                basicEditor.focus();
            } else {
                modeAsmBtn.classList.add('is-active');
                modeBasicBtn.classList.remove('is-active');
                modeAsmBtn.setAttribute('aria-selected', 'true');
                modeBasicBtn.setAttribute('aria-selected', 'false');
                if (hintEl) hintEl.textContent = 'Type 6502 ASM and click RUN to assemble to a PRG that auto-runs via a BASIC SYS stub.';
                syncAsm();
                asmEditor.focus();
            }
        }

        modeBasicBtn.addEventListener('click', () => setMode('basic'));
        modeAsmBtn.addEventListener('click', () => setMode('asm'));

        runBtn.addEventListener('click', function() {
            try {
                basicErrorLine = null;
                asmErrorLine = null;
                setErrorLineMarker('basic', null);
                setErrorLineMarker('asm', null);

                let prg;
                let name = 'dev.prg';
                if (activeMode === 'asm') {
                    const res = compileAsmAutoRunToPrg(asmEditor.value);
                    prg = res.prg;
                    name = 'dev-asm.prg';
                    const how = (res.loadedVia === 'poke') ? 'POKE loader' : 'appended';
                    setStatus(`Assembled ${res.size} bytes @ $${res.entry.toString(16).toUpperCase()} (${how}). Loading...`, 'ok');
                } else {
                    prg = compileBasicV2ToPrg(basicEditor.value);
                    setStatus(`Compiled ${prg.length} bytes. Loading...`, 'ok');
                }
                const blob = new Blob([prg], { type: 'application/octet-stream' });
                const url = URL.createObjectURL(blob);

                if (typeof loadProgramFromUrl !== 'function') {
                    throw new Error('Emulator loader is not available yet');
                }

                loadProgramFromUrl(url, name);

                setTimeout(() => URL.revokeObjectURL(url), 5000);
            } catch (e) {
                const lineNo = extractLineNumberFromError(e);
                if (lineNo) {
                    if (activeMode === 'asm') {
                        asmErrorLine = lineNo;
                        scrollToLine(asmEditor, lineNo);
                        syncAsm();
                    } else {
                        basicErrorLine = lineNo;
                        scrollToLine(basicEditor, lineNo);
                        syncBasic();
                    }
                }
                setStatus(String(e && e.message ? e.message : e), 'err');
                // eslint-disable-next-line no-console
                console.error(e);
            }
        });

        // Load initial content (prefer src/main.bas if served)
        fetch('src/main.bas')
            .then((r) => (r.ok ? r.text() : Promise.reject(new Error('src/main.bas not found'))))
            .then((t) => {
                basicEditor.value = t;
                syncBasic();
            })
            .catch(() => {
                basicEditor.value = [
                    '10 PRINT "HELLO FROM DEV.HTML"',
                    '20 FOR I=1 TO 200:NEXT I',
                    '30 GOTO 10'
                ].join('\n');
                syncBasic();
            });

        // Load ASM template (prefer src/main.asm if served)
        fetch('src/main.asm')
            .then((r) => (r.ok ? r.text() : Promise.reject(new Error('src/main.asm not found'))))
            .then((t) => {
                asmEditor.value = t;
                syncAsm();
            })
            .catch(() => {
                asmEditor.value = [
                    '; 6502 ASM demo (auto-runs via BASIC SYS stub)',
                    '; Notes:',
                    '; - dev.html ASM mode assembles a single contiguous block (no .org/*=).',
                    '; - Use $D020/$D021 to change border/background.',
                    '',
                    '        SEI',
                    '        LDA #$06',
                    '        STA $D020',
                    '        LDA #$00',
                    '        STA $D021',
                    '',
                    'loop:   INC $D020',
                    '        JMP loop'
                ].join('\n');
                syncAsm();
            });

        // Default mode
        setMode('basic');
    }

    // Wait for DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootEditor);
    } else {
        bootEditor();
    }
})();

