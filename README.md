# digital-musicology

Tools for Alex Bean's computational work on the Notre-Dame clausulae.

| Folder | What it does |
| --- | --- |
| `melodic-reduction/` | Tonality-free melodic reduction on music21: prolongational hierarchy, reduction levels, fundamental line, focal pitches, repeated modules. Rules and sources in `melodic-reduction/rules.md`. |
| `schenker-graph/` | Engraves Schenkerian graphs with verovio: the original score with the fundamental line beamed across systems, prolongation slurs, focal-pitch and module labels; optional reduction staves via music21's `ScoreReduction`. |
| `skills/` | Claude skills (`SKILL.md`) that drive the two packages. |

The ligature-rhythm reader (modal rhythm from CANDR MEI) lives on the `ligature-rhythm` branch.

```bash
pip install -e melodic-reduction -e schenker-graph
melodic-reduction analyze Dominus3.xml --json Dominus3.json
schenker-graph Dominus3.xml --analysis Dominus3.json --out graphs/Dominus3
```
