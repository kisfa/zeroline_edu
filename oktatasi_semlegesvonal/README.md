# Oktatási semlegesvonal

QGIS 3.34+ plugin interaktív, állandó meredekségű nyomvonal-tervezéshez.

## Használat

1. Telepítsd a teljes `oktatasi_semlegesvonal` mappát a QGIS profil
   `python/plugins` könyvtárába, majd engedélyezd a plugint.
2. A projekt koordináta-rendszere legyen vetületi, méter alapú CRS.
3. Válassz GDAL-lal megnyitható DEM-et és rasztersávot. A mintavétel 4×4
   környezetű kubikus B-spline interpolációval történik.
4. Add meg az előjeles meredekséget és a lépéshosszt, jelöld ki a kezdőpontot,
   valamint igény szerint a célpontot.
5. Indítsd a tervezést. A halvány kék szakaszok az összes pontosan elérhető
   következő pontot jelzik; az egérhez legközelebbi irány zöld. Bal kattintás
   elfogadja az aktív szakaszt, jobb kattintás visszavonja az utolsót.
6. A `Tervezés vége` memóriarétegként lezárja a vonalat. A réteg attribútumai:
   `gradient_pct`, `step_m`, `segments`, `length_m`.

Az aktív munkamenetben a kezdő- és célpont térképi célkereszttel, a célpont
toleranciája pedig ideiglenes körrel látszik. Lezárás után ezek eltűnnek, csak
a 2 mm-es vörös szaggatott eredményvonal marad. A koordinátamezőkben a projekt
CRS szerinti `X; Y` érték kézzel is megadható; a hozzá tartozó Z értéket a
plugin azonnal B-spline-nal újramintavételezi.

## Matematikai feltétel

Minden lépésnél a program a `r = lépéshossz` sugarú körön keresi a
`DEM(x, y) = z_aktuális + r × meredekség / 100` egyenlet összes gyökét.
Az előjelváltó gyököket felezéssel, az érintő gyököket lokális minimumkereséssel
finomítja. A gyök elfogadásának numerikus magassági hibahatára 5×10⁻⁶ m.

## Korlátok

- A DEM szélétől két képpontnyi sávban a 4×4 B-spline kernel nem mintázható.
- A gyökfelderítés 1°-os kezdeti szögmintát használ, majd finomít. Rendkívül
  keskeny, két minta közé eső gyökpár elméletileg kimaradhat.
- Az önmetszés, éles törés és cikcakk figyelmeztetés; a meredekségileg helyes
  irányt a hallgató ettől még választhatja.
