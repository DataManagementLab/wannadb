"""
Nobel Price Winners Dataset
===========================

The nobel price winners dataset consists of articles about nobel price winners from the T-Rex dataset:
https://hadyelsahar.github.io/t-rex/

The texts have been annotated with information about where they mention the structured values.

Each entry of the dataset is a json file of the following structure:
{
    "id": "<id of the document>",
    "text": "<article>",
    "mentions": {
        "<attribute name>": [
            {
            "start_char": <position of the first character of the mention>,
            "end_char": <position of the first character after the mention>
            }    # for each mention of the attribute in the text
        ]  # for each attribute
    },
    "mentions_same_attribute_class": {
        #  same as "mentions", but with mentions of the same attribute class (e.g. city), but not the desired value
    }
}  # for each document
"""
import json
import logging
import os
from glob import glob
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

NAME: str = "nobel"

ATTRIBUTES: List[str] = [
    "date_of_birth",  # date of birth
    "date_of_death",  # date of death
    "field_of_work",  # field of work
    "country"  # country
]


def load_dataset() -> List[Dict[str, Any]]:
    """
    Load the nobel price winners dataset.

    This method requires the .json files in the "datasets/nobel/documents/" folder.
    """
    dataset: List[Dict[str, Any]] = []
    path: str = os.path.join(os.path.dirname(__file__), "documents", "*.json")
    for file_path in glob(path):
        with open(file_path, encoding="utf-8") as file:
            dataset.append(json.loads(file.read()))
    return dataset


def write_document(document: Dict[str, Any]) -> None:
    """
    Write the given document to the dataset.
    """
    path: str = os.path.join(os.path.dirname(__file__), "documents", document["id"] + ".json")
    with open(path, "w", encoding="utf-8") as file:
        file.write(json.dumps(document))