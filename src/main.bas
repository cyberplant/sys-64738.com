10 rem *** guerra de se#ales: breakout uruguayo - ecm 6 bloques ***
20 rem por grok & luar roji - espacios + fix data 2026
30 rem ---------------------------------------------
40 poke 53265,peek(53265) or 64 : rem activa ecm
50 poke 53281,0 : poke 53282,2 : poke 53283,5 : poke 53284,7 : rem fondos negro/rojo/verde/amarillo
60 pp=17:rem paleta pos
70 sm=1024:cb=55296
80 sa=sm+880
90 dx=1:dy=-1
100 x=20:y=12
110 h=0:ms=0:bh=0:le=0
120 poke 53280,0:print chr$(147)
130 print "partidos:00 bajadas:00 level:00   "
140 poke 646,7:print chr$(13)tab(7)"guerra de se#ales"
150 poke 646,6:print chr$(13)tab(11)"breakout uruguayo"
160 poke 646,3:print chr$(13)tab(4)"1=izq 2=der - recupera el futbol!"
170 print chr$(13)chr$(13)
180 gosub 1200
190 rem loop
200 sp=sa+pp
210 poke sp,32:poke sp+1,98:poke sp+2,98:poke sp+3,98:poke sp+4,98:poke sp+5,32
220 for i=1 to 4:poke cb+sp+i,14:next
230 get k$:k=val(k$):pp=pp+(k=1)-(k=2)
240 if pp<0 then pp=0
250 if pp>34 then pp=34
260 poke sm+x+(y*40),32:poke cb+x+(y*40),0
270 nx=x+dx:ny=y+dy
280 if nx<1 then nx=1:dx=-dx
290 if nx>39 then nx=39:dx=-dx
300 if ny<5 then ny=5:dy=-dy
310 if ny>23 then ms=ms+1:nx=20:ny=12:dx=1:dy=-1
320 x=nx:y=ny
330 if y<6 or y>10 then goto 440
340 bx=int(x/6)*6 : rem ajustado para 6 chars por bloque + espacio
350 if (x-bx)>4 then goto 440
360 p=peek(sm+y*40+bx)
370 if p=32 then goto 440
380 for i=0 to 4:poke sm+y*40+bx+i,32:poke cb+y*40+bx+i,0:next
390 bh=bh+1:h=h+10:dy=-dy:dx=dx*(2*int(rnd(1)*2)-1)
400 rem ---------------------------------------------
440 if y=22 and peek(sm+x+880)=98 then dx=-dx:dy=-dy:h=h+1
450 poke sm+x+(y*40),81:poke cb+x+(y*40),12
460 gosub 900
470 if ms>15 then gosub 1000:end
480 if bh>=30 then le=le+1:gosub 1200
490 goto 190
500 rem puntajes
900 h1=int(h/10):h2=h-10*h1
910 poke 1024+9,48+h1:poke 1024+10,48+h2
920 m1=int(ms/10):m2=ms-10*m1
930 poke 1024+20,48+m1:poke 1024+21,48+m2
940 l1=int(le/10):l2=le-10*l1
950 poke 1024+31,48+l1:poke 1024+32,48+l2
960 return
970 rem game over
1000 poke 646,2:print chr$(147)chr$(145)"{down*2}perdiste! mas bajadas que partidos!"
1010 print "partidos:"h" bajadas:"ms" nivel:"le
1020 end
1030 rem dibujar bloques ecm - 6 por fila con espacio
1040 rem ---------------------------------------------
1200 for r=6 to 10:for c=0 to 39:poke sm+r*40+c,32:poke cb+r*40+c,0:next c:next r
1210 for r=6 to 10
1220   rr=r-6
1230   for b=0 to 5
1240     read t$
1250     o=r*40 + b*6
1260     bg=(b + rr + le) and 3
1270     offset=bg*64
1280     for i=0 to 4
1290       ch$=mid$(t$,i+1,1)
1300       if ch$=" " then sc=32:goto 1340
1310       if ch$>="0" and ch$<="9" then sc=asc(ch$):goto 1340
1320       sc=asc(ch$)-64
1330       if sc<1 or sc>26 then sc=32
1340       poke sm+o+i,sc+offset
1350       poke cb+o+i,1 : rem texto blanco
1360     next i
1370     poke sm+o+5,32:poke cb+o+5,0 : rem espacio separador negro
1380   next b
1390 next r
1400 return
1410 data "vtv  ","can10","goltv","dirtv","flow ","monte"
1420 data "tenfl","casal","paco ","auf  ","senal","bajada"
1430 data "premi","basqu","carna","grill","derec","antel"
1440 data "tv ca","tenfi","p cas","acuer","p dir","futbo"
1450 data "can12","tcc  ","nuevs","mon+ ","dirt+ ","v tv+"
