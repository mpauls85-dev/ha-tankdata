# Architektur und Fachentscheidungen

## Verbindliche Grundlage

Ein Tank je Config Entry, Verbraucher als native Subentries, Liter als kanonische
Volumeneinheit. Zielversion durch lesenden API-Aufruf bestätigt: HA **2026.9.2**.
Python-Anforderung dieser Version: >=3.14.2 (offizielle PyPI-Metadaten).
API-Prüfung am offiziellen Quellstand:
https://github.com/home-assistant/core/tree/2026.9.2/homeassistant
Insbesondere `config_entries.py`, `helpers/storage.py`, `components/sensor`.
Ergänzende Dokumentation:
https://developers.home-assistant.io/docs/core/integration/config_flow/
https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/runtime-data/

## Geräteprofil-Referenz

Arbeitsmappe v0.1 lesend ausgewertet: 266 Profile, darunter 59 mit l/h,
83 mit m³/h, 123 mit kg/h und eines ohne Einheit. Die Raten sind angenommene
Startwerte aus Wärmeleistung, Heizwert und Wirkungsgrad. Sie sind keine Messungen.
Massebasierte Modelle und automatische Profilkalibrierung widersprechen dem MVP.
Deshalb keine automatische Profilübernahme: Nutzer konfigurieren einen belegten
Durchsatz in l/h. Herstellerkatalog, Verzögerungen und automatische Kalibrierung
bleiben mögliche spätere Erweiterungen.

## Ereignisse und Grenzen

- Initialbestand wird ausdrücklich bei der Einrichtung angegeben (0 zulässig).
- Beobachtung dokumentiert einen realen Messwert, verändert den Bestand nicht.
- Korrektur setzt den Bestand absolut auf einen gemessenen Literwert.
- Befüllung/Entnahme verändern ihn um eine nicht negative Literzahl (0 als protokollierte Nullbuchung).
- Reset deaktiviert die Wirkung aller davor gebuchten Korrekturen; Ereignisse
  bleiben erhalten. Er setzt weder Verbrauch noch reale Beobachtungen zurück.
- Rekalkulation spielt das unveränderte Ledger erneut ab.
- UTC-Zeitstempel, stabile Buchungsreihenfolge bei gleichem Zeitpunkt.
- Keine rückdatierten manuellen Buchungen im MVP. Verspätete Quelldaten werden
  verworfen; Herkunftszeit bleibt bei Verbrauchsdaten erhalten.
- Manuelle Ereignis-ID ist optional: gleiche ID und gleicher Inhalt sind
  idempotent; abweichender Inhalt bei gleicher ID wird abgelehnt. Ohne ID ist
  jeder Aufruf eine neue Buchung.
- Manuelle Volumina müssen innerhalb 0/Kapazität liegen; eine Buchung, deren
  resultierender Bestand Grenzen verletzt, wird abgelehnt. Automatischer Verbrauch
  bleibt auch bei negativem rechnerischem Bestand vollständig erhalten; Sensoren
  zeigen den tatsächlichen Rechenwert und ein Grenzwertattribut statt zu kappen.

## Persistenz

Store v1 je Entry: Kapazität, Initialbestand, unveränderte Ereignisse sowie
Quellenbasis. Daten werden vor Verwendung vollständig validiert. Keine erfundene
Altformatmigration; unbekannte Versionen werden abgewiesen. Eine Sperre serialisiert
Buchungen und Quellenupdates. Erst nach erfolgreichem unmittelbarem Speichern wird
der sichtbare Laufzeitzustand ersetzt. Historie bleibt auch beim Entfernen eines
Verbrauchers und beim Löschen des Config Entry auf Datenträger erhalten.

## Verbrauch (für Phasen 4–7)

Zähler: Liter oder m³; Differenz zwischen gültigen Messungen. Negativer Sprung,
Ausfall oder Überschreitung der konfigurierten maximalen Rate setzen eine neue
Basis ohne Verbrauch. Basis über Neustart nur bei identischer Konfiguration und
innerhalb konfigurierter maximaler Zeitlücke verwenden.

Zeitquellen: linkes Rechteck (vorheriger gültiger Wert × Zeit). Durchfluss l/min,
l/h oder m³/h. Betrieb on/off; Leistung W/kW mit Ein-Schwelle > Aus-Schwelle,
an bei >= Ein, aus bei <= Aus. Initial im Zwischenbereich unbekannt.
Unbekannt/unavailable und überlange Lücken werden nicht integriert. Neustart oder
Konfigurationswechsel startet Zeitbasis neu. Laufende Zustände werden periodisch
abgerechnet, höchstens bis zur Gültigkeitsgrenze der letzten Quellenmeldung.
Jede Verbrauchsbuchung erhält Eingangsgrößen, Intervall und Konfigurationssnapshot,
damit spätere Konfigurationsänderungen historische Berechnungen nicht umdeuten.


## Ergänzungen aus der Gesamtabnahme

- Laufende gültige Zeitintervalle werden vor manuellen Buchungen zusammen mit dem
  manuellen Ereignis atomar gespeichert. So wird Verbrauch vor einer Korrektur
  nicht erst danach vom korrigierten Bestand abgezogen.
- Zählerverbrauch wird dem Eingang der Folgemeldung zugeordnet. Ohne zusätzlichen
  Zählerstand zum Korrekturzeitpunkt lässt sich ein dazwischenliegendes Intervall
  nicht aufteilen. Diese Einschränkung ist in BETRIEB.md beschrieben.
- HA-Store-Schreibfehler werden durch anschließendes direktes Lesen erkannt.
  Beschädigte JSON-Dateien werden bereits vor dem allgemeinen HA-Ladepfad abgewiesen.
- Rohwert/Einheit, normalisierte Eingangsgrößen, Start/Ende und Konfiguration werden
  in neuen Verbrauchsbuchungen aufbewahrt. Alte Buchungen ohne zusätzliche Rohfelder
  bleiben gültig; ihre damals gespeicherten numerischen Eingänge reichen für die
  Überprüfung der Mengen. Unbekannte Berechnungsarten werden nicht interpretiert.
- Quellenqualität wird alle 30 Sekunden aktualisiert, auch bei unveränderten
  Zählerständen. Unbekannte Zeitquellen erzeugen keine wiederholten Leerschreibungen.
- Config-/Storeversion 1 blieb bestehen. Frühere reale Teststände aus Phase 3/4
  stehen unter tests/fixtures und werden ohne Datenänderung geladen. Sie stammen
  ausschließlich aus isolierten Testtanks, nicht aus der produktiven Instanz.
- Die unveränderte Versionsnummer ist keine Zusage, dass alter Code neue
  Verbraucherarten versteht. Rückkehr immer mit passender Konfigurationssicherung.

- Abbruch eines Aufrufers wartet auf einen bereits laufenden Schreibvorgang, bevor
  die Transaktionssperre freigegeben wird. Ein unklar bestätigtes manuelles Ereignis
  kann mit gleicher ID sicher wiederholt werden.
- Grenzprüfung toleriert ausschließlich Gleitkomma-Rundung (absolut 1e-9 Liter,
  relativ 1e-12 an der Kapazität); der berechnete Bestand wird nicht verändert.


## Gerätezuordnung ab 0.1.1

Jeder Tank besitzt ein Gerät am Haupt-Config-Entry. Jeder Verbraucher besitzt ein
separates Gerät an seinem Subentry, verbunden über `via_device_id` mit dem Tank.
Beim Laden wird die versehentliche Subentry-Zuordnung des Tankgeräts aus 0.1.0
über die explizite HA-Gerätemigration zurückgesetzt. Sensor-Unique-IDs und Ledger
bleiben unverändert. Gegen die tatsächlich installierte HA-2026.9.2-API geprüft.

## Mitgeliefertes Dashboard ab 0.2.0

Auf ausdrücklichen Nutzerwunsch: HACS-Kategorie Integration, HA-Integrationstyp
Device und eine gemeinsame Verwaltungsoberfläche in der Seitenleiste, funktional
am Bedienmodell von WashData orientiert. Auch die geprüfte WashData-Installation
verwendet einen Config Entry je Gerät; das bestehende Tankmodell bleibt erhalten.

Das Panel nutzt HA Custom Panel und gebündeltes JavaScript ohne CDN, separaten
Webserver oder weitere Frontendinstallation. Tankgeräte sind normale Geräte;
IDs und Ledger bleiben bei der Umstellung erhalten. Verbraucher behalten native
Subentries und ihre bisherige Gerätezuordnung.

Lesende WebSocket-Befehle liefern Tankübersicht und begrenzte Historienseiten.
Sie benötigen wie das Verwaltungs-Panel Administratorrechte. Konfiguration läuft
über die vorhandenen nativen Config Flows, Buchungen über die vorhandenen Actions.
Kein paralleles Datenmodell. Historienseiten nutzen eine feste Ereignisposition,
damit später angehängte Ereignisse ältere Seiten nicht verschieben.

Statische Ressourcen und API werden einmal je HA-Prozess registriert. Entfernen
des letzten Tanks entfernt den Panel-Eintrag; ein neuer Tank registriert ihn wieder.
Deaktivierte Tanks bleiben als solche sichtbar. Versionsparameter im Modulpfad
ermöglichen die Aktualisierung der Browserressourcen nach einem Releasewechsel.
