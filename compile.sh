#!/bin/bash
# C64 BASIC to PRG Compiler
# Uses petcat from VICE emulator suite

set -e

SRC_DIR="src"
OUTPUT_DIR="programs"
SCRIPT_NAME="main.bas"
OUTPUT_NAME="main.prg"

echo "🔧 Compiling C64 BASIC program..."

# Check if petcat is available
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

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Check if source file exists
if [ ! -f "$SRC_DIR/$SCRIPT_NAME" ]; then
    echo "❌ Error: Source file $SRC_DIR/$SCRIPT_NAME not found!"
    exit 1
fi

# Convert line endings to Unix format (LF) if needed
# This ensures petcat can read the file correctly
if [[ "$OSTYPE" == "darwin"* ]] || [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Ensure file has Unix line endings
    sed -i.bak 's/\r$//' "$SRC_DIR/$SCRIPT_NAME" 2>/dev/null || true
    rm -f "$SRC_DIR/$SCRIPT_NAME.bak" 2>/dev/null || true
fi

# Compile BASIC to PRG
# -w2: write as C64 BASIC 2.0 format (tokenized)
# -h: write header (load address)
# -o: output file
# --: separator between options and input file (required by petcat)
echo "📝 Converting $SRC_DIR/$SCRIPT_NAME to $OUTPUT_DIR/$OUTPUT_NAME..."
petcat -w2 -h -o "$OUTPUT_DIR/$OUTPUT_NAME" -- "$SRC_DIR/$SCRIPT_NAME"

if [ $? -ne 0 ]; then
    echo "❌ Compilation failed!"
    exit 1
fi

# Verify the output file
if [ -f "$OUTPUT_DIR/$OUTPUT_NAME" ]; then
    echo "📊 PRG file info:"
    hexdump -C "$OUTPUT_DIR/$OUTPUT_NAME" | head -5
    echo ""
    
    # Check load address (little-endian: first byte is low, second is high)
    BYTE1=$(hexdump -n 1 -e '1/1 "%02x"' "$OUTPUT_DIR/$OUTPUT_NAME")
    BYTE2=$(hexdump -n 2 -e '1/1 "%02x" "\n"' "$OUTPUT_DIR/$OUTPUT_NAME" | tail -1)
    LOAD_ADDR="${BYTE2}${BYTE1}"
    if [ "$LOAD_ADDR" = "0801" ]; then
        echo "✅ Load address is correct: \$0801"
    else
        echo "⚠️  Warning: Load address is \$$LOAD_ADDR (expected 0801)"
    fi
    
    echo "✅ Successfully compiled $OUTPUT_DIR/$OUTPUT_NAME"
    ls -lh "$OUTPUT_DIR/$OUTPUT_NAME"
else
    echo "❌ Error: PRG file was not created!"
    exit 1
fi

