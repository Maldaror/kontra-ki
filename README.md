# Kontra-KI

MCP-Server, der Ideen zur kritischen Gegenpruefung an eine lokal in LM Studio laufende
KI schickt. Gedacht als "Devil's Advocate" fuer Claude: statt Vorschlaege ungeprueft zu
praesentieren, laesst Claude sie zuerst von einer unabhaengigen zweiten KI hinterfragen.

## Setup

### 1. LM Studio

1. Modell laden (z.B. ein lokales Llama/Qwen/Mistral-Modell).
2. Im Developer-Tab den lokalen Server starten (Standard: `http://localhost:1234`).
3. Modellnamen pruefen: `curl http://localhost:1234/v1/models`. Default in Kontra-KI ist
   `qwen3.6-35b-a3b` (Mikes aktuell geladenes Modell). Weicht dein Modell davon ab, per
   `KONTRA_KI_MODEL` ueberschreiben (siehe unten).

### 2. Kontra-KI installieren

```bash
cd /Users/mike/Projekte/kontra-ki
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Als MCP-Server registrieren (Claude Code)

```bash
claude mcp add kontra-ki --scope user -- /Users/mike/Projekte/kontra-ki/.venv/bin/python -m kontra_ki.server
```

Falls das LM-Studio-Modell nicht `qwen3.6-35b-a3b` heisst:

```bash
claude mcp add kontra-ki --scope user --env KONTRA_KI_MODEL=<dein-modellname> -- /Users/mike/Projekte/kontra-ki/.venv/bin/python -m kontra_ki.server
```

`--scope user` macht den Server in jeder neuen Session verfuegbar, unabhaengig vom
Arbeitsverzeichnis. Danach als Tool `challenge_idea` nutzbar.

## Tool

`challenge_idea(idea: str, context: str = "", persona: str = "diabolo", strict: bool = False) -> str`

Schickt `idea` (plus optionalen `context`) mit dem System-Prompt der gewaehlten Persona
an LM Studio und gibt die Kritik der lokalen KI zurueck. System-Prompts sind bewusst auf
Englisch (bessere Instruction-Following-Rate bei kleineren lokalen Modellen), antworten
aber in der Sprache der Eingabe.

### Strict Mode

Nur fuer `inquisitor` und `code_skeptic` (echte Pass/Fail-Personas): Mit `strict=True`
liefert die Persona zusaetzlich ein Verdict (`VERDICT: REJECT` / `VERDICT: PASS`). Bei
`REJECT` kommt der Tool-Call selbst als MCP-Fehler zurueck (`isError=True`, via
`ToolError`) statt als normaler Text — die aufrufende KI bekommt dann den
"Fix-it"-Reflex statt eine ueberlesbare Text-Nachricht. Antwortet das lokale Modell ohne
das erwartete Verdict-Format, faellt das Tool offen (Text wird normal zurueckgegeben,
kein stiller Fehlschlag). Persona ohne Strict-Support + `strict=True` -> klare
Fehlermeldung statt stillem Ignorieren.

### Personas

| Key | Rolle |
|---|---|
| `diabolo` (Default) | Devil's Advocate — zerlegt Argumente/Code/Ideen methodisch, stimmt nie zu |
| `cynic` | Zynischer Senior-Entwickler — fokussiert auf Skalierung, "wo bricht das", Overengineering |
| `antithesis` | Nimmt radikal die Gegenposition zur Position des Nutzers ein |
| `code_skeptic` | Paranoider Code-Auditor — Wartbarkeit, Tests, Abstraktionen, keine Loesungsvorschlaege |
| `inquisitor` | Code-Inquisitor — bestraft Pseudocode, TODOs, Auslassungen; verlangt 100% Produktionsreife |
| `chief_architect` | Ungeduldiger Chef-Architekt — keine Floskeln, verlangt Big-O/Protokolle/Race-Condition-Beweise |

Neue Personas hinzufuegen: Eintrag im `PERSONAS`-Dict in `kontra_ki/personas.py` ergaenzen.

## Struktur

- `kontra_ki/personas.py` — Persona-Registry (System-Prompts, Default)
- `kontra_ki/lm_studio_client.py` — HTTP-Client fuer LM Studios Chat-Completions-Endpoint
- `kontra_ki/server.py` — MCP-Server, verdrahtet Tool-Aufruf mit Persona + Client

## Design-Entscheidungen

- **Single-Shot, kein Multi-Turn-State**: jeder Aufruf ist unabhaengig, kein
  Session-Handling im Server noetig.
- **Mehrere feste Personas, auswaehlbar per Parameter**: keine frei formulierbaren
  System-Prompts pro Aufruf, sondern ein kuratiertes Set in `personas.py`.
- **Fixe LM-Studio-URL** (`http://localhost:1234/v1/chat/completions`): kein `.env`,
  da Kontra-KI ausschliesslich lokal neben LM Studio laeuft.
- **`isError`-Flag nur optional und persona-beschraenkt**: nur `inquisitor` und
  `code_skeptic` haben echte Pass/Fail-Semantik. Fuer die reinen Diskussions-Personas
  (`diabolo`, `cynic`, `antithesis`, `chief_architect`) gibt es kein Verdict — deren
  Kritik ist Meinung, kein Urteil, `strict=True` wird dort mit Fehlermeldung
  abgelehnt statt stillschweigend ignoriert.
