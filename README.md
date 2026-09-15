# TankData

Home-Assistant-Integration für Tankbestände, Verbrauch und ein nachvollziehbares
Ereignisprotokoll. Mit eigenem **TankData-Dashboard** in der Seitenleiste.
Jeder Tank ist ein Gerät; mehrere Tanks erscheinen gemeinsam in der Oberfläche.

## Installation

Version **0.3.0**. HACS-Kategorie: **Integration**.

### Über HACS

1. In HACS das Menü **Benutzerdefinierte Repositories** öffnen.
2. `https://github.com/mpauls85-dev/ha-tankdata` hinzufügen, Typ **Integration**.
3. **TankData** herunterladen und Home Assistant neu starten.
4. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen → TankData**
   den ersten Tank anlegen. Danach erscheint **TankData** in der Seitenleiste.

Das Dashboard wird mit der Integration installiert; eine zusätzliche Karte oder
manuell angelegte Dashboard-Ressource ist nicht erforderlich. TankData ist ein
benutzerdefiniertes HACS-Repository, keine Zusage einer HACS-Standardlistung.

### Manuell

Getestete Zielversion: Home Assistant 2026.9.2, Python >=3.14.2.
`custom_components/ha_tankdata` in das gleichnamige Verzeichnis der HA-Konfiguration kopieren und HA neu starten. Unter Einstellungen → Geräte & Dienste → Integration hinzufügen → TankData einen Tank anlegen. Jeder weitere Tank ist ein eigener Eintrag.

Name, Kapazität und Initialbestand in Litern angeben. Initialbestand 0 ist zulässig. Kapazität und Initialbestand sind die unveränderliche Ledgerbasis. Einen tatsächlichen neuen Bestand über die Korrektur-Action buchen. Den Anzeigenamen kann Home Assistant umbenennen.

## TankData-Dashboard

Die gemeinsame Verwaltungsoberfläche ist für HA-Administratoren verfügbar:

- Übersicht aller Tanks mit Litern, Prozent und Kapazität;
- weitere Tanks als Geräte anlegen;
- Verbraucher hinzufügen, bearbeiten und entfernen;
- kompakte Bestandskarte mit isometrischer Tankgrafik und den Aktionen **Befüllen** und **Bestand korrigieren**;
- Tankgerät direkt über den Kopfbereich öffnen; neue Tanks nur in der Übersicht hinzufügen;
- Historie mit älteren Ereignissen laden und direkt zum Tankgerät wechseln.

Die Anzeige aktualisiert sich alle 15 Sekunden; offene Eingaben werden dabei
nicht überschrieben. Buchungswiederholungen nach Verbindungsfehlern verwenden
dieselbe Ereignis-ID. Außerhalb der Oberfläche stehen die normalen HA-Actions
und Sensoren weiterhin zur Verfügung.

### Aktualisierung von 0.1.x / 0.2.x

Bestehende Tanks werden weiterverwendet. Geräte- und Entity-IDs sowie Ledger
bleiben erhalten; weder Neueinrichtung noch Löschen der Historie ist erforderlich.
Die bisherigen Verbraucher-Untereinträge werden beim Laden automatisch in eigene Einträge umgewandelt. Der zugeordnete Tank und die Buchungshistorie bleiben erhalten. Deaktivierte Tanks werden erst beim erneuten Aktivieren migriert. Vor Updates die HA-Konfiguration und die TankData-Stores sichern.

## Verbraucher einrichten

Unter **Integration hinzufügen → TankData → Verbraucher** einen Verbraucher anlegen und seinen Tank auswählen. Tanks und Verbraucher erscheinen als eigene, flache Einträge unter Geräte & Dienste. Im TankData-Dashboard kann der Verbraucher weiterhin direkt beim Tank angelegt werden. Mehrere Verbraucher und mehrere Tanks sind möglich. Eine Quelle, die mehrfach demselben Tank zugeordnet wird, zählt entsprechend mehrfach; nur tatsächlich getrennte Verbräuche zuordnen.

| Quelle | Eingang | Weitere Parameter |
| --- | --- | --- |
| Kumulativer Zähler (`counter`) | Sensor mit L, l oder m³ | Maximale Datenlücke und maximal plausible Rate |
| Durchfluss (`flow`) | Sensor mit L/h, l/h, L/min, l/min oder m³/h | Maximale Datenlücke und maximal plausible Rate |
| Laufzustand (`running`) | on/off einer Sensor-, Binary-Sensor-, Switch- oder Input-Boolean-Entity | Durchsatz `rate_lph` |
| Elektrische Leistung (`power`) | Sensor mit W oder kW | Durchsatz `rate_lph`, `on_threshold_w`, `off_threshold_w` |

`max_gap_seconds` ist eine positive Zeit in Sekunden (Vorgabe 3600). Sie begrenzt die Gültigkeit der letzten Meldung und die zulässige Zählerlücke. `max_rate_lph` ist die maximal plausible Rate in l/h (Vorgabe 100). Raten darüber werden nicht als Verbrauch gebucht. Für Laufzustand und Leistung ist `rate_lph` positiv und höchstens `max_rate_lph`. Leistung: Ein-Schwelle muss größer als Aus-Schwelle sein; ab Ein-Schwelle an, bis Aus-Schwelle aus. Dazwischen bleibt der bekannte Zustand erhalten, anfangs ist er unbekannt.

Durchfluss wird mit dem vorherigen gültigen Wert über die Zeit integriert. Laufzustand und Leistung nutzen dieselbe Berechnung mit dem konfigurierten Durchsatz. Abrechnung bei Quellenmeldungen und alle 30 Sekunden. Timer verlängern die Gültigkeit alter Meldungen nicht. Bei unknown/unavailable, ungültiger Einheit, überlanger Lücke oder Neustart entsteht kein geschätzter Zeitverbrauch. Ein Zählerreset oder unplausibler Sprung beginnt eine neue Basis. Eine beim Start noch fehlende Zähler-Entity überschreibt die gespeicherte Basis nicht.

Verbraucher über **Neu konfigurieren** ändern. Änderungen wirken ab neuer Berechnungsbasis und schreiben historische Ereignisse nicht um. Entfernen erhält die Historie. Die Geräteprofil-Arbeitsmappe ist eine Referenz; ihre angenommenen Raten werden nicht automatisch übernommen.

## Sensoren

Tank und Verbraucher besitzen eigene, miteinander verknüpfte HA-Geräte. Version
0.1.1 korrigiert die Zuordnung aus 0.1.0 beim Laden; Ledger und eindeutige IDs bleiben erhalten.

Je Tank: Bestand (L), Füllstand (%) und kumulierter berechneter Verbrauch (L).
Je Verbraucher zusätzlich: kumulierter Verbrauch (L); bei Laufzustand und Leistung auch Laufzeit (h). Sensor-IDs werden von HA vergeben; ihre internen eindeutigen IDs bleiben bei Reload und Umbenennung stabil.

`out_of_bounds` zeigt rechnerische Grenzverletzungen; `event_count` die Zahl der Ereignisse. `incomplete_sources` zählt aktuell ungültige oder veraltete Quellen. Verbrauchersensoren zeigen `source_valid` und `last_source_report`. Automatischer Verbrauch wird nicht an der Tankgrenze abgeschnitten. Bestand und kumulierter Verbrauch bleiben bei Quellenausfall sichtbar; nicht beobachtete Zeiträume können fehlen.

## Actions

Alle Actions beginnen mit `ha_tankdata.` und benötigen `config_entry_id` (Tank im Action-Editor auswählen).

| Action | Parameter | Wirkung |
| --- | --- | --- |
| record_observation | liters, optional event_id | Messung dokumentieren, Bestand unverändert |
| record_refill | liters, optional event_id | Liter hinzufügen |
| record_withdrawal | liters, optional event_id | Liter entnehmen |
| apply_correction | liters, optional event_id | Absoluten Bestand setzen |
| recalculate | keine weiteren | Unveränderte Historie neu auswerten |
| reset_calibration | optional event_id | Wirkung bisheriger Korrekturen aufheben; Historie erhalten |

Literwerte müssen endlich und nicht negativ sein. Manuelle Buchungen dürfen keinen Bestand außerhalb 0/Kapazität erzeugen. Gleiche `event_id` mit gleichen Parametern bucht nur einmal; abweichende Parameter werden abgewiesen. Ohne ID ist jeder Aufruf eine neue Buchung. Keine rückdatierten Buchungen.

```yaml
action: ha_tankdata.record_refill
data:
  config_entry_id: DEINE_TANK_ENTRY_ID
  liters: 200
  event_id: lieferung-2026-09-15
```

## Speicherung und Entwicklung

Historie: `.storage/ha_tankdata.<entry_id>` (Store v2; vorhandene v1-Daten werden beim Laden verlustfrei ergänzt). Beschädigte oder unbekannte Versionen werden nicht überschrieben. Buchungen werden erst nach bestätigtem Speichern angezeigt. Das Entfernen eines Eintrags löscht seine Historiedatei nicht.

Tests: `uv sync --group dev --locked`, `uv run pytest`, `uv run ruff check custom_components tests scripts`.

Vor einem Update die HA-Konfiguration einschließlich der TankData-Stores sichern.
Bei einer Rückkehr zur vorherigen Version die passende Sicherung verwenden.

## Funktionen ab 0.3.0

Version 0.3.0 erweitert TankData um:

- **Tankgeometrie:** Quader, stehender und liegender Zylinder, Kugel sowie eine
  eigene Peiltabelle. Die Grafik zeigt die aus dem Volumen berechnete Füllhöhe;
  die Tanks werden isometrisch mit sichtbarer Flüssigkeitsoberfläche dargestellt. Kapazität bleibt maßgeblich.
  Ideale Formen berücksichtigen keine gewölbten Tankböden; dafür Peiltabelle nutzen.
- **Messumrechnung:** Intern werden Liter, Volumenprozent und Füllhöhe in cm unterstützt.
  Die regulären HA-Actions und der Korrekturdialog verwenden Liter. Für cm die innere Höhe
  beziehungsweise den Durchmesser hinterlegen. Peiltabelle: je Zeile `cm;Liter`,
  streng steigend von `0;0` bis Tankhöhe/Kapazität. Messung allein korrigiert den
  berechneten Bestand nicht.
- **Kosten:** Optionaler Gesamtpreis je neuer Befüllung und Preis des Initialbestands
  in EUR/L. Verbrauchskosten und Bestandswert verwenden einen gleitenden gewichteten
  Mischpreis. Fehlende Preise bleiben unbekannt; 0 EUR ist ein gültiger Preis.
  Lieferausgaben und Verbrauchskosten werden getrennt gezeigt. Ein geänderter
  Initialpreis aktualisiert auch die darauf beruhende Kostenhistorie.
- **Statistik:** Heute sowie 7, 30 und 365 Tage, Tagesbalken, Tageswerte,
  Verbrauch je Verbraucher, Laufzeit, Kosten und Datenabdeckung. Abdeckung ist erst
  seit dieser Erweiterung verfügbar; frühere Lücken werden nicht als Nullverbrauch
  interpretiert. Zeitbasierter Verbrauch wird auf lokale Kalendertage aufgeteilt.
- **Prognosen:** Mittelwert vollständiger Tage aus den letzten 30 Tagen, mindestens
  sieben vollständige aktuelle Tage. Anzeige für 7/30 Tage, Reserve und Leerstand.
  Die Schwankungsspanne ist keine statistisch garantierte Vorhersage. Ohne aktuelle
  belastbare Daten oder bei Nullverbrauch gibt es kein scheinbar genaues Leerdatum.
  Wetter und Saisonalität werden in dieser ersten Fassung nicht modelliert.
- **Betriebszustand:** An/Aus/Unbekannt im Dashboard und als HA-Binary-Sensor bei
  Laufzustand, Leistung und Durchfluss. Ein kumulativer Zähler beweist keinen
  aktuellen Betriebszustand. Quellenausfall bedeutet unbekannt, nicht ausgeschaltet.
- **Kalibrierung mit Bestätigung:** Zwei reale Beobachtungen, mindestens 24 Stunden
  Abstand, mindestens eine Stunde erfasste Laufzeit, mindestens 99 % Datenabdeckung
  und eindeutig ein Verbraucher mit konfiguriertem Durchsatz sind erforderlich.
  Befüllungen und manuelle Entnahmen werden berücksichtigt. Korrekturen, wechselnde
  Parameter, weitere Verbraucher und wesentliche Datenlücken verhindern Vorschläge.
  Die gemessene Entnahme muss über dem Zwanzigfachen der eingestellten Messunsicherheit
  liegen. Vorschläge werden auf 2–20 % Änderung und die plausible Maximalrate begrenzt.
  Dashboard und HA-Mitteilung fordern zur Prüfung auf: **Wert übernehmen / Ablehnen /
  Später**. Erst Bestätigung ändert den tatsächlichen Durchsatz in L/h. Altwert,
  Neuwert, Evidenz und Bestätigung bleiben gespeichert. Historische Verbrauchswerte
  werden nicht umgeschrieben. Keine versteckten Korrekturfaktoren.

Die zusätzlichen Einstellungen befinden sich beim Tank unter **Einstellungen**.
Im Dashboard stehen **Befüllen** (mit optionalem Preis) und **Bestand korrigieren**
zur Verfügung. Messbeobachtungen für die Kalibrierung werden über die HA-Action
`ha_tankdata.record_observation` in Litern erfasst. Die weiteren bestehenden
HA-Actions bleiben kompatibel. Massemodelle und Temperaturkompensation sind
nicht enthalten. Geschätzte Durchsätze sind keine Brennstoffmessungen.

Zugangsdaten und lokale Betriebsdaten bleiben außerhalb der Versionsverwaltung.
