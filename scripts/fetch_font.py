"""One-time setup: download the Roboto Flex variable .ttf (OFL license) into
assets/. This is the only network access in the project besides model-weight
downloads; everything at runtime is local."""

from pathlib import Path
from urllib.request import urlretrieve

URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/robotoflex/"
    "RobotoFlex%5BGRAD%2CXOPQ%2CXTRA%2CYOPQ%2CYTAS%2CYTDE%2CYTFI%2CYTLC%2C"
    "YTUC%2Copsz%2Cslnt%2Cwdth%2Cwght%5D.ttf"
)

def main() -> None:
    dest = Path(__file__).resolve().parent.parent / "assets" / "RobotoFlex.ttf"
    dest.parent.mkdir(exist_ok=True)
    if dest.exists():
        print(f"already present: {dest}")
        return
    print("downloading Roboto Flex variable font ...")
    urlretrieve(URL, dest)
    print(f"wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
