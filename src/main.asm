; GUERRA DE SEÑALES - ML ACME - FIXED 8-BIT VALUES
!cpu 6510
!to "juego.prg",cbm

SCREEN    = $0400
COLORRAM  = $D800
VIC       = $D000
CIA1      = $DC00
SPRITEN   = $D015
SPRITEC0  = $D027
SPRITEC1  = $D028

PADDLE_X  = $80     ; 0..240 (ajustado para caber)
BALL_X    = $81
BALL_Y    = $82
BALL_DX   = $83
BALL_DY   = $84
PARTIDOS  = $85
BAJADAS   = $86

* = $0801
        !byte $0C,$08,$0A,$00,$9E,$32,$30,$36,$31,$00,$00,$00

* = $2000

start:
        jsr init_screen
        jsr screen_text
        jsr init_sprites
        jsr init_game

main_loop:
        jsr read_keys
        jsr move_paddle
        jsr move_ball
        jsr check_collisions
        jsr update_scores
        jmp main_loop

init_screen:
        lda #0
        sta $D020
        sta $D021
        lda #$1B
        sta $D011
        lda #0
        sta $D016
        rts

screen_text:
        ldx #0
text_loop:
        lda msg_text,x
        beq text_end
        sec
        sbc #64
        sta SCREEN+40*3+8,x    ; fila 3, más centrado
        lda #7
        sta COLORRAM+40*3+8,x
        inx
        cpx #msg_length
        bne text_loop
text_end:
        rts

init_sprites:
        lda #$C0               ; $3000 / 64 = $C0
        sta $07F8
        lda #$C1               ; $3040 / 64 = $C1
        sta $07F9
        lda #%00000011
        sta SPRITEN
        lda #14
        sta SPRITEC0
        lda #12
        sta SPRITEC1
        rts

init_game:
        lda #120               ; Paddle centro (ajustado)
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
        lda #$FE               ; -2
        sta BALL_DY
        lda #0
        sta PARTIDOS
        sta BAJADAS
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
        bcs .fin_keys
        lda #24
        sta PADDLE_X
        jmp .fin_keys

.der:
        inc PADDLE_X
        lda PADDLE_X
        cmp #240               ; Max ajustado (cabe en 8 bits)
        bcc .fin_keys
        lda #240
        sta PADDLE_X

.fin_keys:
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
        rts

coll_walls:
        lda BALL_X
        cmp #32                 ; Izquierda ajustada
        bcs .no_left
        lda #1
        eor BALL_DX
        sta BALL_DX
.no_left:
        cmp #280                ; Derecha ajustada
        bcc .no_right
        lda #1
        eor BALL_DX
        sta BALL_DX
.no_right:
        lda BALL_Y
        cmp #56                 ; Techo
        bcs .no_top
        lda #1
        eor BALL_DY
        sta BALL_DY
.no_top:
        cmp #200                ; Bottom
        bcc .no_bot
        inc BAJADAS
        jsr reset_ball
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
        adc #40                 ; Ancho paddle aproximado
        cmp BALL_X
        bcc .no_hit
        lda #1
        eor BALL_DY
        sta BALL_DY
        inc PARTIDOS
.no_hit:
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

msg_text:
        !text "GUERRA DE SENALES - ML FUNCIONA!"
        !byte 0
msg_length = *-msg_text-1

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
