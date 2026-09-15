# Projektfortschritt TankData

Aktualisiert: 2026-09-15

## Aktueller Stand

Version 0.2.0 erweitert die Integration um ein mitgeliefertes Verwaltungsdashboard
und die HACS-Paketstruktur. Jeder Tank bleibt ein Config Entry mit eigenem Gerät;
Verbraucher bleiben native Subentries. Config- und Storeversion bleiben unverändert.

## Abgeschlossene Grundlagen

- Phasen 1–8: Config Flow, mehrere Tanks, persistentes Ledger, manuelle Buchungen,
  vier Verbrauchsquellen, Rekalkulation, Reload und Wiederanlauf.
- Version 0.1.1: getrennte Verbrauchergeräte und Migration der Gerätezuordnung;
  stabile Entity-IDs und erhaltene Historien.
- Kontrollierte produktive Einrichtung und Neustart geprüft. Der Test mit einem
  tatsächlichen Brennerlauf steht aus, solange die Heizung ausgeschaltet ist.
  Private Betriebsparameter und Messprotokolle werden nicht veröffentlicht.

## Dashboard und HACS

- Gemeinsames TankData-Panel, Tankgeräte, Konfiguration von Verbrauchern,
  Buchungsdialoge und seitenweise Historie.
- Verwaltungszugriff nur für Administratoren; bestehende HA-Actions werden
  verwendet. Keine zweite Persistenz und kein externer Server.
- 63 lokale Tests bestanden, einschließlich API-Zugriffsschutz, getrennten
  Tankhistorien, stabiler Historienseiten trotz neuer Buchungen und Panel-Lebenszyklus.
- Echte HA-2026.9.2-Dockerabnahme: alle vier Quellen, Timer und manuelle Ereignisse;
  neuer Prozess mit neun Testtanks bestätigt Ledger, Entities und Gerätezuordnung.
- Browserbedienung in einer separaten HA-Testinstanz geprüft: Tanks anlegen,
  Befüllung buchen und Verbraucher anlegen und ändern.
- Die Linux-Prüfstrecke für GitHub besteht ebenfalls alle 63 Tests sowie Ruff
  und den Paketbau. Veröffentlichung als benutzerdefiniertes HACS-Repository.

Detaillierte interne Entwicklungsprotokolle und produktive Konfigurationen bleiben
im lokalen Arbeitsbereich. Öffentliche Testfixtures stammen ausschließlich aus
isolierten Testtanks.
