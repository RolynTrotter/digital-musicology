"""ligature-rhythm: realise the rhythm of Notre-Dame modal notation (CANDR MEI) and write MusicXML."""
from .candr import parse_mei, upper_and_tenor, fetch, show
from .segment import split, guess_incipit, Clausula
from .features import Model, load_weights
from .realise import realise, Result, Event
from .musicxml import to_musicxml, write

__version__ = '0.2.0'
__all__ = ['parse_mei', 'upper_and_tenor', 'fetch', 'show', 'split', 'guess_incipit', 'Clausula',
           'Model', 'load_weights', 'realise', 'Result', 'Event', 'to_musicxml', 'write']
