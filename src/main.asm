; GUERRA DE SEÑALES - ML ACME - Paddle + Pelota + Rebotes
; Compila: acme -f cbm -o juego.prg este_archivo.asm
; LOAD "JUEGO.PRG",8,1

!cpu 6510
!to "juego.prg",cbm

SCREEN    = $0400
COLORRAM  = $D800
VIC       = $D000
CIA1      = $DC00
SPRITEN   = $D015
SPRITEC0  = $D027   ; Color sprite 0
SPRITEC1  = $D028   ; Color sprite 1

PADDLE_X  = $80
BALL_X    = $81
BALL_Y    = $82
BALL_DX   = $83
BALL_DY   = $84
PARTIDOS  = $85
BAJADAS   = $86

* = $0801
        !byte $0C, $08, $0A, $00, $9E, $32, $30, $36, $31, $00, $00, $00   ; SYS 8192

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
        sbc #64                ; PETSCII → screen code
        sta SCREEN+40*2+10,x   ; fila ~3, centrado
        lda #7                 ; amarillo
        sta COLORRAM+40*2+10,x
        inx
        cpx #msg_length
        bne text_loop
text_end:
        rts

init_sprites:
        lda #$C0               ; $3000 / 64 = $C0 → paddle
        sta $07F8
        lda #$C1               ; $3040 / 64 = $C1 → pelota
        sta $07F9
        lda #%00000011
        sta SPRITEN
        lda #14                ; celeste paddle
        sta SPRITEC0
        lda #12                ; naranja pelota
        sta SPRITEC1
        rts

init_game:
        lda #160
        sta PADDLE_X
        lda #220
        sta VIC+1              ; paddle Y
        lda #160
        sta BALL_X
        sta VIC+2              ; ball X
        lda #100
        sta BALL_Y
        sta VIC+3              ; ball Y
        lda #2
        sta BALL_DX
        lda #$FE               ; -2 arriba
        sta BALL_DY
        lda #0
        sta PARTIDOS
        sta BAJADAS
        rts

read_keys:
        lda CIA1
        and #%00010000         ; 1 = izquierda
        beq .izquierda
        lda CIA1
        and #%00100000         ; 2 = derecha
        beq .derecha
        rts

.izquierda:
        dec PADDLE_X
        lda PADDLE_X
        cmp #16
        bcs .fin_keys
        lda #16
        sta PADDLE_X
        jmp .fin_keys

.derecha:
        inc PADDLE_X
        lda PADDLE_X
        cmp #280
        bcc .fin_keys
        lda #280
        sta PADDLE_X

.fin_keys:
        rts

move_paddle:
        lda PADDLE_X
        sta VIC+0              ; sprite 0 X
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
        cmp #24
        bcs .no_left_wall
        lda #1
        eor BALL_DX
        sta BALL_DX
.no_left_wall:
        cmp #312
        bcc .no_right_wall
        lda #1
        eor BALL_DX
        sta BALL_DX
.no_right_wall:
        lda BALL_Y
        cmp #48
        bcs .no_top
        lda #1
        eor BALL_DY
        sta BALL_DY
.no_top:
        cmp #216
        bcc .no_bottom
        inc BAJADAS
        jsr reset_ball
.no_bottom:
        rts

coll_paddle:
        lda BALL_Y
        cmp #208
        bcc .no_paddle_hit
        lda BALL_X
        cmp PADDLE_X
        bcc .no_paddle_hit
        lda PADDLE_X
        clc
        adc #32
        cmp BALL_X
        bcc .no_paddle_hit
        lda #1
        eor BALL_DY
        sta BALL_DY
        inc PARTIDOS
.no_paddle_hit:
        rts

reset_ball:
        lda #160
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
        !text "GUERRA DE SENALES BREAKOUT ML!"
        !byte 0
msg_length = *-msg_text-1

; Sprites al FINAL (después del código)
* = $3000
paddle_data:    ; Barra ancha simple
        !byte $3C,$7E,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF,$3C
        !fill 32,0

* = $3040
ball_data:      ; Pelota redonda
        !byte $18,$3C,$7E,$FF,$FF,$7E,$3C,$18
        !byte $3C,$7E,$FF,$FF,$FF,$FF,$7E,$3C
        !byte $7E,$FF,$FF,$FF,$FF,$FF,$FF,$7E
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF
        !fill 32,0
