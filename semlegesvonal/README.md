# Semlegesvonal QGIS plugin

Elso prototipus QGIS 3.34+ ala.

## Cel

Ket terkepen kijelolt pont kozott DEM raszteren keres olyan polyline-t, amely
a megadott cel-lejtest koveti, es a celpont megadott meteres korzetebe erkezik.
A cellarol cellara szamitott lejtes csak a cel-lejtes +/- 0,5%-os savjaban
engedelyezett.
Az algoritmus adott lepeshossz mellett, iranyonként interpolalt DEM pontokon
keresi a cel-lejtesu folytatast.

## Hasznalat

1. Masold a `semlegesvonal` mappat a QGIS plugin konyvtaraba.
2. QGIS-ben engedelyezd a `Semlegesvonal` plugint.
3. Valassz DEM rasztert.
4. Kattints ket pontot a terkepen.
5. A plugin megprobalja kirajzolni az eredmeny vonalat memoria retegkent.
6. Az `SHP mentes` gombbal shapefile-ba irhato.

## Jelenlegi korlatok

- Ez meg minimum prototipus, 8 szomszedos rasztercellan lepked.
- A cel-lejtes jelenleg egyetlen, signed ertek; automatikus modban az A-B
  magassagkulonbsegbol szamolja.
- A tures erkezesi sugar meterben, nem lejtesszazalek.
- A szakaszon beluli eses-emelkedes valtas es a hosszabb konstans lejtesu
  szakaszok kulon optimalizalasa kovetkezo fejlesztesi lepes.
