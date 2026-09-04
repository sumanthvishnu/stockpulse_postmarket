"""Fix broken diffusers builds that use `nn` without importing it."""

from pathlib import Path


def main() -> None:
    import diffusers

    path = Path(diffusers.__file__).resolve().parent / "loaders" / "lora_pipeline.py"
    if not path.is_file():
        print("no lora_pipeline.py")
        return
    text = path.read_text(encoding="utf-8")
    if "from torch import nn" in text:
        print("already patched")
        return
    if "import torch\n" not in text:
        print("no import torch to hook")
        return
    path.write_text(
        text.replace("import torch\n", "import torch\nfrom torch import nn\n", 1),
        encoding="utf-8",
    )
    print(f"patched {path}")


if __name__ == "__main__":
    main()
