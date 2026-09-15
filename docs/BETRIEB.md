# Betrieb, Sicherung und Rückkehr

## Version und Installation

TankData 0.2.0 unterstützt Home Assistant 2026.9.2 und Python ab 3.14.2.
Installation über HACS als benutzerdefiniertes Repository der Kategorie Integration
oder manuell gemäß README. Das Dashboard ist Bestandteil desselben Pakets.

## Konfiguration und Speicherung

Ein Tank ist ein Config Entry mit eigenem Gerät. Verbraucher sind native Subentries.
Die gemeinsame Oberfläche ist in der HA-Seitenleiste unter TankData erreichbar.
Der Verwaltungsbereich benötigt einen Administrator. Sensoren und Actions bleiben
auch unabhängig davon nutzbar.

Config Entry v1 und Store v1, Minor 1 bleiben bestehen. Historie und Quellenbasis
liegen in `.storage/ha_tankdata.<entry_id>`. Die Sensorhistorie ersetzt diesen Store
nicht. Entfernen eines Verbrauchers oder Tanks löscht die Ledgerdatei nicht.
Die Kapazität und der Initialbestand sind die feste Basis des Ledgers.

## Sicherung und Aktualisierung

1. Vor einer Aktualisierung ein vollständiges HA-Backup erstellen und die
   erfolgreiche Fertigstellung prüfen.
2. Integration und zugehörige Config-/Device-/Entity-Registries sowie TankData-Stores
   als zusammengehörigen Stand erhalten. Sicherungen enthalten vertrauliche Daten.
3. Das neue Integrationspaket installieren, HA neu starten und Geräte, Bestand,
   Verbraucher sowie Logs prüfen.
4. Ein Rückkehrtest gehört in eine isolierte Instanz. Eine produktive Rückkehr
   verwendet einen vollständigen passenden Sicherungsstand, nicht einzelne alte
   Dateien mit neuerer Konfiguration.

0.2.0 verwendet vorhandene Tanks und Ereignisse weiter. Keine Löschung des Stores
oder Neueinrichtung bestehender Tanks nötig. Alte Versionsnummern im Store sind
keine Zusage, dass ältere Integrationsversionen neuere Konfiguration verstehen.

## Fachliche Grenzen

- Prozent beziehen sich auf Volumen. Keine geometrische Umrechnung von Füllhöhen.
- Ein angenommener Durchsatz liefert geschätzten, nicht gemessenen Verbrauch.
- Änderungen am Verbraucherdurchsatz wirken auf neue Intervalle. Historie bleibt
  erhalten. Gemessene Bestände als Beobachtung und bei Bedarf Korrektur buchen.
- Bei unbekannten Quellen, überlangen Lücken und Neustart wird fehlende Laufzeit
  nicht ergänzt. Verbraucheränderungen lösen Reload aus und setzen die Zeitbasis neu.
- Zeitquellen werden bei Meldungen und alle 30 Sekunden abgerechnet. Die letzte
  Meldung wird durch den Timer nicht künstlich verlängert.
- Zählerverbrauch wird erst beim nächsten Zählerstand bekannt. Ohne Zwischenstand
  lässt sich ein Intervall über eine manuelle Korrektur nicht zeitlich aufteilen.
- Das vollständige Ledger wächst mit der Historie. Keine automatische Archivierung
  oder Komprimierung; keine Kosten, Prognosen oder automatische Kalibrierung.

## Reproduzierbare Prüfung

`uv sync --group dev --locked`, `uv run pytest -q`,
`uv run ruff check custom_components tests scripts` und
`uv run ruff format --check custom_components tests scripts`.

Die HA-Prozesstests verwenden das offizielle Image
`ghcr.io/home-assistant/home-assistant:2026.9.2`. Projekt und Integration werden
schreibgeschützt nach `/work` beziehungsweise `/config/custom_components`
eingebunden, ein ausschließlich für Tests angelegtes Verzeichnis nach `/config`.
Niemals die produktive Konfiguration als Testverzeichnis verwenden.

- `scripts/ha_acceptance.py`: manuelle Buchungen und Wiederanlauf.
- `scripts/ha_sources_acceptance.py`: vier Quellen, echte Timer und gemischte Aktionen.
- `scripts/ha_restart_acceptance.py`: neuer Prozess, unveränderte Ledger und korrekte
  Geräte-/Entity-Zuordnung. Quellenabnahmen erzeugen jeweils einen weiteren Testtank.

`scripts/build_release.py` baut das Paket ausschließlich aus Integrationsdateien,
HACS-Metadaten und öffentlicher Dokumentation. Zugangsdaten und private Betriebsdaten
werden nicht eingepackt.
