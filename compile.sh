#!/bin/bash
# C64 source to PRG compiler
# - BASIC (*.bas): petcat (VICE)
# - ASM (*.asm):  acme

set -e

SRC_DIR="src"
OUTPUT_DIR="programs"
echo "🔧 Compiling C64 sources in ./${SRC_DIR} -> ./${OUTPUT_DIR} ..."

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

shopt -s nullglob

bas_files=("$SRC_DIR"/*.bas)
asm_files=("$SRC_DIR"/*.asm)

if [ ${#bas_files[@]} -eq 0 ] && [ ${#asm_files[@]} -eq 0 ]; then
    echo "❌ Error: No .bas or .asm files found in ./${SRC_DIR}/"
    exit 1
fi

# Install needed tools only when required by source files present.
if [ ${#bas_files[@]} -gt 0 ]; then
    if ! command -v petcat &> /dev/null; then
        echo "❌ Error: petcat not found. Installing VICE..."
        if [[ "$OSTYPE" == "linux-gnu"* ]]; then
            sudo apt-get update
            sudo apt-get install -y vice
        elif [[ "$OSTYPE" == "darwin"* ]]; then
            if command -v brew &> /dev/null; then
                brew install vice
            else
                echo "❌ Error: Homebrew not found. Please install VICE manually."
                exit 1
            fi
        else
            echo "❌ Error: Unsupported OS. Please install VICE manually."
            exit 1
        fi
    fi
fi

if [ ${#asm_files[@]} -gt 0 ]; then
    if ! command -v acme &> /dev/null; then
        echo "❌ Error: acme not found. Installing acme..."
        if [[ "$OSTYPE" == "linux-gnu"* ]]; then
            sudo apt-get update
            sudo apt-get install -y acme
        elif [[ "$OSTYPE" == "darwin"* ]]; then
            if command -v brew &> /dev/null; then
                brew install acme
            else
                echo "❌ Error: Homebrew not found. Please install acme manually."
                exit 1
            fi
        else
            echo "❌ Error: Unsupported OS. Please install acme manually."
            exit 1
        fi
    fi
fi

normalize_line_endings() {
    local file="$1"
    # Ensure file has Unix line endings (petcat/acme prefer LF)
    if [[ "$OSTYPE" == "darwin"* ]] || [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sed -i.bak 's/\r$//' "$file" 2>/dev/null || true
        rm -f "${file}.bak" 2>/dev/null || true
    fi
}

compile_basic() {
    local in="$1"
    local base
    base="$(basename "$in" .bas)"
    local out="$OUTPUT_DIR/${base}.prg"
    echo "📝 BASIC: $in -> $out"
    normalize_line_endings "$in"
    # -w2: C64 BASIC 2.0 tokenized
    # -h:  write PRG header (load address)
    petcat -w2 -h -o "$out" -- "$in"
}

compile_asm() {
    local in="$1"
    local base
    base="$(basename "$in" .asm)"
    local out="$OUTPUT_DIR/${base}.prg"
    echo "📝 ASM:   $in -> $out"
    normalize_line_endings "$in"
    # -f cbm: write C64 PRG (load address header)
    acme -f cbm -o "$out" "$in"
}

for f in "${bas_files[@]}"; do
    compile_basic "$f"
done

for f in "${asm_files[@]}"; do
    compile_asm "$f"
done

echo ""
echo "✅ Compilation finished. Outputs:"
ls -lh "$OUTPUT_DIR"/*.prg || true

