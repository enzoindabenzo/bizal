# Metodologjia e Matjes së Kohës së Onboarding-ut

Deri tani koha e onboarding-ut (nën 1 min / deri 2 min me detaje) është
matur **një herë, manualisht, nga vetë zhvilluesi** — e vlefshme si tregues
i parë, por jo si metodologji e përsëritshme që një komision do ta pranonte
si "matje" në kuptimin kërkimor. Ky skedar e formalizon.

## Protokolli

Për secilin test:

1. **Kush kronometron**: një person i dytë (jo vetë personi që kryen
   onboarding-un) — evito vetë-kronometrimin, sepse është e lehtë ta bësh
   pavetëdijshëm më shpejt/më ngadalë kur e di që matesh vetë.
2. **Pika e fillimit**: momenti kur pjesëmarrësi hap `/signup/` për herë të
   parë (jo kur fillon të lexojë udhëzime).
3. **Pika e mbarimit**: momenti kur portali publik i tenant-it ngarkohet me
   sukses (jo kur klikohet "Përfundo", por kur faqja publike vërtet shfaqet).
4. **Regjistro çdo ngecje**: nëse pjesëmarrësi ndalon/pyet/kthehet mbrapa,
   shëno se ku ndodhi dhe pse (jep evidencë cilësore për pikat problematike
   të UX-it, jo vetëm numrin final).
5. **Të paktën 2 kushte**: (a) "shpejt" — vetëm fushat e detyrueshme, (b)
   "të plotë" — të gjitha 6 hapat e wizard-it me detaje/logo/branding.

## Kush duhet të testojë

Për të qenë e besueshme, jo çdo pjesëmarrës duhet të jetë dikush si ty
(zhvillues me njohuri të BizAL). Sugjerohet përzierje:
- 1-2 që e kanë parë platformën më parë (baseline "best case")
- 3-5 që s'e kanë përdorur kurrë — këta japin numrin realist që vlen për
  thesë (lidhet direkt me pikën që ngrite më herët: "40+ nuk përdorin
  telefonin/appet si brezi i ri" — nëse testoni dikë nga ai grup, kjo është
  pikërisht ku do dilte problem real, jo në UI-në vetë)

## Tabela e regjistrimit (shembull — plotësoje me matje reale)

| # | Pjesëmarrësi | Njeh BizAL më parë? | Lloj biznesi zgjedhur | Kusht (shpejt/i plotë) | Kohë (min:sek) | Ngecje/vërejtje |
|---|---|---|---|---|---|---|
| 1 | | Po/Jo | | shpejt | | |
| 2 | | Po/Jo | | i plotë | | |
| 3 | | Po/Jo | | shpejt | | |

## Çfarë të raportosh në thesë

- Kohë mesatare + min/max, ndarë sipas "njeh platformën" vs. "s'e njeh"
  (dallimi mes këtyre dy grupeve është vetë gjetja interesante — tregon sa
  intuitive është designi për dikë krejt të ri, jo vetëm sa shpejt e bën
  vetë zhvilluesi)
- Lista e ngecjeve — bëhet lista e "problemeve UX të gjetura", e vlefshme
  edhe nëse koha mesatare është e mirë
- Krahasim (nëse mundesh) me kohën që do të merrte dikush të krijonte një
  portal të ngjashëm nga zero (edhe vlerësim i përafërt/literatura mjafton
  si pikë referimi, jo eksperiment i plotë i dytë)
