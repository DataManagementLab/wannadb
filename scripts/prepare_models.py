from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"


def download(url: str, destination: Path) -> None:
    print(f"Downloading {url}", flush=True)
    with urllib.request.urlopen(url, timeout=120) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def prepare_spacy(temporary_dir: Path) -> None:
    for model in ("en_core_sci_md", "en_ner_craft_md"):
        name = f"{model}-0.4.0"
        destination = MODELS_DIR / "spacy" / name
        archive_path = temporary_dir / f"{name}.tar.gz"

        download(
            "https://s3-us-west-2.amazonaws.com/"
            f"ai2-s2-scispacy/releases/v0.4.0/{name}.tar.gz",
            archive_path,
        )

        # Copy only the model data, excluding package setup files.
        prefix = f"{name}/{model}/{name}/"
        copied = 0

        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive:
                if not member.isfile() or not member.name.startswith(prefix):
                    continue

                relative_path = Path(member.name[len(prefix):])
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise ValueError(f"Unsafe archive path: {member.name}")

                target = destination / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)

                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"Cannot read {member.name}")

                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                copied += 1

        if not copied or not (destination / "config.cfg").is_file():
            raise ValueError(f"Model data missing from {archive_path.name}")

        archive_path.unlink()
        print(f"Prepared {name}", flush=True)


def prepare_fasttext(temporary_dir: Path) -> None:
    filename = "wiki-news-300d-1M-subword.vec"
    destination = MODELS_DIR / "fasttext" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    archive_path = temporary_dir / "fasttext.zip"

    download(
        f"https://dl.fbaipublicfiles.com/fasttext/vectors-english/{filename}.zip",
        archive_path,
    )

    with zipfile.ZipFile(archive_path) as archive:
        with archive.open(filename) as source:
            with destination.open("wb") as output:
                shutil.copyfileobj(source, output)

    archive_path.unlink()
    print("Prepared fastText vectors.", flush=True)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary_dir:
        temporary_dir = Path(temporary_dir)
        prepare_spacy(temporary_dir)
        prepare_fasttext(temporary_dir)


if __name__ == "__main__":
    main()