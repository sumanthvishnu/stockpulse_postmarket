"""Prepend missing torch imports in broken diffusers lora_pipeline.py."""

from pathlib import Path

HEADER = "import torch\nfrom torch import nn\n"


def main() -> None:
    import diffusers

    path = Path(diffusers.__file__).resolve().parent / "loaders" / "lora_pipeline.py"
    if not path.is_file():
        print("no lora_pipeline.py")
        return
    text = path.read_text(encoding="utf-8")
    if text.startswith(HEADER):
        print("already patched")
        return
    path.write_text(HEADER + text, encoding="utf-8")
    print(f"patched {path}")


if __name__ == "__main__":
    main()
