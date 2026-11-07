# TAOS

Ein Steam-Achievement-Manager für Windows. TAOS liest den echten lokalen
Fortschritt aus den Steam-Cachedateien und schreibt Änderungen über die
Steamworks-API zurück. Kein Web-Login, kein API-Key nötig – Steam muss nur
laufen.

## Was es kann

- Spielebibliothek aus installierten Manifesten, lokalen Caches und optional
  der Steam-Web-API aufbauen
- Achievements einzeln oder komplett freischalten bzw. sperren
- Original-Backup pro Steam-Account, automatisch beim ersten Scan
- „Reset to Original“ stellt exakt den gespeicherten Zustand wieder her
- Live-Suche nach Spielen mit Teilnamen, Bild und Fortschritt
- Schneller Start durch einen kleinen Fortschritts-Cache

## Start

```powershell
.venv\Scripts\python.exe main.py
```

Alternativ `run.bat` doppelklicken. Benötigt Python 3.10+ und die Pakete aus
`requirements.txt`.

## Live-Modus

TAOS sucht automatisch nach einer passenden `steam_api64.dll` in den
installierten Steam-Spielen. Wenn du eine bestimmte DLL verwenden willst,
kannst du sie unter `assets/steam_api64.dll` ablegen. Die DLL gehört nicht ins
Repository.

Vor dem Schreiben:

- Steam muss laufen und eingeloggt sein.
- Das Spiel sollte geschlossen sein.
- Das Backup muss geschrieben werden können; sonst bricht TAOS den
  Schreibvorgang ab.

Steam braucht nach dem Setzen manchmal ein paar Sekunden, bis die Anzeige
aktualisiert ist.

## Backup

Beim ersten vollständigen Scan wird für jedes Spiel mit Achievement-Daten der
aktuelle Stand gesichert:

```
taos_initial_snapshot_<SteamID64>.json
```

Das Backup wird durch Unlock, Lock oder einzelne Toggles nicht verändert. Vor
dem ersten Schreibzugriff auf ein Spiel ohne Backup liest TAOS den aktuellen
Stand ein und sichert ihn zuerst. Ein altes, account-loses Backup wird beim
ersten Start automatisch übernommen.

Wichtig: „Reset to Original“ ist ein echter Reset auf den Stand des Backups.
Achievements, die du danach regulär verdient hast, werden dabei ebenfalls
entfernt. Das steht auch im Bestätigungsdialog.

## Bekannte Grenzen

- Windows-only (Registry, `tasklist`, `steam_api64.dll`).
- Achievements, die erst nach dem Backup durch DLC dazukommen, sind nicht im
  Backup enthalten.
- Manche Spiele behandeln Achievements serverseitig; dort kann ein Schreib-
  vorgang fehlschlagen. TAOS meldet das dann pro Spiel.
- Die lokale Steam-Cache-Datei kann minimal hinterherhängen. Wenn ein Spiel
  noch nie gestartet wurde, greift TAOS auf Live-/Online-Daten zurück.

## Aufbau

```
main.py               Einstiegspunkt
html.html             Oberfläche
taos/
  config.py           Pfade und Konstanten
  engine.py           Bibliothek, Achievements, Schreibvorgänge
  bridge.py           JS-API
  worker.py           Steamworks-Subprozess
  data/               Backups und Caches
  steam/              Steam-Dateien und Web-API
```

## Vor dem Veröffentlichen

`taos_initial_snapshot*.json`, `taos_appnames_cache.json` und
`taos_progress_cache.json` enthalten persönliche Bibliotheksdaten und sind in
`.gitignore` eingetragen. Die Steamworks-DLL wird nicht mitgeliefert.

Achievements freizuschalten kann gegen Steam- oder Spielregeln verstoßen.
Nutzung auf eigene Verantwortung.

## Lizenz

MIT

