# Entwicklungsplan TankData

Stand: 2026-09-15. Grundlage: `AGENTS.md` und Bestandsaufnahme des Projektverzeichnisses.

## Ausgangslage und Ziel

Vorhanden sind `AGENTS.md`, eine Geräteprofil-Arbeitsmappe und lokale Zugangsdateien unter `resources/`. Implementierung, Tests, Entwicklungsumgebung und Git-Repository fehlen. Die Referenzinhalte und HA-Zielversion sind noch nicht fachlich beziehungsweise technisch geprüft; daraus werden hier keine zusätzlichen Anforderungen abgeleitet.

Ziel ist ein lokal entwickeltes, getestetes MVP, das anschließend kontrolliert in der realen HA-Instanz geprüft wird. Die folgende Reihenfolge ist der Umsetzungsplan. Dieser Planungsauftrag implementiert noch keine der Entwicklungsphasen.

## Vorgehen und Fortschritt

1. Phasen sequenziell abarbeiten. Jede Phase liefert einen eigenständig prüfbaren Zwischenstand und baut auf den abgeschlossenen Vorgängern auf.
2. Vor Beginn Arbeitsregeln, Fortschritt, relevante Entscheidungen, Code, Tests und Nutzeränderungen lesen. Konkrete Arbeitspunkte der Phase im Fortschrittsdokument festhalten.
3. Offene fachliche Regeln vor ihrer Implementierung anhand der Projektquellen eingrenzen. Nur nicht selbst ermittelbare, ergebnisrelevante Fragen an den Nutzer richten.
4. Implementieren, passende Tests ausführen, Fehler beheben und Dokumentation aktualisieren. HA-spezifische Änderungen zusätzlich in einer geeigneten HA-Umgebung laden und prüfen.
5. Prüfergebnisse mit Datum, Umgebung/Version, ausgeführten Prüfungen und tatsächlichem Ergebnis in `FORTSCHRITT.md` dokumentieren. Ausstehende reale Prüfungen bleiben sichtbar.
6. Änderungen prüfen und eine abgeschlossene Phase in einem thematisch passenden lokalen Commit sichern, sobald Git eingerichtet ist. Keine Zugangsdaten aufnehmen. Veröffentlichung ist kein automatischer Bestandteil.
7. Status nur bei erfüllten Abnahmekriterien auf „abgeschlossen“ setzen. Bei Unterbrechung den letzten belastbaren Stand und den nächsten konkreten Schritt festhalten.

Statuswerte: **geplant**, **in Arbeit**, **blockiert**, **abgeschlossen**. Ein Blocker enthält Ursache und benötigte Auflösung. Abhängige Arbeiten warten; unabhängige Arbeit innerhalb der Phase kann weitergehen.

Wesentliche technische und fachliche Entscheidungen werden während ihrer Klärung gesammelt in `docs/ARCHITEKTUR.md` dokumentiert. Diese Datei wird erst angelegt, wenn konkrete Entscheidungen vorliegen. Sie unterscheidet bestätigte Vorgaben, getroffene Entscheidungen und offene Fragen.

## Phase 0 – Bestandsaufnahme und Planung

**Ergebnis:** nachvollziehbare Roadmap und dauerhaftes Fortschrittsprotokoll.

- Arbeitsregeln und Dateibestand prüfen.
- Phasen, Abhängigkeiten, Abnahme und Dokumentationsverfahren festlegen.
- README als ehrlichen Einstieg in den aktuellen Projektstand anlegen.

**Abnahme:** Plan und Fortschritt sind verlinkt; fehlende Implementierung und ungeprüfte Umgebung sind ausdrücklich sichtbar.

## Phase 1 – Entwicklungsbasis und verbindliche Fachentscheidungen

**Ergebnis:** reproduzierbare Testumgebung und geklärte Grundlagen für das erste Datenmodell.

- Geräteprofil-Arbeitsmappe auswerten und relevante Anforderungen mit `AGENTS.md` abgleichen.
- Tatsächliche HA-Version und erreichbare Entwicklungs-/Testumgebung ermitteln. Lokale Zugänge nur zweckgebunden nutzen und nicht dokumentieren oder versionieren.
- Versionsabhängige Config-Entry-, Subentry-, Runtime- und Store-Schnittstellen anhand der passenden offiziellen HA-Quellen prüfen; Quellen und unterstützte Version dokumentieren.
- Git und sichere Ausschlussregeln für Zugangsdaten, lokale Umgebungen und Laufzeitdaten einrichten; vor dem ersten Commit die vorgesehene Dateiliste prüfen.
- Einfache Projekt- und Teststruktur sowie passende Python-/HA-Abhängigkeiten und Prüfwerkzeuge einrichten. Falls HA lokal nicht ausführbar ist, eine geeignete Testumgebung festlegen.
- Fachregeln entscheiden: Initialbestand, Beobachtung gegenüber Korrektur, Werte außerhalb 0/Kapazität, Ereignisreihenfolge, Zeitbasis, Wiederholung manueller Buchungen, Rekalkulation und Rücksetzung der Korrekturbasis.
- Festlegen, welche Eingangsdaten und Konfigurationsstände für spätere reproduzierbare Rekalkulation erhalten bleiben müssen. Änderungen eines Verbrauchers dürfen frühere Zeiträume nicht stillschweigend umdeuten.

**Abnahme:** Testumgebung tatsächlich gestartet und eine aussagekräftige Basisprüfung ausgeführt; Zielversion und API-Kompatibilität belegt; fachliche Kernregeln dokumentiert; Git enthält keine lokalen Zugänge. Ungeklärte Fragen, die das Ledgerformat bestimmen, sind vor Phase 2 aufgelöst.

## Phase 2 – Tankmodell und Ereignisberechnung

**Ergebnis:** unabhängig von der HA-Oberfläche testbarer fachlicher Kern.

- Tankkapazität, Bestand und Prozentwert mit eindeutigen Einheiten modellieren.
- Initialisierung, Beobachtung, Befüllung, Entnahme, Korrektur und Verbrauch als nachvollziehbare Ereignisse abbilden.
- Deterministische Verarbeitung einschließlich Reihenfolge, Herkunft und Wiederholungsschutz implementieren.
- Grundlage für Rekalkulation und Rücksetzung entsprechend den Entscheidungen aus Phase 1 umsetzen; reale Ereignisse erhalten.

**Abnahme:** Tests für alle Ereignistypen, Grenzen, ungültige Werte, gleiche Zeitpunkte, doppelte Ereignisse und wiederholte Berechnung bestehen. Eine gemischte Ereignisfolge liefert den unabhängig erwarteten Bestand ohne Doppelbuchung oder versteckte Korrektur.

## Phase 3 – Persistenter, manuell nutzbarer Tank in Home Assistant

**Ergebnis:** erster vollständiger Nutzungsweg: Tank anlegen, manuell buchen, Bestand sehen und nach Neustart wiederherstellen.

- Integration unter `custom_components/ha_tankdata` mit Manifest, Config Flow und geeigneter Laufzeitzuordnung aufbauen.
- Mehrere Tanks, Kapazität und veränderbare Tankparameter sauber trennen.
- Versionierten HA-Store für Ledger und benötigte Berechnungsbasis integrieren; Speicherfehler und beschädigte/fremde Versionen sicher behandeln.
- Tank-Entities mit stabiler Identität und geprüfter HA-Semantik bereitstellen.
- Alle sechs vorgesehenen Actions anbinden; Parameter aus dem Fachmodell ableiten, validieren und dokumentieren.
- Nebenläufige Buchungen und Unterbrechungen beim Speichern berücksichtigen; erfolgreich bestätigte Ereignisse dürfen nicht unbemerkt verloren gehen.
- Installation, Tankeinrichtung, Entities und Actions in der README beschreiben.

**Abnahme:** lokale Fach- und HA-Integrationstests bestehen. In einer echten HA-Testumgebung funktionieren Einrichtung von zwei Tanks, isolierte Buchungen, alle Actions, Reload, Unload und Neustart mit unveränderter Historie. Storefehler, zukünftige Versionen und Änderungen bestehender Konfiguration sind getestet; Logs geprüft. Bei noch nicht vorhandenem Altformat wird kein historischer Migrationsfall erfunden.

## Phase 4 – Verbraucher mit kumulativem Zähler

**Ergebnis:** erster automatisch verbrauchender Tank mit mehreren Verbrauchern.

- Verbraucher als native Config Subentries anlegen, ändern und entfernen.
- Gemeinsame Verarbeitung von Eingangsgrößen und Verbrauchsbuchungen etablieren.
- Differenzbildung, Einheiten, Zählerreset/-sprung und veraltete/ungültige Werte behandeln.
- Wiederanlaufbasis persistent führen; Verhalten bei Quellenwechsel und Konfigurationsänderung definieren.
- Sinnvolle Verbrauchswerte als Entities darstellen; historische Buchungen beim Entfernen eines Verbrauchers erhalten.

**Abnahme:** normale und identische Folgemessung, Reset, Sprung, unbekannte/unverfügbare Werte, verspätete und doppelte Updates sowie Neustart zwischen Messungen getestet. HA-Test mit mehreren Verbrauchern und Tanks einschließlich Subentry-Änderung/-Löschung und Reload ohne doppelte Listener oder Buchungen bestanden.

## Phase 5 – Verbrauch aus Durchfluss

**Ergebnis:** Durchflusssensoren liefern nachvollziehbare zeitabhängige Verbrauchsbuchungen.

- Integrationsverfahren und Regeln für Gültigkeitsdauer, Zeitlücken und Abschluss laufender Intervalle dokumentieren.
- Durchfluss und Zeit mit eindeutigen Einheiten integrieren; gemeinsame Verbrauchsverarbeitung nutzen.
- Fehlende Daten, verspätete Updates und Neustarts ohne unbelegten Verbrauch behandeln.

**Abnahme:** konstante und wechselnde Durchflüsse, Nullwert, Zeitlücken, ungültige Einheiten, unavailable, verspätete Updates und Neustart getestet. Ein HA-Test bestätigt Mengen und Ledger anhand einer kontrollierten Eingangsfolge, einschließlich Reload.

## Phase 6 – Verbrauch aus Laufzustand

**Ergebnis:** ein Betriebssignal steuert Verbrauch und gegebenenfalls Laufzeit.

- Unterstützte Betriebszustände und konfigurierten Durchsatz validieren.
- Start/Stop und laufende Intervalle in die gemeinsame Berechnung einbinden.
- Änderungen des Durchsatzes zeitlich eindeutig behandeln; fehlende Betriebsdaten nicht als bekannte Laufzeit werten.

**Abnahme:** Start, Stop, mehrere Intervalle, längerer Betrieb ohne Zustandswechsel, unbekannter Zustand, Parameterwechsel und Neustart während des Betriebs getestet. HA-Test zeigt erwartete Menge und Laufzeit ohne Doppelzählung nach Reload.

## Phase 7 – Verbrauch aus elektrischer Leistung

**Ergebnis:** stabile Betriebserkennung mit Hysterese und daraus berechnetem Verbrauch.

- Ein-/Ausschaltschwellen mit gültiger Hysterese konfigurieren.
- Betriebserkennung auf die vorhandene Laufzustandsberechnung abbilden.
- Initialzustand im Hysteresebereich, Messrauschen, schnelle Wechsel und Ausfälle eindeutig behandeln.

**Abnahme:** unter/über Schwelle, exakte Grenzwerte, Werte im Hysteresebereich, schnelle Wechsel, unavailable und Neustart getestet. Kontrollierte HA-Messfolge bestätigt stabilen Zustand und erwarteten Verbrauch.

## Phase 8 – Gesamtabnahme, Upgrade und Betriebsdokumentation

**Ergebnis:** vollständig geprüftes MVP als Installationskandidat.

- Gemischte Szenarien mit mehreren Tanks und allen vier Verbraucherarten prüfen.
- Manuelle Ereignisse, Parameterwechsel, Verbraucherentfernung, Rekalkulation und Rücksetzung zusammen testen; reale Historie bleibt nachvollziehbar.
- Upgrade von den tatsächlich entstandenen früheren Config-/Store-Versionen ohne Historienverlust testen. Falls unverändert, Kompatibilität durch erneutes Laden des früheren Datenstands prüfen.
- Speicherfehler, beschädigte Daten, Wiederanlauf, Entity-Verfügbarkeit und Action-Lebenszyklus prüfen.
- README mit tatsächlichen Parametern, Einheiten, Entities, Installation, Grenzen und Bedienbeispielen vervollständigen.
- Installationspaket beziehungsweise definierten Versionsstand sowie Sicherungs- und Rückkehrverfahren vorbereiten.

**Abnahme:** vollständige lokale Tests und eingeführte Lint-/Typprüfungen bestehen; reale HA-Gesamttests und Upgrade-/Reload-Fälle protokolliert; keine offenen Fehler mit Risiko für Bestands- oder Historienkorrektheit. Rückkehrverfahren berücksichtigt auch ein gegebenenfalls geändertes Storeformat.

## Phase 9 – Kontrollierte Inbetriebnahme der realen Instanz

**Ergebnis:** MVP in der Nutzerinstanz installiert und mit realen Quellen geprüft.

- Tatsächlichen Zielstand und konkrete Auswirkungen prüfen; Integration, Konfiguration und betroffene Persistenz vor Änderungen sichern.
- Geprüften Versionsstand installieren und erforderlichen Reload beziehungsweise Neustart durchführen.
- Tanks und Verbraucher passend zu den realen Quellen einrichten; keine historischen Tankdaten löschen oder zurücksetzen.
- Gezielte Testbuchungen in einem separaten Testtank durchführen; reale Bestände nur auf belegter Grundlage setzen.
- Zustände, Einheiten, Verbrauchsintervalle, Historie und Logs prüfen. Wiederherstellung nach Neustart verifizieren.
- Einen zum realen Verbrauch passenden Beobachtungszeitraum festlegen und Messergebnisse dokumentieren. Falls Beobachtung aussteht, bleibt die Phase offen; keine Hintergrundüberwachung ohne gesonderten Auftrag einrichten.

**Abnahme:** reale Funktionsprüfung einschließlich Wiederanlauf und dokumentiertem Beobachtungsintervall erfolgreich; Unterschiede zu lokalen Tests geklärt; Nutzer kann Einrichtung und Aktionen anhand der README nachvollziehen. Einschränkungen und installierter Versionsstand sind dokumentiert.

## Umfang und Entscheidungspunkte

- Verbindlich sind ein Tank je Config Entry, Verbraucher als Subentries und ein persistentes Ereignismodell.
- Noch zu ermitteln: HA-Zielversion, verfügbare Testumgebung, Inhalte der Geräteprofile und reale Sensorsemantik.
- Noch zu entscheiden: Details der Ereignis- und Zeitregeln aus Phase 1. Dieser Plan nimmt diese Entscheidungen nicht vorweg.
- Kosten, Prognosen, komplexe Geometrien, automatische Kalibrierung und Cloud-Komponenten bleiben außerhalb des MVP.
- Zeitaufwände werden erst nach Phase 1 sinnvoll eingeschätzt. Abschluss wird anhand der Abnahme belegt, nicht anhand einer geschätzten Dauer.
