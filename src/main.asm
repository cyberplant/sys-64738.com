; GUERRA DE SEÑALES - ML ACME - Versión mínima para probar
; Compila: acme -f cbm -o juego.prg este_archivo.asm

!cpu 6510
!to "juego.prg",cbm     ; <-- SIEMPRE AL PRINCIPIO!!!

; Direcciones básicas
SCREEN = $0400
VIC    = $D000

* = $0801
        !byte $0C, $08, $0A, $00, $9E, $20, $34, $30, $39, $36, $00, $00, $00   ; 10 SYS 4096

* = $1000   ; Código empieza en $1000 (SYS 4096)

start:
        lda #0
        sta $D020               ; border negro
        sta $D021               ; fondo negro

        ; Mensaje simple en pantalla
        ldx #0
msg_loop:
        lda message,x
        beq done
        sta SCREEN+120,x        ; Centro pantalla aprox
        lda #1                  ; color blanco
        sta COLORRAM+120,x
        inx
        bne msg_loop

done:
        lda #80                 ; X=80 (centro)
        sta VIC+0               ; Sprite 0 X
        lda #200                ; Y=200 (abajo)
        sta VIC+1               ; Sprite 0 Y
        lda #%00000001          ; Enable sprite 0
        sta $D015
        lda #1                  ; Color blanco
        sta $D027

        jmp *                   ; Loop infinito

message:
        !text "GUERRA DE SENALES - ML FUNCIONANDO!"
        !byte 0

; Sprite simple (cuadrado blanco)
* = $2000   ; $2000 / 64 = $80 → pointer $80
        !byte $FF,$FF,$FF
        !byte $FF,$FF,$FF
        !byte $FF,$FF,$FF
        !byte $FF,$FF,$FF
        !fill 48,$00            ; Relleno a 64 bytes
