* = $c000   // Start at $C000 (SYS 49152 to run)

 // Constants
screen = $0400
color = $d800
vic = $d000
sid = $d400
paddle_x = $d000   // Sprite 0 X
paddle_y = $d001   // Sprite 0 Y
ball_x = $d002     // Sprite 1 X
ball_y = $d003     // Sprite 1 Y
sprite_en = $d015
sprite_mult = $d017
sprite_prior = $d01b
sprite_col = $d027

 // Variables
paddle_pos: .byte 160   // Paddle X (0-320)
ball_pos_x: .byte 160
ball_pos_y: .byte 100
ball_dx: .byte 2
ball_dy: .byte -2
score: .byte 0,0   // BCD
lives: .byte 3
level: .byte 1

main:
  jsr init_vic
  jsr init_sid
  jsr draw_blocks
  jsr init_sprites
  jsr init_irq
loop:
  jmp loop   // Main loop empty, all in IRQ

init_vic:
  lda #0
  sta $d020   // Border black
  sta $d021   // Background black
  lda #59     // Standard video mode + ECM if wanted
  sta $d011
  lda #8      // Multicolor off
  sta $d016
  rts

init_sid:
  lda #0
  ldx #24
sid_clear:
  sta sid,x
  dex
  bpl sid_clear
  lda #15   // Volume max
  sta sid+24
  jsr play_himno   // Start music
  rts

init_sprites:
  lda #64   // Sprite pointers to $1000
  sta $07f8   // Sprite 0 pointer (paddle)
  lda #65
  sta $07f9   // Sprite 1 pointer (ball)
  lda #3
  sta sprite_en   // Enable sprites 0 and 1
  lda #0
  sta sprite_mult   // No multicolor
  sta sprite_prior   // Sprites over background
  lda #1
  sta sprite_col   // Paddle white
  sta sprite_col+1 // Ball white
  lda #160
  sta paddle_x
  sta paddle_y   // Y = 200 (bottom)
  sta ball_x
  sta ball_y = 100
  rts

init_irq:
  sei
  lda #1
  sta $d019
  sta $d01a   // IRQ on raster
  lda #$7f
  sta $dc0d   // Disable timer IRQ
  lda #0
  sta $d012   // Raster line 0
  lda #<irq_handler
  sta $0314
  lda #>irq_handler
  sta $0315
  cli
  rts

irq_handler:
  lda #1
  sta $d019   // Ack IRQ
  jsr update_paddle
  jsr update_ball
  jsr check_collision
  jsr update_music
  jsr update_sound
  rti

update_paddle:
  lda $dc00   // Joystick or keys
  and #4      // Left
  beq left
  and #8      // Right
  beq right
  rts
left:
  dec paddle_pos
  rts
right:
  inc paddle_pos
  rts

update_ball:
  lda ball_pos_x
  clc
  adc ball_dx
  sta ball_pos_x
  lda ball_pos_y
  clc
  adc ball_dy
  sta ball_pos_y
  // Bounce logic similar to BASIC
  // ...
  rts

check_collision:
  // Coll with paddle, blocks, etc.
  // Increase score, break blocks
  rts

draw_blocks:
  // Poke screen with blocks, colors
  rts

play_himno:
  // SID data for himno uruguayo melody
  // Example notes: A4, B4, C5, etc.
  // Use ADSR, waveform triangle
  lda #9   // Triangle
  sta sid+4
  lda #15  // Attack 0, Decay 0, Sustain 15, Release 0
  sta sid+5
  sta sid+6
  // Notes data in table
  rts

update_music:
  // Cycle through notes
  rts

update_sound:
  // If collision, trigger noise
  lda #129   // Noise wave
  sta sid+18
  lda #15
  sta sid+19
  // Delay then off
  rts

 // Sprite data at $1000 (64 bytes per sprite)
* = $1000
paddle_sprite:
 .byte %00111100,%01111110,%11111111
 // ... 64 bytes for control remoto shape

ball_sprite:
 .byte %00011000,%00111100,%01111110
 // ... 64 bytes for futbol ball

 // End
 .text "by grok & luar - 2026"
