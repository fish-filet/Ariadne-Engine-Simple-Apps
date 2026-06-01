---
name: connector-generator
description: Generiert und validiert einen Python-basierten Konnektor basierend auf
  einem Machine Profile und einer Ziel-Spezifikation.
tags: []
tools:
- write_file
- edit_file
- exec_terminal_command
- think
- apply_patch
mcps: []
metadata: {}
---

# Connector Generator

## Purpose
Generiert und validiert einen Python-basierten Konnektor, der auf einem "Machine Profile" basiert und Daten gemäß einer Ziel-Spezifikation transformiert.

## When to Use
Wenn ein Machine Profile (aus dem `machine-data-profiler`) und eine Ziel-Spezifikation (z.B. API-Definition, JSON-Schema oder Textbeschreibung der Ziel-Plattform) vorliegen.

## Workflow

### Phase 1: Requirement Gathering (Interaktiv)
1. **Input-Check:** Verifiziere das Vorhandensein von zwei Komponenten:
   - Einem validen **Machine Profile** (JSON).
   - Einer **Ziel-Spezifikation** (API-Dokumentation, Schema oder detaillierte Textbeschreibung).
2. **Aufforderung:** Falls eine Komponente fehlt, fordere den Nutzer aktiv dazu auf, den Pfad oder den Text der fehlenden Information bereitzustellen.

### Phase 2: Design & Implementation
1. **Mapping-Planung:** Nutze `think`, um das Mapping von der Quelle zur Ziel-Plattform zu entwerfen (z.B. Einheitenumrechnung, Datentyp-Konvertierung, Key-Mapping).
2. **Code-Erstellung:** Implementiere den Konnektor als Python-Skript. Nutze `write_file` oder `apply_patch`, um den Code zu erstellen. Der Code muss robust sein (Logging, Fehlerbehandlung bei unvollständigen Datensätzen).

### Phase 3: Automated Validation (The Debugging Loop)
1. **Testlauf:** Nutze `exec_terminal_command`, um das generierte Skript gegen eine Stichprobe der Quelldaten (aus dem Machine Profile) auszuführen.
2. **Feedback-Analyse:** 
   - **Erfolg:** Wenn das Skript läuft und das Zielformat korrekt erzeugt, ist die Aufgabe abgeschlossen.
   - **Fehler:** Wenn Fehler auftreten (Syntax, Runtime, Formatfehler), analysiere die Fehlermeldung mittels `think`.
3. **Korrektur:** Nutze `edit_file` oder `write_file`, um den Fehler zu beheben, und starte den Testlauf erneut. Wiederhole diesen Loop, bis die Validierung erfolgreich ist oder keine sinnvollen Korrekturen mehr möglich sind.

### Phase 4: Final Delivery
1. **Ergebnis:** Gib den Pfad zum validierten Skript sowie eine Zusammenfassung der durchgeführten Transformationen und der Testergebnisse aus.
