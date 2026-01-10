; ARKAN-BREAKOUT URUGUAYO - ML ACME COMPLETO (sin truncamientos)
; Compila: acme -f cbm -o ../programs/main.prg main.asm

!cpu 6510

SCREEN    = $0400
COLORRAM  = $D800
VIC       = $D000
SID       = $D400
CIA1      = $DC00
SPRITEN   = $D015
SPRITEC0  = $D027
SPRITEC1  = $D028

; Variables zero page (using safer addresses, avoiding BASIC/KERNAL workspace)
; Safe ranges for ML programs called from BASIC:
; $02-$03: Can be used (some risk)
; $A3-$BE: Relatively safe (avoid $A0-$A2 jiffy timer)
; $C0-$CF: KERNAL workspace, often unused
; $FB-$FE: Generally free (avoid $FF = stack)
; We'll use $C0+ range which is safer
PADDLE_X  = $C0
BALL_X    = $C1
BALL_Y    = $C2
BALL_DX   = $C3
BALL_DY   = $C4
PARTIDOS  = $C5
BAJADAS   = $C6
LEVEL     = $C7
NOTE_IDX  = $C8     ; Índice para nota del himno
HIT_TEMP  = $C9
FRAME_TIMER = $CA   ; Contador de frames para timing
NOTE_TIMER = $CB    ; Contador de frames para duración de nota actual
BLOCKS    = $CC     ; $CC to $F3 = 40 bytes (1= bloque vivo)

* = $0801
        !byte $0C,$08,$0A,$00,$9E,$38,$31,$39,$32,$00,$00,$00  ; SYS 8192

* = $2000

start:
        ; Initialize stack pointer (safety check)
        ldx #$FF
        txs                     ; Set stack to $01FF
        
        ; Minimal initialization first - just clear screen and display text
        ; This will help us see if the basic structure works
        jsr init_screen
        jsr screen_text
        
        ; Add a simple marker to show we got here
        ; Convert PETSCII to screen code: 'A' (65) -> screen code 1
        lda #65                 ; PETSCII 'A'
        sec
        sbc #64                 ; Convert to screen code
        sta SCREEN+40*0+0       ; Top-left corner
        lda #1                  ; White color
        sta COLORRAM+40*0+0
        
        ; Now initialize other subsystems
        jsr init_sid
        jsr init_sprites
        jsr init_blocks
        jsr init_game
        
        ; Initialize IRQ last (now that we know main loop works)
        jsr init_irq
        
        ; Add another marker to show initialization completed
        ; Convert PETSCII to screen code: 'B' (66) -> screen code 2
        lda #66                 ; PETSCII 'B'
        sec
        sbc #64                 ; Convert to screen code
        sta SCREEN+40*0+1       ; Second position
        lda #1                  ; White color
        sta COLORRAM+40*0+1
        
        ; Add a counter marker (will increment in main loop)
        ; '0' is already a screen code (48)
        lda #48                 ; Screen code for '0'
        sta SCREEN+40*0+2       ; Third position
        lda #1                  ; White color
        sta COLORRAM+40*0+2
        
        ; Should never return from here - stay in main loop forever
        ; If we get back to BASIC, something crashed

main_loop:
        ; The IRQ handler does all the game updates, so we just wait here
        ; Keep a counter to show we're still in the main loop (for debugging)
        inc SCREEN+40*0+2       ; Increment third character on screen
        lda SCREEN+40*0+2
        cmp #58                 ; Wrap around after '9' (screen code 58)
        bcc .no_wrap
        lda #48                 ; Reset to '0' (screen code 48)
        sta SCREEN+40*0+2
.no_wrap:
        
        ; Read keys (can be done in main loop or IRQ)
        jsr read_keys
        
        ; Simple delay to prevent tight loop (reduces CPU usage)
        ; IRQ will fire ~50-60 times per second for game updates
        ldx #10                 ; Shorter delay since IRQ handles timing
delay_loop:
        nop
        nop
        dex
        bne delay_loop
        
        ; Make sure we stay in this loop forever
        ; IRQ handler will interrupt and update game logic
        jmp main_loop

init_screen:
        ; Clear screen first (1000 bytes = 40*25 characters)
        ; IMPORTANT: Screen memory is $0400-$07E7 (1000 bytes)
        ; Sprite pointers are at $07F8-$07FF - DON'T OVERWRITE THEM!
        ; So we clear $0400-$07E7, which is 1000 bytes
        ldx #0
        lda #32                 ; Space character
clear_screen:
        sta SCREEN,x            ; $0400-$04FF
        sta SCREEN+256,x        ; $0500-$05FF
        sta SCREEN+512,x        ; $0600-$06FF
        sta SCREEN+768,x        ; $0700-$07FF (but we'll stop before $07F8)
        inx
        cpx #232                ; Clear only 232 bytes in last block (stop at $07E8)
        bne clear_screen
        ; Now clear the remaining bytes from $07E8 to $07E7... wait, that's wrong
        ; Actually, $0400 + 1000 = $0400 + $03E8 = $07E8, so we need to clear from $07E8 to $07FF?
        ; No, screen is 40*25 = 1000 bytes = $0400 to $0400+1000-1 = $0400 to $07E7
        ; So we've cleared $0400 to $07E7, that's correct!
        
        ; Set screen colors to white on black (1000 bytes, same range)
        ldx #0
        lda #1                  ; White
clear_colors:
        sta COLORRAM,x          ; $D800-$D8FF
        sta COLORRAM+256,x      ; $D900-$D9FF
        sta COLORRAM+512,x      ; $DA00-$DAFF
        sta COLORRAM+768,x      ; $DB00-$DBFF (but we'll stop before end)
        inx
        cpx #232                ; Clear only 232 bytes in last block
        bne clear_colors
        
        ; Set border and background colors
        lda #0                  ; Black border
        sta $D020
        lda #0                  ; Black background
        sta $D021
        
        ; Set VIC-II registers
        lda #$1B                ; Normal screen, 24 rows, 40 columns
        sta $D011
        lda #$10                ; Multicolor charset disabled initially
        sta $D016
        lda #0
        sta $D022               ; Multicolor 1
        lda #2
        sta $D023               ; Multicolor 2
        lda #5
        sta $D024               ; Background color 3
        
        rts

screen_text:
        ; Clear top line and display game title
        ldx #0
text_loop:
        lda msg_text,x
        beq text_end
        sec
        sbc #64                ; Convert to screen code (assuming PETSCII input)
        sta SCREEN+40*1+6,x
        lda #1                  ; White color
        sta COLORRAM+40*1+6,x
        inx
        cpx #30
        bne text_loop
text_end:
        ; Add score labels on screen to make it more visible
        lda #19                 ; 'S' in screen code
        sta SCREEN+40*0+5
        lda #3                  ; 'C' in screen code
        sta SCREEN+40*0+6
        lda #15                 ; 'O' in screen code
        sta SCREEN+40*0+7
        lda #18                 ; 'R' in screen code
        sta SCREEN+40*0+8
        lda #5                  ; 'E' in screen code
        sta SCREEN+40*0+9
        lda #58                 ; ':' in screen code
        sta SCREEN+40*0+10
        
        rts

msg_text:
        !scr "GUERRA DE SENALES BREAKOUT ML!"
        !byte 0

init_sprites:
        ; Ensure VIC can see our sprite data (bank 0: $0000-$3FFF)
        ; $DD00 bits 0-1 control VIC bank: 11 = bank 0, 10 = bank 1, 01 = bank 2, 00 = bank 3
        ; We want bank 0 for $3000 to be visible, so bits 0-1 should be 11
        ; Default is usually bank 0, but let's set it explicitly
        lda $DD00
        and #%11111100          ; Clear bits 0-1 first
        ora #%00000011          ; Set bits 0-1 to 11 (bank 0)
        sta $DD00
        
        ; Clear sprite X MSB register (high bit of X position)
        lda #0
        sta $D010
        
        ; Sprite pointers: pointer_value * 64 = sprite data address (relative to VIC bank)
        ; With VIC bank 0 (base $0000), sprite pointer value * 64 = absolute address
        ; Our sprite data is at $3000, so: $3000 / 64 = 12288 / 64 = 192 = $C0
        ; Ball sprite at $3040: $3040 / 64 = 12352 / 64 = 193 = $C1
        ; Sprite pointers are at $07F8-$07FF (last 8 bytes of screen memory area)
        lda #$C0                ; Paddle sprite at $3000 ($C0 * 64 = $3000)
        sta $07F8               ; Sprite 0 pointer (at $07F8)
        lda #$C1                ; Ball sprite at $3040 ($C1 * 64 = $3040)  
        sta $07F9               ; Sprite 1 pointer (at $07F9)
        
        ; Enable sprites 0 and 1 only
        lda #%00000011
        sta SPRITEN
        
        ; Set sprite colors
        lda #14                 ; Light blue for paddle
        sta SPRITEC0
        lda #12                 ; Medium grey for ball
        sta SPRITEC1
        
        rts

init_sid:
        lda #0
        ldx #24
clear_loop:
        sta SID,x
        dex
        bpl clear_loop
        lda #15
        sta SID+24          ; Volume
        lda #0
        sta NOTE_IDX
        sta FRAME_TIMER
        sta NOTE_TIMER
        rts

init_blocks:
        ldx #0
        lda #1
block_init:
        sta BLOCKS,x
        inx
        cpx #40
        bne block_init
        jsr draw_blocks
        rts

init_game:
        ; Initialize paddle position
        lda #120
        sta PADDLE_X
        
        ; Initialize ball position and velocity (signed bytes)
        lda #120
        sta BALL_X
        lda #100
        sta BALL_Y
        lda #2                  ; Move right 2 pixels/frame
        sta BALL_DX
        lda #$FE                ; -2 (move up 2 pixels/frame)
        sta BALL_DY
        
        ; Initialize scores
        lda #0
        sta PARTIDOS
        sta BAJADAS
        sta LEVEL
        
        ; Set initial sprite positions
        jsr move_paddle
        jsr move_ball
        rts

read_keys:
        ; Read port B of CIA1 (joystick port 2)
        ; Bit 4 = Left, Bit 5 = Right
        lda CIA1
        and #%00010000         ; Check left
        beq .izquierda
        lda CIA1
        and #%00100000         ; Check right
        beq .derecha
        rts

.izquierda:
        dec PADDLE_X
        lda PADDLE_X
        cmp #24
        bcs .fin_key
        lda #24
        sta PADDLE_X
        jmp .fin_key

.derecha:
        inc PADDLE_X
        lda PADDLE_X
        cmp #240
        bcc .fin_key
        lda #240
        sta PADDLE_X

.fin_key:
        rts

move_paddle:
        ; Set paddle sprite X position (sprite 0)
        lda PADDLE_X
        sta VIC+0               ; Sprite 0 X low byte ($D000)
        
        ; Handle sprite X MSB (bit 9) if needed
        ; Since PADDLE_X is limited to 24-240 (8-bit range), MSB will never be needed
        ; Just clear it to be safe
        lda $D010
        and #%11111110          ; Clear bit 0 for sprite 0 MSB (keep it in 0-255 range)
        sta $D010
        
.set_y:
        ; Set paddle sprite Y position (sprite 0)
        lda #220                ; Paddle Y position (bottom of screen)
        sta VIC+1               ; Sprite 0 Y position ($D001)
        rts

move_ball:
        ; Move ball X (handle signed addition)
        lda BALL_X
        clc
        adc BALL_DX
        sta BALL_X
        sta VIC+2               ; Sprite 1 X position (low byte)
        
        ; Handle sprite X MSB (bit 9) if needed
        ; Since ball collision checks keep it in range, MSB will never be needed
        ; Just clear it to be safe
        lda $D010
        and #%11111101          ; Clear bit 1 for sprite 1 MSB (keep it in 0-255 range)
        sta $D010
        
.move_y:
        ; Move ball Y (handle signed addition)  
        lda BALL_Y
        clc
        adc BALL_DY
        sta BALL_Y
        sta VIC+3               ; Sprite 1 Y position
        rts

check_collisions:
        jsr coll_walls
        jsr coll_paddle
        jsr coll_blocks
        rts

coll_walls:
        ; Check left wall
        lda BALL_X
        cmp #24                 ; Left boundary (allowing sprite width)
        bcs .no_left
        ; Reverse X direction (negate signed byte)
        lda BALL_DX
        eor #$FF
        clc
        adc #1
        sta BALL_DX
        jmp .check_y
.no_left:
        ; Check right wall
        cmp #240                ; Right boundary
        bcc .check_y
        ; Reverse X direction
        lda BALL_DX
        eor #$FF
        clc
        adc #1
        sta BALL_DX
        jmp .check_y
        
.check_y:
        ; Check top wall
        lda BALL_Y
        cmp #50                 ; Top boundary (allowing sprite height)
        bcs .no_top
        ; Reverse Y direction
        lda BALL_DY
        eor #$FF
        clc
        adc #1
        sta BALL_DY
        jmp .check_bottom
.no_top:
        ; Check bottom wall (ball lost)
        cmp #220                ; Bottom boundary
        bcc .no_bot
        inc BAJADAS
        jsr reset_ball
        jsr sid_hit_sound
        jmp .done
.no_bot:
.check_bottom:
.done:
        rts

coll_paddle:
        ; Check if ball is near paddle Y position
        lda BALL_Y
        cmp #200                ; Paddle Y position
        bcc .no_hit
        cmp #220                ; Below paddle?
        bcs .no_hit
        
        ; Check X collision with paddle
        lda BALL_X
        sec
        sbc PADDLE_X
        bcc .no_hit             ; Ball left of paddle
        cmp #48                 ; Paddle width (3 bytes * 8 pixels + some margin)
        bcs .no_hit             ; Ball right of paddle
        
        ; Hit! Reverse Y direction (make it negative to go up)
        lda BALL_DY
        eor #$FF
        clc
        adc #1
        sta BALL_DY
        inc PARTIDOS
        jsr sid_hit_sound
.no_hit:
        rts

coll_blocks:
        ; Check if ball is in block area (top of screen)
        lda BALL_Y
        cmp #50                 ; Top of block area
        bcc .no_hit_block
        cmp #100                ; Bottom of block area
        bcs .no_hit_block
        
        ; Calculate which block (blocks are 8 pixels wide)
        lda BALL_X
        sec
        sbc #24                 ; Left margin
        bcc .no_hit_block
        lsr                     ; Divide by 8 (3 shifts)
        lsr
        lsr
        cmp #40                 ; Max 40 blocks
        bcs .no_hit_block
        tax
        
        ; Check if block exists
        lda BLOCKS,x
        beq .no_hit_block
        
        ; Remove block
        lda #0
        sta BLOCKS,x
        jsr draw_blocks         ; Redraw blocks
        
        ; Update score
        lda PARTIDOS
        clc
        adc #10
        sta PARTIDOS
        
        ; Reverse Y direction
        lda BALL_DY
        eor #$FF
        clc
        adc #1
        sta BALL_DY
        
        jsr sid_hit_sound
.no_hit_block:
        rts

reset_ball:
        lda #120
        sta BALL_X
        sta VIC+2
        lda #100
        sta BALL_Y
        sta VIC+3
        lda #2
        sta BALL_DX
        lda #$FE
        sta BALL_DY
        rts

update_scores:
        ; Display score (PARTIDOS) at position 40*0+12
        lda PARTIDOS
        clc
        adc #48                ; Convert to screen code ('0' = 48)
        sta SCREEN+40*0+12
        ; Display misses (BAJADAS) at position 40*0+24
        lda BAJADAS
        clc
        adc #48                ; Convert to screen code
        sta SCREEN+40*0+24
        rts

draw_blocks:
        ldx #0
draw_lp:
        lda BLOCKS,x
        beq .empty
        lda #160
        sta SCREEN+240,x
        lda #1 + LEVEL
        and #15
        sta COLORRAM+240,x
        jmp .next
.empty:
        lda #32
        sta SCREEN+240,x
        lda #0
        sta COLORRAM+240,x
.next:
        inx
        cpx #40
        bne draw_lp
        rts

sid_hit_sound:
        lda #16
        sta SID+12
        lda #240
        sta SID+13
        lda #15
        sta SID+14
        lda #10
        sta HIT_TEMP
.delay:
        dec HIT_TEMP
        bne .delay
        lda #0
        sta SID+12
        rts

play_himno_frame:
        ; Check if current note is still playing
        lda NOTE_TIMER
        beq .advance_note
        dec NOTE_TIMER
        rts
        
.advance_note:
        ; Release gate from previous note first
        lda SID+4
        and #%11111110          ; Clear gate bit
        sta SID+4
        
        ; Small delay to let note release
        ldx #2
.release_delay:
        dex
        bne .release_delay
        
        ; Get next note - check bounds first
        ldx NOTE_IDX
        cpx #9                  ; Max index (array has 9 bytes, last is 0 terminator)
        bcs .reset_himno        ; If >= 9, reset
        lda himno_low,x
        beq .reset_himno        ; If 0, end of melody, reset
        
        ; Set frequency
        sta SID+0
        lda himno_high,x
        sta SID+1
        
        ; Set ADSR envelope
        lda #$00                ; Attack = 0 (fast)
        sta SID+5
        lda #$F0                ; Decay/Sustain = F0
        sta SID+6
        
        ; Start note with triangle waveform + gate
        lda #17                 ; %00010001 = Triangle + gate on
        sta SID+4
        
        ; Set note duration (frames to hold this note)
        lda #60                 ; ~1 second at 50Hz PAL / 60Hz NTSC
        sta NOTE_TIMER
        
        inc NOTE_IDX
        rts
        
.reset_himno:
        ; Release gate before resetting
        lda SID+4
        and #%11111110
        sta SID+4
        lda #0
        sta NOTE_IDX
        rts

init_irq:
        sei                     ; Disable interrupts
        
        ; Disable CIA timer interrupts (prevents conflicts)
        lda #$7f
        sta $dc0d               ; CIA1 ICR - disable all CIA1 interrupts
        sta $dd0d               ; CIA2 ICR - disable all CIA2 interrupts
        
        ; Clear pending interrupts by reading ICR (acknowledges any pending)
        lda $dc0d
        lda $dd0d
        
        ; Set up IRQ vector to point to our handler
        lda #<irq_handler
        sta $0314               ; IRQ vector low byte
        lda #>irq_handler
        sta $0315               ; IRQ vector high byte
        
        ; Clear any pending raster interrupt first
        lda #$01
        sta $d019               ; Clear raster interrupt flag (write 1 to clear)
        
        ; Set raster line for interrupt (line 200, near bottom of visible area)
        ; For PAL: 312 lines total (0-311), for NTSC: 262 lines (0-261)
        ; Use line 200 which works for both (within first 256 lines)
        lda $d011
        and #$7f                ; Clear bit 7 (raster < 256, use $d012 as low byte)
        sta $d011               ; Store back with bit 7 clear
        lda #200                ; Raster line 200 (0-255 range)
        sta $d012               ; Set raster line low byte
        
        ; Enable raster interrupts only (bit 0 = raster IRQ)
        lda #$01
        sta $d01a               ; Enable raster interrupt
        
        ; Ensure interrupts are enabled
        cli                     ; Enable interrupts
        rts

irq_handler:
        ; Save registers (standard IRQ entry)
        pha
        txa
        pha
        tya
        pha
        
        ; Check if this is a raster interrupt (bit 0 of $d019)
        lda $d019
        and #$01
        beq .not_raster         ; Not a raster interrupt, skip game updates
        
        ; Acknowledge raster IRQ (clear bit 0 by writing 1)
        lda #$01
        sta $d019
        
        ; Visual indicator: show IRQ is firing (put 'I' at position 3)
        lda #9                  ; Screen code for 'I'
        sta SCREEN+40*0+3
        lda #1                  ; White color
        sta COLORRAM+40*0+3
        
        ; Update game logic once per frame
        ; Start with safe routines first
        jsr move_paddle         ; Actualiza paddle
        jsr move_ball           ; Actualiza pelota
        jsr check_collisions    ; Chequea colisiones
        jsr update_scores       ; Actualiza puntuación
        
        ; Update music (this might be causing issues - enable carefully)
        jsr play_himno_frame    ; Actualiza música (con timing correcto)
        
        ; Update system clock (jiffy timer at $a0-$a2) to keep BASIC/KERNAL happy
        ; This ensures BASIC's time continues running
        inc $a2                 ; Update jiffy LSB
        bne .clock_done
        inc $a1                 ; Update jiffy middle
        bne .clock_done
        inc $a0                 ; Update jiffy MSB
.clock_done:

.not_raster:
        ; Restore registers (must be in reverse order of save)
        pla
        tay
        pla
        tax
        pla
        
        ; Return from interrupt
        ; This will restore PC and flags from the stack
        rti

; Notas aproximadas del himno (Bb major: primera frase)
himno_low:
        !byte $AC, $15, $7D, $E8, $5C, $D3, $52, $AC, $00
himno_high:
        !byte $04, $05, $05, $05, $06, $06, $07, $07, $00

; Sprites
* = $3000
paddle_data:
        !byte $3C,$7E,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$3C
        !fill 32,0

* = $3040
ball_data:
        ; Ball sprite: 21 rows × 3 bytes = 63 bytes total
        !byte $00,$00,$00    ; Row 1: empty
        !byte $00,$00,$00    ; Row 2: empty
        !byte $00,$3C,$00    ; Row 3: center
        !byte $00,$7E,$00    ; Row 4
        !byte $00,$FF,$00    ; Row 5
        !byte $01,$FF,$80    ; Row 6
        !byte $03,$FF,$C0    ; Row 7
        !byte $07,$FF,$E0    ; Row 8
        !byte $0F,$FF,$F0    ; Row 9
        !byte $0F,$FF,$F0    ; Row 10 (center)
        !byte $07,$FF,$E0    ; Row 11
        !byte $03,$FF,$C0    ; Row 12
        !byte $01,$FF,$80    ; Row 13
        !byte $00,$FF,$00    ; Row 14
        !byte $00,$7E,$00    ; Row 15
        !byte $00,$3C,$00    ; Row 16
        !byte $00,$00,$00    ; Row 17: empty
        !byte $00,$00,$00    ; Row 18: empty
        !byte $00,$00,$00    ; Row 19: empty
        !byte $00,$00,$00    ; Row 20: empty
        !byte $00,$00,$00    ; Row 21: empty
