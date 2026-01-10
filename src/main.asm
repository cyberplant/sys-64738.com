; GUERRA DE SEÑALES - ML ACME MINIMAL - FIXED ERRORS
; Compila: acme -f cbm -o juego.prg este_archivo.asm
; LOAD "JUEGO.PRG",8,1 en VICE

!cpu 6510
!to "juego.prg",cbm     ; <-- SOLO UNA VEZ, AL PRINCIPIO!!!

; Direcciones C64
SCREEN   = $0400
COLORRAM = $D800         ; <-- ESTO FALTABA! $D800 Color RAM
VIC      = $D000

* = $0801
        !byte $0C, $08, $0A, $00, $9E, $20, $34, $30, $39, $36, $00, $00, $00  ; SYS 4096

* = $1000  ; Start code $1000 (SYS 4096)

start:
        lda #0
        sta $D020      ; Border negro
        sta $D021      ; Bg negro

        ; Mensaje en pantalla centro
        ldx #0
msg_loop:
        lda message,x
        beq msg_done
        sta SCREEN+120,x     ; Fila ~12, col 0+
        lda #7               ; Amarillo para tema
        sta COLORRAM+120,x
        inx
        cpx #28              ; Longitud msg
        bne msg_loop

msg_done:
        ; Sprite simple abajo centro
        lda #160            ; X centro (320/2)
        sta VIC+0           ; Sprite 0 X
        lda #220            ; Y abajo
        sta VIC+1           ; Sprite 0 Y
        lda #%00000001      ; Enable sprite 0
        sta $D015
        lda #6              ; Azul claro
        sta $D027           ; Sprite 0 color

loop:   jmp loop            ; Infinito - agrega logica aqui despues

message:
        !text "GUERRA DE SENALES ML OK! 1=IZQ 2=DER"
        !byte 0

; Sprite 0: Barra paleta ▄▄▄▄ (24x21 pixels)
* = $2000                 ; $2000 / 64 = $80 → POKE $07F8,$80
        !byte $3C,$7E,$FF,$FF,$FF,$FF,$FF,$FF  ; Fila 0
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 1
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 2
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 3
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 4
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 5
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 6
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 7
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 8
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 9
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 10
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 11
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 12
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 13
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 14
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 15
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 16
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 17
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 18
        !byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF  ; 19
        !byte $3C,$7E,$FF,$FF,$FF,$FF,$FF,$FF  ; 20 Fila final
