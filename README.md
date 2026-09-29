# digital-musicology

Computational work on the Notre-Dame repertory: clausulae, their relation to the chant, and the tools
needed to get the manuscripts into analysable form.

| Folder | What it is |
| --- | --- |
| [`ligature-rhythm/`](ligature-rhythm/) | Python package that reads CANDR's ligature-level MEI, supplies the modal rhythm, cuts manuscript systems into clausulae and writes MusicXML. It is tuned and tested on the *Dominus* clausulae. |

The Dominus data (CANDR MEI files and edition-based MusicXML encodings) are not in this repository.
Fetch the MEI with `ligature-rhythm fetch`. The edition encodings belong to the project's working
folder.

## Sources

### Manuscripts and transcriptions

- **CANDR: Clausula Archive of the Notre Dame Repertory.**
  [candr.org.uk](https://www.candr.org.uk). Diplomatic transcriptions of the Notre-Dame sources as
  MEI (pitches, ligatures, plicae, strokes, synchronisation between voices).
  - Browse: [/browse/setting/](https://www.candr.org.uk/browse/setting/)
  - One setting's MEI: `https://www.candr.org.uk/browse/setting/<id>/mei/`
  - Staves as RDF (with coordinates): `/browse/stave/<id>/rdf/`
  - Coverage (September 2026): F fol. 10v and 147r–155r, and all of W1.
- **F: Florence, Biblioteca Medicea Laurenziana, Pluteus 29.1** (the Medici Antiphoner).
  - Digital facsimile: [Teca Digitale, *Plutei*](https://tecabml.contentdm.oclc.org/digital/collection/plutei)
  - Description: [DIAMM source 924](https://www.diamm.ac.uk/sources/924/),
    [Wikipedia](https://en.wikipedia.org/wiki/Pluteo_29.1)
- **W1: Wolfenbüttel, Herzog August Bibliothek, Cod. Guelf. 628 Helmst.**
  - Digital facsimile: [Wolfenbütteler Digitale Bibliothek](https://diglib.hab.de/mss/628-helmst/start.htm)
  - Description: [HAB manuscript database](https://diglib.hab.de/?db=mss&list=ms&id=628-helmst&lang=en),
    [DIAMM source 870](https://www.diamm.ac.uk/sources/870/)
- **Magnus liber organi.**
  - Scans of the facsimiles and older editions: [IMSLP](https://imslp.org/wiki/Magnus_Liber_Organi_(Various))
  - Overview: [Wikipedia](https://en.wikipedia.org/wiki/Magnus_Liber)

### Editions (ground truth for testing)

- **Baltzer, *Le Magnus liber organi de Notre-Dame de Paris*, vol. V** (clausulae of F), Éditions de
  l'Oiseau-Lyre. The *Dominus* encodings used for tuning follow this edition. It is under copyright,
  so the encodings are not included here.
- **Thomas B. Payne, *Organa, Clausulae and Conductus from MS I-Fl Pluteus 29.1*** on DIAMM:
  [diamm.ac.uk](https://www.diamm.ac.uk/resources/music-editions/organa-and-clausulae-ms-i-fl-pluteus-291/).
  Modern transcriptions of F. This is a likely second source of ground truth for testing the reader
  beyond *Dominus*.

### Chant

- **[Cantus Index](https://cantusindex.org)**: chant texts and melodies by Cantus ID, for tenor
  incipits.

### Tools

- **[MEI](https://music-encoding.org)**: the Music Encoding Initiative format CANDR uses.
- **[verovio](https://www.verovio.org)**: engraving MusicXML/MEI to SVG. `pip install verovio`.
- **[music21](https://web.mit.edu/music21/)**: analysis of the realised MusicXML (intervals,
  reductions).

## Working with this repository

```bash
cd ligature-rhythm
pip install -e '.[test]'
pytest
```

See [`ligature-rhythm/README.md`](ligature-rhythm/README.md) for usage, method and accuracy.
