; *** GUERRA DE SEÑALES: BREAKOUT URUGUAYO - ML ACME ***
; POR GROK & LUAR ROJI - 2026
; COMPILA: acme -f cbm -o juego.prg juego.a
; LOAD "JUEGO.PRG",8,1

!cpu 6510

; Direcciones C64
SCREEN    = $0400
COLORRAM  = $D800
VIC       = $D000
SID       = $D400
CIA1      = $DC00
SPRITEN   = $D015  ; Sprite enable
SPRITECOL = $D025  ; Sprite 0 color
SPRITE0   = $07F8  ; Sprite pointers

; Variables (zero page)
PADDLE    = $80    ; Paddle X (0-37*8=296)
BALLX     = $81
BALLY     = $82
BALLDX    = $83    ; +/-1 o 2
BALLDY    = $84
SCOREH    = $85    ; Partidos hi/lo
SCOREL    = $86
BAJADAS   = $87
LEVEL     = $88
HITFLAG   = $89

!to "guerra_senales.prg",cbm  ; Output PRG auto-run

* = $0801
        !byte $0C,$08,$0A,$00,$9E,$20,$32,$30,$36,$31,$00,$00,$00  ; BASIC stub SYS 2064

* = $0810  ; Main code start
main:
        jsr init_screen
        jsr init_sprites
        jsr init_sid
        jsr draw_blocks
        jsr init_game

loop:
        jsr read_keys
        jsr move_paddle
        jsr move_ball
        jsr check_collisions
        jsr update_score
        jsr check_lose_level
        jmp loop

init_screen:
        lda #0
        sta $D020  ; Border negro
        sta $D021  ; Bg negro
        lda #$1B   ; 25 rows
        sta $D011
        lda #0
        sta $D016  ; Single color
        rts

init_sprites:
        lda #>SPRITE0/64
        sta SPRITE0     ; Sprite 0 ptr ($2000/64 = $80)
        sta SPRITE0+1   ; Sprite 1 ptr ($2040/64 = $81)
        lda #%00000011  ; Enable sprites 0(paleta),1(ball)
        sta SPRITEN
        lda #1          ; Blanco
        sta SPRITECOL
        sta SPRITECOL+1
        rts

init_sid:
        lda #0
        ldx #24
clear_sid:
        sta SID,x
        dex
        bpl clear_sid
        lda #15         ; Vol max
        sta SID+$18
        jsr himno_play  ; Arranca himno
        rts

init_game:
        lda #20*8       ; Paddle centro
        sta PADDLE
        lda #25*8       ; Bottom
        sta VIC+$00+1   ; Sprite 0 Y
        lda #15*8       ; Ball start
        sta BALLX
        sta VIC+$02     ; Sprite 1 X
        lda #12*8
        sta BALLY
        sta VIC+$03     ; Sprite 1 Y
        lda #2
        sta BALLDX
        lda #$FF        ; Arriba
        sta BALLDY
        lda #0
        sta SCOREH
        sta SCOREL
        sta BAJADAS
        sta LEVEL
        rts

read_keys:
        lda CIA1        ; Teclado
        and #%00010000  ; 1 (izq)
        beq key_left
        lda CIA1
        and #%00100000  ; 2 (der)
        beq key_right
        rts
key_left:
        dec PADDLE
        cmp #0
        bpl +
        lda #0
        sta PADDLE
+       rts
key_right:
        inc PADDLE
        cmp #37*8       ; Max right
        bmi +
        lda #37*8
        sta PADDLE
+       rts

move_paddle:
        lda PADDLE
        sta VIC+$00     ; Sprite 0 X
        rts

move_ball:
        lda BALLX
        clc
        adc BALLDX
        sta BALLX
        sta VIC+$02
        lda BALLY
        clc
        adc BALLDY
        sta BALLY
        sta VIC+$03
        rts

check_collisions:
        jsr coll_walls
        jsr coll_paddle
        jsr coll_blocks
        rts

coll_walls:
        lda BALLX
        cmp #0
        bne +
        lda #1
        eor BALLDX
        sta BALLDX
+       cmp #39*8
        bne +
        lda #1
        eor BALLDX
        sta BALLDX
+       lda BALLY
        cmp #40         ; Top
        bne +
        lda #1
        eor BALLDY
        sta BALLDY
+       cmp #23*8       ; Bottom
        bmi +
        inc BAJADAS
        jsr reset_ball
+       rts

coll_paddle:
        lda BALLY
        cmp #22*8       ; Paddle row
        bne +
        lda BALLX
        cmp PADDLE
        bcs +
        cmp PADDLE+4
        bcc +
        lda #1
        eor BALLDY      ; Rebote Y
        sta BALLDY
        inc SCOREL      ; +1 partido
+       rts

coll_blocks:
        ldy #0          ; Row offset
check_row:
        lda BALLY
        sec
        sbc #6*8 + y*8  ; Rows 6-9
        bmi next_row
        cmp #8
        bpl next_row
        ; Col check
        lda BALLX
        lsr
        lsr
        lsr             ; /8
        tax
        lda blocks,x    ; Block alive?
        beq next_row
        ; Hit!
        lda #0
        sta blocks,x
        inc SCOREH      ; +10 partidos
        lda #1
        eor BALLDY
        sta BALLDY      ; Rebote
        jsr sid_hit
next_row:
        iny
        cpy #4
        bne check_row
        rts

blocks:
        !fill 40,1      ; 40 bloques vivos (1=alive)

update_score:
        ; Poke score a screen (simple BCD print)
        lda SCOREH
        clc
        adc #48
        sta SCREEN+0+9
        lda SCOREL
        clc
        adc #48
        sta SCREEN+0+10
        lda BAJADAS
        clc
        adc #48
        sta SCREEN+0+20
        rts

check_lose_level:
        lda BAJADAS
        cmp #10
        bcc +
        jmp game_over
+       lda SCOREH
        cmp #3          ; 30 pts = level up
        bcc +
        inc LEVEL
        jsr draw_blocks
        lda #0
        sta SCOREH
+       rts

reset_ball:
        lda #15*8
        sta BALLX
        sta VIC+$02
        lda #12*8
        sta BALLY
        sta VIC+$03
        lda #2
        sta BALLDX
        lda #$FF
        sta BALLDY
        rts

draw_blocks:
        ldx #0
draw_loop:
        lda blocks,x
        beq empty
        txa
        and #7          ; Col color
        clc
        adc LEVEL
        and #15
        sta COLORRAM + 6*40 + x
        lda #160        ; █ block
        sta SCREEN + 6*40 + x
        jmp nextb
empty:
        lda #32
        sta SCREEN + 6*40 + x
        lda #0
        sta COLORRAM + 6*40 + x
nextb:
        inx
        cpx #40
        bne draw_loop
        rts

sid_hit:
        lda #16         ; Noise
        sta SID+$12
        lda #240
        sta SID+$13
        lda #15
        sta SID+$14
        lda #15
        sta SID+$18
        rts

himno_play:
        ; Himno Uruguay: notas aprox D4 E F# G A B C# D5 (freq SID)
        ; Freq table stub (low,hi)
himno_notes:
        !byte $AC,$04  ; D4
        !byte $15,$05  ; E4
        !byte $7D,$05  ; F#4
        !byte $E8,$05  ; G4
        !byte $5C,$06  ; A4
        !byte $D3,$06  ; B4
        !byte $52,$07  ; C#5
        !byte $AC,$07  ; D5
        !byte 0

        ldx #0
himno_loop:
        lda himno_notes,x
        beq end_himno
        sta SID+$00     ; Freq low
        inx
        lda himno_notes,x
        sta SID+$01     ; Freq hi
        inx
        lda #17         ; Triangle + gate
        sta SID+$04
        lda #$F0        ; ADSR corto
        sta SID+$05
        sta SID+$06
        jsr delay_500ms
        lda #16         ; Gate off
        sta SID+$04
        jmp himno_loop
end_himno:
        rts

delay_500ms:
        ldx #50
delay1:
        ldy #255
delay2:
        dey
        bne delay2
        dex
        bne delay1
        rts

game_over:
        ; Print lose
        lda #2
        sta $D020
        lda #82         ; R
        sta SCREEN+12*40+10
        ; Infinite loop
-       jmp -

; Sprites en $2000
* = $2000
paleta_sprite:  ; Control remoto ▄▄▄▄
        !byte $FF,$FF,$FF,$FF
        !byte $FF,$18,$18,$FF
        !byte $FF,$18,$18,$FF
        !byte $FF,$FF,$FF,$FF
        !fill 48,0      ; 64 bytes total

pelota_sprite:  ; Fútbol ●
        !byte $18,$3C,$7E,$FF
        !byte $FF,$7E,$3C,$18
        !byte $24,$42,$81,$00
        !byte $00,$81,$42,$24
        !fill 40,0

; Screen titles (pre-poke)
* = SCREEN
        !text " partidos:  bajadas:  level: "
        !fill 960,32    ; Resto screen

; Fin
