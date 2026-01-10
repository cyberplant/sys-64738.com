10 rem *** guerra de se#ales: breakout uruguayo ***
20 rem por grok & luar roji - texto bloques fast 2026
30 rem sin sonido - bloques con conflicto - rapido
40 rem ---------------------------------------------
50 pp=17:rem paleta pos
60 sm=1024:cb=55296:rem screen y color ram
70 sa=sm+880:rem paleta row 22
80 dx=1:dy=-1:rem direccion pelota (arriba al empezar)
90 x=20:y=12:rem posicion pelota
100 h=0:ms=0:bh=0:le=0:rem partidos/bajadas/bloques/nivel
110 rem ---------------------------------------------
120 rem setup pantalla
130 rem ---------------------------------------------
140 poke 53280,0:poke 53281,0:rem negro total
150 print chr$(147):rem clear
160 print "partidos:00 bajadas:00 level:00   "
170 rem titulos coloreados
180 poke 646,7:print chr$(13)tab(7)"guerra de se#ales"
190 poke 646,6:print chr$(13)tab(11)"breakout uruguayo"
200 poke 646,3:print chr$(13)tab(4)"1=izq 2=der - recupera el futbol!"
210 print chr$(13)chr$(13):rem salta a row 6
220 rem ---------------------------------------------
230 rem dibujar bloques iniciales
240 rem ---------------------------------------------
250 gosub 1200:rem limpiar y dibujar
260 rem ---------------------------------------------
270 rem loop principal
280 rem ---------------------------------------------
290 rem dibujar paleta + color azul claro
300 sp=sa+pp
310 poke sp,32:poke sp+1,98:poke sp+2,98
320 poke sp+3,98:poke sp+4,98:poke sp+5,32
330 for i=1 to 4:poke cb+sp+i,14:next i
340 rem ---------------------------------------------
350 rem input teclas
360 get k$:k=val(k$):pp=pp+(k=1)-(k=2)
370 if pp<0 then pp=0
380 if pp>34 then pp=34
390 rem ---------------------------------------------
400 rem borrar pelota vieja
410 poke sm+x+(y*40),32:poke cb+x+(y*40),0
420 rem mover a nueva posicion
430 nx=x+dx:ny=y+dy
440 rem rebote lados
450 if nx<1 then nx=1:dx=-dx:gosub 1400
460 if nx>39 then nx=39:dx=-dx:gosub 1400
470 rem rebote techo (no toca texto)
480 if ny<5 then ny=5:dy=-dy:gosub 1400
490 rem bajada (miss)
500 if ny>23 then ms=ms+1:gosub 1400:nx=20:ny=12:dx=1:dy=-1
510 x=nx:y=ny
520 rem ---------------------------------------------
530 rem chequeo colision bloques (rows 6-10)
540 if y<6 or y>10 then goto 700
550 bx=int(x/5)*5
560 if (x-bx)>3 then goto 700
570 p=peek(sm+y*40+bx)
580 if p=32 then goto 700
590 rem *** golpe! borrar bloque completo ***
600 for i=0 to 3:poke sm+y*40+bx+i,32:poke cb+y*40+bx+i,0:next i
610 bh=bh+1:h=h+10:dy=-dy:dx=dx*(2*int(rnd(1)*2)-1):gosub 1400
620 goto 700
630 rem ---------------------------------------------
640 rem colision paleta (row 22)
650 rem ---------------------------------------------
700 if y=22 and peek(sm+x+(22*40))=98 then dx=-dx:dy=-dy:h=h+1:gosub 1400
710 rem ---------------------------------------------
720 rem dibujar pelota naranja
730 poke sm+x+(y*40),81:poke cb+x+(y*40),12
740 rem ---------------------------------------------
750 gosub 900:rem actualizar puntajes
760 if ms>15 then gosub 1000:end
770 if bh>=40 then gosub 1100
780 goto 290
790 rem ---------------------------------------------
800 rem sub actualizar puntajes
810 rem ---------------------------------------------
900 h1=int(h/10):h2=h-10*h1
910 poke 1024+9,48+h1:poke 1024+10,48+h2
920 m1=int(ms/10):m2=ms-10*m1
930 poke 1024+20,48+m1:poke 1024+21,48+m2
940 l1=int(le/10):l2=le-10*l1
950 poke 1024+31,48+l1:poke 1024+32,48+l2
960 return
970 rem ---------------------------------------------
980 rem sub game over
990 rem ---------------------------------------------
1000 poke 646,2:print chr$(147)chr$(145)"{down*2}¡perdiste! mas bajadas que partidos!"
1010 print "partidos:"h" bajadas:"ms" nivel:"le
1020 end
1030 rem ---------------------------------------------
1040 rem sub siguiente nivel
1050 rem ---------------------------------------------
1100 le=le+1
1110 gosub 1200:rem limpiar y dibujar nuevo
1120 return
1130 rem ---------------------------------------------
1140 rem sub dibujar bloques (8x5=40 por nivel)
1150 rem ---------------------------------------------
1200 rem limpiar area rows 6-10
1210 for r=6 to 10:for c=0 to 39:poke sm+r*40+c,32:poke cb+r*40+c,0:next c:next r
1220 rem dibujar bloques solidos con texto conflicto
1230 data "vtv ","can10","can12","goltv","dirtv","flow ","montec","nuevsc"
1240 data "tenfl","casal","paco ","auf  ","senal","bajada","cable ","futbol"
1250 data "premi","basquet","carna","grilla","derech","antel ","saad  ","tcc   "
1260 for r=6 to 10:rr=r-6
1270   for b=0 to 7
1280     read txt$
1290     o=r*40 + b*5
1300     cc=(b + rr*3 + le) and 15 + 2:rem colores variados
1310     for i=0 to 3
1320       poke sm+o+i,asc(mid$(txt$,i+1,1))
1330       poke cb+o+i,cc
1340     next i
1350     poke sm+o+4,32:poke cb+o+4,0:rem espacio negro
1360   next b
1370 next r
1380 return
1390 rem ---------------------------------------------
1400 rem sub sonido simple (pitido corto, sin sid complejo)
1410 rem podes comentar todo este sub si queres max velocidad
1420 poke 54296,15:poke 54276,33:poke 54277,0:poke 54278,240
1430 for w=1 to 20:next w:poke 54296,0
1440 return
