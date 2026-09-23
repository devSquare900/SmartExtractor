import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_block(text, x0, y0, x1, y1, confidence=0.99):
    return {"box": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "text": text, "confidence": confidence}


def make_page(blocks, page_number=1, width=1200, height=1700):
    return {"page_number": page_number, "width": width, "height": height, "blocks": blocks}
