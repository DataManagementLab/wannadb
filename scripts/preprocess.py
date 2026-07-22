import argparse
import logging.config
import os
from pathlib import Path

from wannadb.configuration import Pipeline
from wannadb.data.data import Document, DocumentBase
from wannadb.interaction import EmptyInteractionCallback
from wannadb.preprocessing.dimension_reduction import PCAReducer
from wannadb.preprocessing.embedding import BERTContextSentenceEmbedder, RelativePositionEmbedder, SBERTTextEmbedder, SBERTLabelEmbedder
from wannadb.preprocessing.extraction import StanzaNERExtractor, SpacyNERExtractor
from wannadb.preprocessing.label_paraphrasing import OntoNotesLabelParaphraser, SplitAttributeNameLabelParaphraser
from wannadb.preprocessing.normalization import CopyNormalizer
from wannadb.preprocessing.other_processing import ContextSentenceCacher, DuplicatedNuggetsCleaner
from wannadb.resources import ResourceManager
from wannadb.statistics import Statistics
from wannadb.status import EmptyStatusCallback


def init_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        usage="preprocess.py input_path output_path [OPTIONS]",
        description="Preprocess a collection of textual documents into a document base.",
        prog="WannaDB Preprocessing CLI",
    )
    parser.add_argument(
        "-v", "--version", action="version",
        version=f"{parser.prog} version 0.9.0"
    )
    parser.add_argument("input_path", help="Path containing the input files")
    parser.add_argument("output_path",
                        help="Path where the resulting bson file should be placed. "
                             "Will be created if it does not exist yet.")
    parser.add_argument('-n', '--name', required=False,
                        help="Name of the serialized document base. "
                             "Optional, if not specified 'document_base' will be used.")
    return parser


def main() -> None:
    parser = init_argparse()
    args = parser.parse_args()
    print(args.input_path)
    print(args.output_path)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logger = logging.getLogger()

    dataset_name = args.name if args.name else "document_base"
    input_path = args.input_path
    output_path = args.output_path

    with ResourceManager():
        documents = []
        for filename in os.listdir(input_path):
            with open(os.path.join(input_path, filename), "r", encoding='utf-8') as infile:
                text = infile.read()
                documents.append(Document(filename.split(".")[0], text))

        logger.info(f"Loaded {len(documents)} documents")

        wannadb_pipeline = Pipeline([
            StanzaNERExtractor(),
            SpacyNERExtractor("SpacyEnCoreWebLg"),
            ContextSentenceCacher(),
            CopyNormalizer(),
            OntoNotesLabelParaphraser(),
            SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
            SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
            SBERTTextEmbedder("SBERTBertLargeNliMeanTokensResource"),
            BERTContextSentenceEmbedder("BertLargeCasedResource"),
            RelativePositionEmbedder(),
            DuplicatedNuggetsCleaner(),
            PCAReducer()
        ])

        document_base = DocumentBase(documents, [])

        statistics = Statistics(do_collect=True)
        statistics["preprocessing"]["config"] = wannadb_pipeline.to_config()

        wannadb_pipeline(
            document_base=document_base,
            interaction_callback=EmptyInteractionCallback(),
            status_callback=EmptyStatusCallback(),
            statistics=statistics["preprocessing"]
        )

        Path(output_path).mkdir(parents=True, exist_ok=True)
        with open(os.path.join(output_path, f"{dataset_name}.bson"), "wb") as file:
            file.write(document_base.to_bson())


if __name__ == "__main__":
    main()
