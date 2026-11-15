# E1: zbiór danych i wyniki modeli bazowych (zero-shot i few-shot)

**Projekt:** Fine-tuning modelu do generowania diagramów Mermaid z opisów procesów w języku polskim

## 1. Cel etapu

Na etapie E1 ustalamy zbiór testowy (golden set) i punkt odniesienia dla fine-tuningu. Modele bazowe
uruchamiamy bez douczania, z promptingiem zero-shot i few-shot. Późniejszy model będzie porównywany
z tymi wynikami.

Zadanie: dla polskiego opisu procesu model ma zwrócić sam kod Mermaid (`flowchart` albo `sequenceDiagram`).

## 2. Zbiory danych

### 2.1 Źródła

| Źródło | Do czego |
|---|---|
| `RonnieAllen/mermaid-flowchart-dataset`  | diagramy `flowchart` do golden setu; 2 przykłady few-shot ze splitu `validation` |
| `ibm-research/MermaidSeqBench` | diagramy `sequenceDiagram` do golden setu |
| drafted | łatwe diagramy, teksty spoza zakresu |

### 2.2 Golden set (`data/golden/golden.jsonl`)

Wszystkie wyniki w tym raporcie liczymy na tym zbiorze: 130 rekordów, z czego 125 to diagramy, a 5 to teksty
spoza zakresu.

| | flowchart | sequenceDiagram | none | razem |
|---|---|---|---|---|
| RonnieAllen | 84 | – | – | 84 |
| MermaidSeqBench | – | 30 | – | 30 |
| drafted | 7 | 4 | 5 | 16 |
| **razem** | **91** | **34** | **5** | **130** |

| Podział | Wartości |
|---|---|
| Styl opisu | structured 43, natural 41, brief 41 (rekordy `none` nie mają stylu) |
| Trudność | easy 12, medium 100, hard 13 |

**Style opisu.** Każdy opis zawiera wszystkie kroki i gałęzie diagramu.
- `structured`: krok po kroku, słowami bliskimi etykietom.
- `natural`: tak, jak powiedziałby użytkownik, z inną kolejnością i dygresjami.
- `brief`: krótko, ale kompletnie.

**Trudność.**
- flowchart: easy to ≤ 6 węzłów i brak decyzji; medium to ≤ 12 węzłów i ≤ 2 decyzje; reszta to hard.
- sequenceDiagram: easy to ≤ 8 komunikatów i brak bloków; medium to ≤ 14 komunikatów i ≤ 1 blok; reszta to
  hard.

### 2.3 Przykłady few-shot (`data/shots/shots_pl.jsonl`)

Golden set nigdy nie trafia do promptów few-shot, więc przykłady są z osobnego pliku. Przykłady są 3, ten sam
zestaw dla każdego rekordu. Każdy ma trudność medium i inny styl opisu:

| id | typ | styl | źródło |
|---|---|---|---|
| shot-flow-0001 | flowchart (zgłoszenie szkody, z pętlą) | brief | RonnieAllen `validation`, wiersz 7 |
| shot-seq-0001 | sequenceDiagram (rezerwacja książki w bibliotece, blok `alt`) | natural | claude-drafted, temat spoza golden setu |
| shot-flow-0002 | flowchart (rekrutacja, dodana brakująca gałąź „Nie”) | structured | RonnieAllen `validation`, wiersz 9 |

## 3. Ustawienia eksperymentu

| | Qwen3 4B | Qwen3 1.7B | Gemini 3 Flash (referencja) |
|---|---|---|---|
| Model | `qwen3:4b-instruct-2507-q8_0` | `qwen3:1.7b-q8_0` | `google/gemini-3-flash-preview` |
| Myślenie | brak (model instruct) | wyłączone (`--no-think`) | wyłączone (`--no-think`) |
| Gdzie | Ollama, Kaggle GPU (2× T4) | Ollama, Kaggle GPU (2× T4) | Kaggle Model Proxy; odpowiedzi pobrane lokalnie i ocenione w kernelu (`--replay`) |

**Wspólne dla wszystkich przebiegów.** Sprawdziliśmy to w plikach wyników po skrótach SHA-256.
- Ten sam prompt systemowy (`prompts/system.txt`) i ten sam plik danych.
- Temperatura 0, seed 0, `max_tokens` = 1024.
- Dopasowanie węzłów przez embeddingi `bge-m3` z progiem τ = 0,7.
- Few-shot: te same 3 przykłady.
- W żadnym przebiegu model nie myślał: `reasoning_chars` i `reasoning_tokens` = 0.


**Prompt few-shot.** Kolejno: prompt systemowy, potem każdy przykład jako para wiadomości użytkownik (opis) i
asystent (diagram), na końcu opis do przetworzenia.

**Gemini 3 Flash jako model referencyjny.** Ten duży model wyznacza górną granicę tego, co da się osiągnąć
promptingiem. Nie użyliśmy w tej roli Claude Sonnet 5, bo to on wygenerował tłumaczenia i opisy golden setu.
Miałby więc przewagę, bo ocenialibyśmy go na jego własnych tekstach.

### Metryki (szczegóły: `docs/design.md` §4.3)

- **typ diagramu OK**: zgadza się typ diagramu (`flowchart` albo `sequenceDiagram`).
- **renderuje się**: `mmdc` rysuje diagram bez błędu.
- **sam kod Mermaid**: odpowiedź nie jest w blokach ```` ``` ```` i nie ma tekstu dookoła.
- **węzły F1**:
  - Dla flowchartów liczone na węzłach, dla diagramów sekwencji na uczestnikach.
  - Etykiety dopasowujemy najpierw dokładnie, potem przez embeddingi: przypisanie jeden do jednego algorytmem
    węgierskim, z progiem podobieństwa τ = 0,7.
- **krawędzie F1**:
  - Dla flowchartów krawędź liczy się, gdy oba jej końce są dopasowane.
  - Dla diagramów sekwencji komunikat liczy się, gdy zgadzają się nadawca, odbiorca i tekst.
- **kształty OK**: tylko flowcharty; odsetek dopasowanych węzłów z poprawnym kształtem, np. decyzja jako romb.
- **odmowa poprawna**: tylko 5 tekstów spoza zakresu; odpowiedź to dokładnie `BRAK_PROCESU`.
- Diagram, który się nie renderuje, dostaje F1 = 0.
- Średnia makro po 125 rekordach z diagramem.

## 4. Wyniki

### 4.1 Ogółem (125 diagramów + 5 tekstów spoza zakresu)

| Miara | 4B zero-shot | 4B few-shot | 1.7B zero-shot | 1.7B few-shot | Gemini zero-shot | Gemini few-shot |
|---|---|---|---|---|---|---|
| typ diagramu OK | 124 z 125 | 125 z 125 | 89 z 125 | 109 z 125 | 125 z 125 | 124 z 125 |
| renderuje się | 114 z 125 | 120 z 125 | 50 z 125 | 115 z 125 | 125 z 125 | 125 z 125 |
| sam kod Mermaid (bez ```` ``` ````) | 110 z 125 | 125 z 125 | 125 z 125 | 125 z 125 | 125 z 125 | 125 z 125 |
| **węzły F1** | **0,77** | **0,90** | **0,23** | **0,73** | **0,88** | **0,96** |
| **krawędzie F1** | **0,63** | **0,79** | **0,12** | **0,54** | **0,78** | **0,88** |
| kształty OK (flowchart) | 0,77 | 0,95 | 0,74 | 0,90 | 0,87 | 0,99 |
| węzły / krawędzie F1 | 0,84 / 0,69 | 0,93 / 0,82 | 0,57 / 0,31 | 0,79 / 0,59 | 0,88 / 0,78 | 0,96 / 0,88 |
| odmowa poprawna | 5 z 5 | 5 z 5 | 3 z 5 | 4 z 5 | 5 z 5 | 5 z 5 |
| ucięte odpowiedzi | 0 | 0 | 2 | 1 | 0 | 0 |

### 4.2 Według typu diagramu (węzły F1 / krawędzie F1)

| Typ | n | 4B zero | 4B few | 1.7B zero | 1.7B few | Gemini zero | Gemini few |
|---|---|---|---|---|---|---|---|
| flowchart | 91 | 0,77 / 0,66 | 0,92 / 0,84 | 0,31 / 0,17 | 0,82 / 0,65 | 0,85 / 0,77 | 0,95 / 0,89 |
| sequenceDiagram | 34 | 0,76 / 0,54 | 0,84 / 0,65 | 0,00 / 0,00 | 0,48 / 0,26 | 0,97 / 0,81 | 0,99 / 0,85 |

### 4.3 Według stylu opisu (węzły F1 / krawędzie F1)

| Styl | n | 4B zero | 4B few | 1.7B zero | 1.7B few | Gemini zero | Gemini few |
|---|---|---|---|---|---|---|---|
| structured | 43 | 0,82 / 0,72 | 0,93 / 0,84 | 0,32 / 0,18 | 0,75 / 0,60 | 0,91 / 0,83 | 0,98 / 0,91 |
| brief | 41 | 0,82 / 0,67 | 0,92 / 0,82 | 0,21 / 0,11 | 0,70 / 0,51 | 0,89 / 0,80 | 0,96 / 0,88 |
| natural | 41 | 0,65 / 0,49 | 0,84 / 0,70 | 0,15 / 0,07 | 0,72 / 0,50 | 0,85 / 0,69 | 0,96 / 0,84 |

### 4.4 Według trudności (węzły F1 / krawędzie F1)

| Trudność | n | 4B zero | 4B few | 1.7B zero | 1.7B few | Gemini zero | Gemini few |
|---|---|---|---|---|---|---|---|
| easy | 12 | 0,84 / 0,72 | 0,93 / 0,82 | 0,00 / 0,00 | 0,50 / 0,41 | 0,85 / 0,71 | 0,96 / 0,85 |
| medium | 100 | 0,78 / 0,64 | 0,90 / 0,79 | 0,24 / 0,13 | 0,76 / 0,57 | 0,88 / 0,78 | 0,96 / 0,88 |
| hard | 13 | 0,59 / 0,48 | 0,86 / 0,74 | 0,34 / 0,19 | 0,67 / 0,42 | 0,96 / 0,85 | 0,99 / 0,89 |

## 5. Analiza

**Few-shot pomaga każdemu modelowi, i to tym bardziej, im mniejszy model.**

| Model | Zmiana F1 węzłów | Zmiana F1 krawędzi |
|---|---|---|
| Qwen3 4B | +0,13 | +0,16 |
| Qwen3 1.7B | +0,50 | +0,42 |
| Gemini 3 Flash | +0,08 | +0,10 |

**Qwen3 4B few-shot jest blisko Gemini zero-shot.**
- Na flowchartach 4B few-shot (0,92 / 0,84) jest nawet lepszy od Gemini zero-shot (0,85 / 0,77).
- Gemini few-shot pozostaje najlepszy (0,95 / 0,89).
- Duża luka zostaje na diagramach sekwencji: 0,84 / 0,65 dla 4B few-shot wobec 0,99 / 0,85 dla Gemini
  few-shot. Krawędzie (komunikaty) to najsłabszy punkt 4B. Na renderujących się diagramach sekwencji precyzja
  komunikatów wynosi 0,75, a czułość 0,73. Model więc zarówno dopisuje komunikaty, których nie ma w referencji,
  jak i pomija albo przeformułowuje komunikaty z referencji tak, że nie przekraczają progu τ.


**Typowe błędy, przez które diagram się nie renderuje:**
- `end` użyte jako id węzła (zabronione w Mermaid);
- etykiety z nawiasami albo cudzysłowami bez otaczających `"…"`;
- składnia bloków `alt`/`else` w diagramach sekwencji.

Te błędy występują u Qwen3 4B: 11 diagramów się nie renderuje w zero-shot i 5 w few-shot. Gemini nie zrobił
ani jednego błędu renderowania.

**Odmowy.**
- 4B i Gemini poprawnie odmówiły we wszystkich 5 przypadkach i nie odmówiły ani razu przy prawdziwym procesie.
- 1.7B w zero-shot:
  - przy dwóch tekstach spoza zakresu wypisał tekst albo diagram zamiast `BRAK_PROCESU`;
  - przy dwóch prawdziwych procesach odmówił.
- 1.7B w few-shot odmówił przy trzech prawdziwych procesach.

**Wnioski dla fine-tuningu.**
- Podstawą fine-tuningu zostaje Qwen3 4B (instruct, bez myślenia). Jego few-shot (0,90 / 0,79) to poprzeczka,
  którą model po LoRA musi przekroczyć bez przykładów w prompcie.
- Najwięcej do zyskania jest na:
  - krawędziach diagramów sekwencji,
  - opisach `natural`,
  - poprawnej składni etykiet.
- Qwen3 1.7B jest za słaby bez przykładów.
