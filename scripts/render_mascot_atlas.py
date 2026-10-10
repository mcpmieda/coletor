"""Rebuild the approved PNG atlas from the committed pixel rows (Pillow optional).

Only authored artwork is read; this utility never reads a diary or uses a network.
"""
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'ui/src/mascot/sprite-source.json'
DESTINATION = ROOT / 'ui/public/mascot'


def render_frame(rows, palette, size):
    width, height = size
    if len(rows) != height or any(len(row) != width for row in rows):
        raise ValueError('Malformed pixel grid')
    colors = {'.': (0, 0, 0, 0)}
    for key, value in palette.items():
        colors[key] = tuple(int(value[i:i+2], 16) for i in (1, 3, 5)) + (255,)
    image = Image.new('RGBA', size)
    image.putdata([colors[key] for row in rows for key in row])
    return image


def main():
    source = json.loads(SOURCE.read_text())
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for group, filename in [('body', 'atlas.png'), ('heads', 'head-expressions.png')]:
        spec = source[group]
        atlas = Image.new('RGBA', tuple(spec['size']))
        for frame in spec['frames'].values():
            image = render_frame(frame['rows'], source['palette'], tuple(spec['frameSize']))
            x, y, width, height = frame['rect']
            if (width, height) != image.size:
                raise ValueError('Frame rectangle differs from the approved grid')
            atlas.paste(image, (x, y))
        atlas.save(DESTINATION / filename)
    head = render_frame(source['heads']['frames']['neutral']['rows'], source['palette'], (32,32))
    head.save(DESTINATION / 'head.png')


if __name__ == '__main__':
    main()
