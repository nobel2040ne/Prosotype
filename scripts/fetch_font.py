"""Download the local OFL variable fonts used by English and Korean captions.

This is the only network access in the project besides model-weight downloads;
everything at runtime is served by AutoCWI from ``assets/``.
"""

from pathlib import Path
from urllib.request import urlretrieve

FONTS = {
    "RobotoFlex.ttf": (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/robotoflex/"
        "RobotoFlex%5BGRAD%2CXOPQ%2CXTRA%2CYOPQ%2CYTAS%2CYTDE%2CYTFI%2CYTLC%2C"
        "YTUC%2Copsz%2Cslnt%2Cwdth%2Cwght%5D.ttf"
    ),
    "NotoSansKR.ttf": (
        "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanskr/"
        "NotoSansKR%5Bwght%5D.ttf"
    ),
}


def main() -> None:
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(exist_ok=True)
    for filename, url in FONTS.items():
        dest = assets / filename
        if dest.exists():
            print(f"already present: {dest}")
            continue
        print(f"downloading {filename} ...")
        urlretrieve(url, dest)
        print(f"wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
