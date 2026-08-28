# Pyetësor Përdorshmërie — BizAL (Pilot)

Pjesa e "përdorshmërisë" e pyetjes kërkimore — deri tani mungonte plotësisht
si artefakt (ishte identifikuar si "pjesa e lehtë", por s'kishte ende asnjë
formë konkrete). Ky është një skelet gati-për-përdorim: **SUS (System
Usability Scale)**, standardi më i përdorur akademikisht për pikërisht këtë
qëllim — 10 pyetje, shkallë 1-5, rezultat i krahasueshëm (0-100) me norma
publike të vendosura (mesatarja industriale ~68).

Pse SUS dhe jo pyetësor i shpikur nga zeroja: (1) është i validuar shkencor-
isht dhe kërkimtarë të tjerë e njohin/pranojnë menjëherë, (2) rezultati
numerik (0-100) mund të krahasohet drejtpërdrejt me "SUS mesatar" të
publikuar në literaturë, gjë që i jep peshë empirike krahasuese thesës,
(3) mund të plotësohet në ~2 minuta — realiste për pronarë biznesesh të
zënë.

## Protokolli i pilotit (propozim)

1. **Rekrutim**: 5-8 pjesëmarrës mjafton për SUS (Nielsen: 5 përdorues
   zbulojnë ~85% të problemeve të përdorshmërisë). Kombinim i sugjeruar:
   2-3 pronarë biznesesh realë (nëse mund të gjenden), pjesa tjetër shokë/
   familje që s'e kanë përdorur BizAL më parë (jo studentë të TI-së — duam
   perspektivën e përdoruesit "normal", jo dikë që e njeh Django admin).
2. **Detyra e strukturuar** përpara pyetësorit — jo thjesht "hidhi një sy":
   p.sh. "Krijo një tenant të ri restorant nga zero deri te faqja publike
   e gatshme" (këtë e ke kohëmatur tashmë — nën 1 min / deri 2 min me
   detaje). Kjo lidh drejtpërdrejt të dhënat e onboarding-ut me pyetësorin.
3. Menjëherë pas detyrës, plotëson pyetësorin më poshtë (jo ditë më vonë).
4. Regjistro: kohën reale që mori (kronometro), sa herë kërkoi ndihmë/u
   ngec, dhe përgjigjet SUS.

## Pyetësori (10 pyetje standarde SUS, të përkthyera)

Për secilën pohim, shëno sa dakord je, nga **1 (Aspak dakord)** deri
**5 (Plotësisht dakord)**:

1. Do të doja ta përdorja këtë platformë shpesh.
2. E gjeta platformën më komplekse nga sa duhej të ishte.
3. E gjeta platformën të lehtë për t'u përdorur.
4. Do të kisha nevojë për ndihmën e një personi teknik për ta përdorur këtë platformë.
5. Funksionet e platformës ishin të integruara mirë me njëra-tjetrën.
6. Gjeta shumë mospërputhje në platformë.
7. Mendoj se shumica e njerëzve do ta mësonin ta përdornin këtë platformë shumë shpejt.
8. E gjeta platformën shumë të vështirë për t'u përdorur.
9. U ndjeva shumë i/e sigurt gjatë përdorimit të platformës.
10. Më duhej të mësoja shumë gjëra përpara se të mund ta përdorja platformën.

## Si llogaritet rezultati (SUS Score)

- Pyetjet **teke (1,3,5,7,9)**: pikët = (përgjigja − 1)
- Pyetjet **çifte (2,4,6,8,10)**: pikët = (5 − përgjigja)
- Mblidh të gjitha pikët (0-40 total) × 2.5 = **SUS Score (0-100)**

Interpretim i përafërt (referencë standarde, Bangor et al.):
| SUS Score | Interpretim |
|---|---|
| >80 | Shkëlqyer |
| 68-80 | Mbi mesataren |
| ~68 | Mesatarja industriale |
| 51-68 | Nën mesataren |
| <51 | Problem serioz përdorshmërie |

## Çfarë të raportosh në thesë

- SUS score mesatar i të gjithë pjesëmarrësve + shpërndarja (min/max)
- Krahasim me mesataren industriale (~68) — a je sipër apo nën
- Kohët reale të detyrës (nga kronometrimi), të lidhura me pyetjen kërkimore
  për "kohë/përpjekje"
- 2-3 citate/komente të lira nga pjesëmarrësit (nëse mbledh komente shtesë
  krahas pyetësorit numerik) — shton kontekst cilësor mbi numrat e thatë

## Shënim metodologjik

Meqë pjesëmarrësit janë pak (5-8), mos e paraqit rezultatin si "statistikisht
domethënës" në kuptimin formal (p-value, etj.) — trajtoje si **studim pilot
kualitativ me mbështetje sasiore**, gjë që është krejt legjitime dhe e
pritshme për një thesë të këtij lloji. Thuaje këtë hapur në kufizimet e
metodologjisë — një thesë që e pranon ndershmërisht kufizimin e vet të
mostrës është më e fortë se një që pretendon më shumë se ç'ka.
