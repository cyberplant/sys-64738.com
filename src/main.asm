; ARKAN-BREAKOUT URUGUAYO - ML ACME COMPLETO (sin truncamientos)
; Compila: acme -f cbm -o arkanoid_uy.prg este_archivo.asm

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

; Variables zero page
PADDLE_X  = $80
BALL_X    = $81
BALL_Y    = $82
BALL_DX   = $83
BALL_DY   = $84
PARTIDOS  = $85
BAJADAS   = $86
LEVEL     = $87
NOTE_IDX  = $88     ; Índice para nota del himno
BLOCKS    = $90     ; $90 a $B7 = 40 bytes (1= bloque vivo)
HIT_TEMP  = $89

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
        lda #$10               ; Multicolor charset (Arkanoid style)
        sta $D016
        lda #0
        sta $D022
        lda #2
        sta $D023
        lda #5
        sta $D024
        rts

screen_text:
        ldx #0
text_loop:
        lda msg_text,x
        beq text_end
        sec
        sbc #64
        sta SCREEN+40*1+6,x
        lda #1
        sta COLORRAM+40*1+6,x
        inx
        cpx #30
        bne text_loop
text_end:
        rts

msg_text:
        !text "GUERRA DE SENALES BREAKOUT ML!"
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
clear_loop:
        sta SID,x
        dex
        bpl clear_loop
        lda #15
        sta SID+24
        lda #0
        sta NOTE_IDX
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
        beq .izquierda
        lda CIA1
        and #%00100000
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
        bcc .no_hit
        lda BALL_X
        cmp PADDLE_X
        bcc .no_hit
        lda PADDLE_X
        clc
        adc #40
        cmp BALL_X
        bcc .no_hit
        lda #1
        eor BALL_DY
        sta BALL_DY
        inc PARTIDOS
        jsr sid_hit_sound
.no_hit:
        rts

coll_blocks:
        lda BALL_Y
        sec
        sbc #48
        cmp #40
        bcs .no_hit_block
        lsr
        lsr
        lsr
        tay
        lda BALL_X
        lsr
        lsr
        lsr
        tax
        lda BLOCKS,x
        beq .no_hit_block
        lda #0
        sta BLOCKS,x
        lda PARTIDOS
        clc
        adc #10
        sta PARTIDOS
        lda #1
        eor BALL_DY
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
        lda PARTIDOS
        clc
        adc #48
        sta SCREEN+12
        lda BAJADAS
        clc
        adc #48
        sta SCREEN+24
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
        ldx NOTE_IDX
        lda himno_low,x
        beq .reset_note
        sta SID+0
        lda himno_high,x
        sta SID+1
        lda #17
        sta SID+4
        lda #$F0
        sta SID+5
        sta SID+6
        inc NOTE_IDX
        rts
.reset_note:
        lda #0
        sta NOTE_IDX
        rts

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
        !byte $18,$3C,$7E,$FF,$FF,$7E,$3C,$18
        !byte $3C,$7E,$FF,$FF,$FF,$FF,$7E,$3C
        !byte $7E,$FF,$FF,$FF,$FF,$FF,$FF,$7E
        !fill 32,0
