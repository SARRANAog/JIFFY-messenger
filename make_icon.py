# -*- coding: utf-8 -*-
import os
from PIL import Image

SRC = os.path.join("web", "logo.png")
OUT_DIR = "assets"
OUT = os.path.join(OUT_DIR, "jiffy.ico")

def main():
    if not os.path.exists(SRC):
        raise FileNotFoundError(f"Missing {SRC}. Save your logo as web/logo.png")

    os.makedirs(OUT_DIR, exist_ok=True)

    img = Image.open(SRC).convert("RGBA")

    # набор размеров для Windows ico
    sizes = [(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)]
    img.save(OUT, format="ICO", sizes=sizes)

    print("OK:", OUT)

if __name__ == "__main__":
    main()
