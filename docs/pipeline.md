# XILP Pipeline Diagrams

Documentation of the three-script automated podcast production pipeline for **THE 413**.

---

## 1. End-to-End Overview

```mermaid
flowchart TD
    S["`📄 scripts/*.md
    Production script markdown`"]
    C["`📋 cast_the413_S01E01.json
    Voice ID + pan + filter per character`"]
    P1["XILP001_script_parser.py"]
    J["`📦 parsed/parsed_the413_S01E01.json
    127 dialogue entries + stats`"]
    P2["XILP002_the413_producer.py"]
    P3["XILP003_the413_audio_assembly.py"]
    DRY["`--dry-run
    Preview lines + TTS cost
    No API calls`"]
    ST["`🎙️ stems/S01E01/*.mp3
    001_cold-open_adam.mp3 …`"]
    OUT["🎧 the413_S01E01_master.mp3"]

    S --> P1 --> J
    C --> P2
    J --> P2
    P2 -->|"--dry-run"| DRY
    P2 --> ST
    C --> P3
    ST --> P3 --> OUT
```

---

## 2. XILP001 — Script Parser Internals

```mermaid
flowchart TD
    IN["📄 Production script .md"]
    ESC["`strip_markdown_escapes()
    Removes backslash escapes: bracket, equals, period`"]
    LINES["Split into lines"]
    SKIP["`Skip CAST section
    Skip title line
    Skip === dividers`"]

    LINES --> SKIP --> LOOP

    subgraph LOOP["Line-by-line state machine"]
        direction TB
        CHK{"Classify line"}
        SEC["`Section header
        COLD OPEN / ACT ONE
        update current_section`"]
        SCN["`Scene header
        SCENE N:
        update current_scene`"]
        DIR["`Stage direction
        SFX / MUSIC / AMBIENCE / BEAT
        direction entry`"]
        DLG["`SPEAKER text
        dialogue entry
        speaker + direction + text`"]
        CONT["`Bare continuation text
        append to previous dialogue`"]
        STOP["`END OF EPISODE
        or PRODUCTION NOTES
        break`"]

        CHK -->|section header| SEC
        CHK -->|scene header| SCN
        CHK -->|bracket line| DIR
        CHK -->|known speaker| DLG
        CHK -->|bare text| CONT
        CHK -->|metadata or end| STOP
    end

    IN --> ESC --> LINES
    LOOP --> ENTRIES

    subgraph ENTRIES["Output entries list"]
        direction LR
        E1["`seq · type · section · scene
        speaker · direction · text
        direction_type`"]
    end

    ENTRIES --> STATS["`Compute stats
    total_entries · dialogue_lines
    characters_for_tts · speakers`"]
    STATS --> JSON["📦 parsed_the413_S01E01.json"]
```

### Speaker normalization

```mermaid
flowchart LR
    RAW["`KNOWN_SPEAKERS list
    Ordered longest-first`"]
    RAW --> MATCH{"`startswith match
    space or paren follows?`"}
    MATCH -->|yes| KEY["`SPEAKER_KEYS lookup
    ADAM → adam
    MR. PATTERSON → mr_patterson
    RIAN → rian`"]
    MATCH -->|no| SKIP2["try next speaker"]
    KEY --> ENTRY["`dialogue entry
    speaker = normalized key`"]
```

---

## 3. XILP002 — Voice Generation

```mermaid
sequenceDiagram
    actor User
    participant M as main
    participant LP as load_production
    participant QG as Quota Guard
    participant API as ElevenLabs API
    participant FS as stems directory

    User->>M: python XILP002_the413_producer.py
    M->>LP: load cast_the413_S01E01.json + parsed script
    LP-->>M: config dict, dialogue_entries list

    M->>QG: check_elevenlabs_quota — display status
    M->>QG: get_best_model_for_budget
    QG-->>M: eleven_v3 or eleven_flash_v2_5

    loop each dialogue entry from start_from
        M->>FS: stem file exists?
        alt already on disk
            FS-->>M: skip, no API call
        else voice_id is TBD
            M->>M: skip, warn user
        else
            M->>QG: has_enough_characters(text)
            alt quota exhausted
                QG-->>M: False, halt with message
            else quota OK
                M->>API: text_to_speech.convert(text, voice_id, model)
                API-->>M: audio_stream chunks
                M->>FS: write seq_section_scene_speaker.mp3
            end
        end
    end

    M-->>User: Generation complete, N new stems
```

---

## 4. XILP003 — Audio Assembly

```mermaid
flowchart TD
    C2["`📋 cast_the413_S01E01.json
    pan + filter per character`"]
    C2 --> CFG_LOAD["`CastConfiguration model
    build config dict`"]
    CFG_LOAD --> ASSMBL

    ST["`stems/S01E01/*.mp3
    sorted alphabetically
    sequence prefix guarantees order`"]
    NONE{"No stems found?"}
    WARN["`⚠️ Print warning
    Tell user to run XILP002 first`"]

    ST --> NONE
    NONE -->|yes| WARN
    NONE -->|no| LOOP2

    subgraph LOOP2["For each stem file"]
        direction TB
        EXT["`Extract speaker from filename
        rsplit underscore, take last part`"]
        CFG{"speaker in config?"}
        FILT{"filter: true?"}
        PAN["segment.pan(config pan value)"]
        PHONE["`apply_phone_filter()
        high-pass 300Hz
        low-pass 3000Hz
        +5 dB`"]
        GAP["+ 600ms silence gap"]

        EXT --> CFG
        CFG -->|yes| FILT
        CFG -->|no| PAN
        FILT -->|yes| PHONE --> PAN
        FILT -->|no| PAN
        PAN --> GAP
    end

    ASSMBL --> LOOP2
    LOOP2 --> CONCAT["`full_vocals AudioSegment
    concatenated`"]
    CONCAT --> EXPORT["export the413_S01E01_master.mp3"]
    EXPORT --> PLAY["os.system mpg123 — WSL playback"]
```

> **Restartability:** XILP003 has no ElevenLabs dependency and reads only `cast_the413_S01E01.json` and
> the `stems/<TAG>/` directory. Re-running assembly after adjusting effects or adding missing stems
> requires no API key and carries no TTS quota risk.

---

## 5. Stem File Naming Convention

```mermaid
flowchart LR
    SEQ["`seq
    003`"]
    SEP1["_"]
    SEC["`section
    cold-open`"]
    SEP2["-"]
    SCN["`scene
    scene-1`"]
    SEP3["_"]
    SPK["`speaker
    adam`"]
    EXT[".mp3"]

    SEQ --> SEP1 --> SEC --> SEP2 --> SCN --> SEP3 --> SPK --> EXT

    style SEQ fill:#d4e6f1
    style SEC fill:#d5f5e3
    style SCN fill:#fdebd0
    style SPK fill:#f9ebea
```

**Example:** `003_cold-open_adam.mp3`, `028_act1-scene-1_rian.mp3`, `102_act2-scene-5_mr_patterson.mp3`

---

## 6. API Cost Guard Flow

```mermaid
flowchart TD
    START["Before each API call"]
    CHK["`has_enough_characters(text)
    client.user.get()`"]
    ERR{"API error?"}
    SKIP_GUARD["`Skip guard
    no user_read permission
    return True`"]
    CALC["`remaining = limit - count
    required = len(text)`"]
    CMP{"remaining >= required?"}
    OK["✅ Proceed to API call"]
    HALT["`🛑 Halt generation
    Log chars needed vs remaining`"]

    START --> CHK --> ERR
    ERR -->|yes| SKIP_GUARD
    ERR -->|no| CALC --> CMP
    CMP -->|yes| OK
    CMP -->|no| HALT

    BUDGET["`get_best_model_for_budget()
    remaining > 5000?`"]
    V3["`eleven_v3
    standard quality`"]
    FLASH["`eleven_flash_v2_5
    50% cheaper`"]
    FALLBACK["`eleven_multilingual_v2
    API error fallback`"]

    BUDGET -->|yes| V3
    BUDGET -->|no| FLASH
    BUDGET -->|exception| FALLBACK
```
