; *** ARKAN-BREAKOUT URUGUAYO - ML ACME COMPLETO 2026 ***
; POR GROK & LUAR ROJI
; acme -f cbm -o arkanoid_uy.prg este.asm
; LOAD "ARKANOID_UY.PRG",8,1

!cpu 6510
!to "arkanoid_uy.prg",cbm

SCREEN    = $0400
COLORRAM  = $D800
VIC       = $D000
SID       = $D400
CIA1      = $DC00
SPRITEN   = $D015
SPRITEC0  = $D027
SPRITEC1  = $D028

; Zero page
PADDLE_X  = $80
BALL_X    = $81
BALL_Y    = $82
BALL_DX   = $83
BALL_DY   = $84
PARTIDOS  = $85
BAJADAS   = $86
LEVEL     = $87
HIT_TEMP  = $88

* = $0801
        !byte $0C,$08,$0A,$00,$9E,$32,$30,$36,$31,$00,$00,$00  ; SYS 8192

* = $2000

start:
        jsr init_screen
        jsr screen_text
        jsr init_sprites
        jsr init_sid
        jsr init_blocks
        jsr init_game

main_loop:
        jsr read_keys
        jsr move_paddle
        jsr move_ball
        jsr check_collisions
        jsr update_scores
        jsr play_himno_frame
        jmp main_loop

init_screen:
        lda #0
        sta $D020
        sta $D021
        lda #$1B
        sta $D011
        lda #$10           ; Multicolor charset ON (Arkanoid look)
        sta $D016
        lda #0
        sta $D022          ; Bg multicolor 1 negro
        lda #2             ; Rojo
        sta $D023
        lda #5             ; Verde
        sta $D024
        rts

screen_text:
        ldx #0
text_loop:
        lda msg_text,x
        beq text_end
        sec
        sbc #64
        sta SCREEN+40*1+6,x   ; fila 1
        lda #1
        sta COLORRAM+40*1+6,x
        inx
        cpx #30
        bne text_loop
text_end:
        rts

msg_text:
        !text "GUERRA DE SENALES - BREAKOUT URUGUAYO"
        !byte 0

init_sprites:
        lda #$C0
        sta $07F8
        lda #$C1
        sta $07F9
        lda #%00000011
        sta SPRITEN
        lda #14
        sta SPRITEC0
        lda #12
        sta SPRITEC1
        rts

init_sid:
        lda #0
        ldx #24
clear_sid:
        sta SID,x
        dex
        bpl clear_sid
        lda #15
        sta SID+24
        rts

init_blocks:
        ldx #0
        lda #1
block_loop:
        sta BLOCKS,x
        inx
        cpx #40
        bne block_loop
        jsr draw_blocks
        rts

init_game:
        lda #120
        sta PADDLE_X
        lda #220
        sta VIC+1
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
        lda #0
        sta PARTIDOS
        sta BAJADAS
        sta LEVEL
        rts

read_keys:
        lda CIA1
        and #%00010000
        beq .izq
        lda CIA1
        and #%00100000
        beq .der
        rts
.izq:
        dec PADDLE_X
        lda PADDLE_X
        cmp #24
        bcs .fin_key
        lda #24
        sta PADDLE_X
        jmp .fin_key
.der:
        inc PADDLE_X
        lda PADDLE_X
        cmp #240
        bcc .fin_key
        lda #240
        sta PADDLE_X
.fin_key:
        rts

move_paddle:
        lda PADDLE_X
        sta VIC+0
        rts

move_ball:
        lda BALL_X
        clc
        adc BALL_DX
        sta BALL_X
        sta VIC+2
        lda BALL_Y
        clc
        adc BALL_DY
        sta BALL_Y
        sta VIC+3
        rts

check_collisions:
        jsr coll_walls
        jsr coll_paddle
        jsr coll_blocks
        rts

coll_walls:
        lda BALL_X
        cmp #32
        bcs .no_left
        lda #1
        eor BALL_DX
        sta BALL_DX
.no_left:
        cmp #240
        bcc .no_right
        lda #1
        eor BALL_DX
        sta BALL_DX
.no_right:
        lda BALL_Y
        cmp #56
        bcs .no_top
        lda #1
        eor BALL_DY
        sta BALL_DY
.no_top:
        cmp #200
        bcc .no_bot
        inc BAJADAS
        jsr reset_ball
        jsr sid_hit_sound
.no_bot:
        rts

coll_paddle:
        lda BALL_Y
        cmp #200
        bcc .no_paddle
        lda BALL_X
        cmp PADDLE_X
        bcc .no_paddle
        lda PADDLE_X
        clc
        adc #40
        cmp BALL_X
        bcc .no_paddle
        lda #1
        eor BALL_DY
        sta BALL_DY
        inc PARTIDOS
        jsr sid_hit_sound
.no_paddle:
        rts

coll_blocks:
        lda BALL_Y
        sec
        sbc #48            ; Rows 6-10 (48-88)
        cmp #40
        bcs .no_block_hit
        lsr
        lsr
        lsr                ; Row index
        tay
        lda BALL_X
        lsr
        lsr
        lsr                ; Col index
        tax
        lda BLOCKS,x
        beq .no_block_hit
        lda #0
        sta BLOCKS,x
        lda #10
        clc
        adc PARTIDOS
        sta PARTIDOS
        lda #1
        eor BALL_DY
        sta BALL_DY
        lda BALL_DX
        eor #$FF
        clc
        adc #1
        sta BALL_DX             ; Rebote random
        jsr sid_hit_sound
        dec BLOCKS             ; Contador bloques vivos
        lda BLOCKS
        bne .no_level_up
        inc LEVEL
        lda #0
        sta BAJADAS
        jsr init_blocks
        lda BALL_DX
        asl                     ; Speed up
        sta BALL_DX
.no_level_up:
.no_block_hit:
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
        lda PARTIDOS
        clc
        adc #48
        sta SCREEN+12
        lda BAJADAS
        clc
        adc #48
        sta SCREEN+24
        lda LEVEL
        clc
        adc #48
        sta SCREEN+36
        rts

draw_blocks:
        ldx #0
draw_lp:
        lda BLOCKS,x
        beq .empty
        lda LEVEL
        and #3
        clc
        adc #2
        sta COLORRAM+240,x     ; Rows 6*40=240
        lda #160               ; █
        sta SCREEN+240,x
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
        lda #16                ; Noise
        sta SID+12
        lda #240
        sta SID+13
        lda #15
        sta SID+14
        lda #15
        sta SID+24
        lda #10
        sta HIT_TEMP
.delay_hit:
        dec HIT_TEMP
        bne .delay_hit
        lda #0
        sta SID+12
        rts

; Himno Uruguay - frase principal loop
himno_start:
        lda #0
        sta $90                ; Index nota
himno_frame:
        ldx $90
        lda himno_freq_low,x
        beq .end_himno
        sta SID+0
        lda himno_freq_high,x
        sta SID+1
        lda #17                ; Triangle + gate
        sta SID+4
        lda #$F0               ; ADSR
        sta SID+5
        sta SID+6
        inc $90
        rts
.end_himno:
        lda #0
        sta $90
        rts

update_himno:
        lda $90
        cmp #himno_length
        bcc .no_reset
        lda #0
        sta $90
.no_reset:
        jsr himno_frame
        rts

himno_freq_low:
        !byte $AC,$15,$7D,$E8,$5C,$D3,$52,$AC   ; D4 E4 F#4 G4 A4 B4 C#5 D5
        !byte $00
himno_freq_high:
        !byte $04,$05,$05,$05,$06,$06,$07,$07
        !byte $00
himno_length = *-himno_freq_low-1

; Sprites
* = $3000
paddle_data:
        !byte $3C,$7E,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$3C
        !fill 32,0

* = $3040
ball_data:
        !byte $18,$3C,$7E,$FF,$FF,$7E,$3C,$18
        !byte $3C,$7E,$FF,$FF,$FF,$FF,$7E,$3C
        !byte $7E,$FF,$FF,$FF,$FF,$FF,$FF,$7E
        !fill 32,0
