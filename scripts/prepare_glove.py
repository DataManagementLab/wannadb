from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

import numpy as np


URL = (
    "https://huggingface.co/stanfordnlp/glove/resolve/main/"
    "glove.840B.300d.zip"
)

output_dir = Path("/home/wannadb/models/glove")
output_dir.mkdir(parents=True, exist_ok=True)

vocab_path = output_dir / "glove.840B.300d.vocab"
vector_path = output_dir / "glove.840B.300dvectors.npy"

if vocab_path.is_file() and vector_path.is_file():
    print("GloVe files already exist.", flush=True)
else:
    with tempfile.TemporaryDirectory() as temporary_dir:
        temporary_dir = Path(temporary_dir)
        archive_path = temporary_dir / "glove.zip"
        temporary_vocab = temporary_dir / vocab_path.name
        temporary_vectors = temporary_dir / vector_path.name

        print("Downloading GloVe embeddings...", flush=True)
        with urllib.request.urlopen(URL, timeout=120) as response:
            with archive_path.open("wb") as destination:
                shutil.copyfileobj(response, destination)

        print("Converting GloVe embeddings...", flush=True)
        count = 0

        with (
            zipfile.ZipFile(archive_path) as archive,
            archive.open("glove.840B.300d.txt") as source,
            temporary_vocab.open("w", encoding="utf-8") as vocabulary,
            temporary_vectors.open("wb") as vectors,
        ):
            for line_number, raw_line in enumerate(source, start=1):
                # Split from the right to preserve tokens containing spaces.
                parts = raw_line.decode("utf-8").rstrip("\r\n").rsplit(" ", 300)

                if len(parts) != 301:
                    raise ValueError(f"Invalid GloVe row at line {line_number}")

                word = parts[0]
                vector = np.asarray(parts[1:], dtype=np.float32)

                vocabulary.write(word + "\n")
                vectors.write(vector.tobytes())
                count += 1

                if count % 100_000 == 0:
                    print(f"Converted {count:,} vectors...", flush=True)

        if not count or temporary_vectors.stat().st_size != count * 300 * 4:
            raise ValueError("GloVe output size is invalid")

        shutil.move(str(temporary_vectors), str(vector_path))
        shutil.move(str(temporary_vocab), str(vocab_path))

        print(f"Prepared {count:,} GloVe vectors.", flush=True)