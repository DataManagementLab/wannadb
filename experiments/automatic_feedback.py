import random
from typing import Dict, Any, List
import logging

from wannadb.interaction import BaseInteractionCallback
from util import consider_overlap_as_match, get_document_by_name

logger: logging.Logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class AutomaticRandomRankingBasedMatchingFeedback(BaseInteractionCallback):
    """Interaction callback that gives feedback on a random nugget of the ranked list."""

    def __init__(self, documents: List[Dict[str, Any]], user_attribute_name2dataset_attribute_name: Dict[str, str]):
        self._documents: List[Dict[str, Any]] = documents
        self._user_attribute_name2dataset_attribute_name: Dict[str, str] = user_attribute_name2dataset_attribute_name

    def _call(self, pipeline_element_identifier: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if "do-attribute-request" in data.keys():
            return {
                    "do-attribute": True
                }
        nuggets = data["nuggets"]
        attribute = data["attribute"]

        attribute_name = self._user_attribute_name2dataset_attribute_name[attribute.name]

        # randomly select a nugget to give feedback on
        nugget = random.choice(nuggets)
        document = None
        for doc in self._documents:
            print(doc["id"])
            print(nugget.document.name)
            if doc["id"] == nugget.document.name:
                document = doc

        # check whether nugget matches attribute
        for mention in document["mentions"][attribute_name]:
            if consider_overlap_as_match(mention["start_char"], mention["end_char"],
                                         nugget.start_char, nugget.end_char):
                # the nugget matches the attribute
                print(f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> IS MATCH")
                return {
                    "message": "is-match",
                    "nugget": nugget,
                    "not-a-match": None
                }

        # check if any other nugget matches attribute
        for nug in nugget.document.nuggets:
            for mention in document["mentions"][attribute_name]:
                if consider_overlap_as_match(mention["start_char"], mention["end_char"],
                                             nug.start_char, nug.end_char):
                    # there is a matching nugget in nugget's document
                    logger.debug(
                        f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> RETURN OTHER MATCHING NUGGET '{nug.text}'")
                    return {
                        "message": "is-match",
                        "nugget": nug,
                        "not-a-match": nugget
                    }

        # there is no matching nugget in nugget's document
        logger.debug(f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> NO MATCH IN DOCUMENT")
        return {
            "message": "no-match-in-document",
            "nugget": nugget,
            "not-a-match": nugget
        }


class AutomaticFixFirstRankingBasedMatchingFeedback(BaseInteractionCallback):
    """Interaction callback that gives feedback on the first incorrect nugget of the ranked list."""

    def __init__(self, documents: List[Dict[str, Any]], user_attribute_name2dataset_attribute_name: Dict[str, str]):
        self._documents: List[Dict[str, Any]] = documents
        self._user_attribute_name2dataset_attribute_name: Dict[str, str] = user_attribute_name2dataset_attribute_name

    def _call(self, pipeline_element_identifier: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if "do-attribute-request" in data.keys():
            return {
                    "do-attribute": True
                }
        nuggets = data["nuggets"]
        attribute = data["attribute"]

        attribute_name = self._user_attribute_name2dataset_attribute_name[attribute.name]

        # iterate through nuggets of ranked list and give feedback on first incorrect one
        for nugget in nuggets:
            document = None
            for doc in self._documents:
                if doc["id"] == nugget.document.name:
                    document = doc

            for mention in document["mentions"][attribute_name]:
                if consider_overlap_as_match(mention["start_char"], mention["end_char"],
                                             nugget.start_char, nugget.end_char):
                    break
            else:
                # nugget is an incorrect guess
                for nug in nugget.document.nuggets:
                    for men in document["mentions"][attribute_name]:
                        if consider_overlap_as_match(men["start_char"], men["end_char"],
                                                     nug.start_char, nug.end_char):
                            # there is a matching nugget in nugget's document
                            logger.debug(
                                f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> RETURN OTHER MATCHING NUGGET '{nug.text}'")
                            return {
                                "message": "is-match",
                                "nugget": nug,
                                "not-a-match": nugget
                            }

                # there is no matching nugget in nugget's document
                logger.debug(f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> NO MATCH IN DOCUMENT")
                return {
                    "message": "no-match-in-document",
                    "nugget": nugget,
                    "not-a-match": nugget
                }

        # all nuggets are matches
        logger.debug(f"{data['max-distance']:.2f} {attribute_name}: '{nuggets[0].text}' ==> IS MATCH")
        return {
            "message": "is-match",
            "nugget": nuggets[0],
            "not-a-match": None
        }


class AutomaticCustomMatchesRandomRankingBasedMatchingFeedback(BaseInteractionCallback):
    """Interaction callback that gives feedback on a random nugget of the ranked list and creates custom matches."""

    def __init__(self, documents: List[Dict[str, Any]], user_attribute_name2dataset_attribute_name: Dict[str, str]):
        self._documents: List[Dict[str, Any]] = documents
        self._user_attribute_name2dataset_attribute_name: Dict[str, str] = user_attribute_name2dataset_attribute_name

    def _call(self, pipeline_element_identifier: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if "do-attribute-request" in data.keys():
            return {
                    "do-attribute": True
                }
        nuggets = data["nuggets"]
        logger.debug(f"Nuggets: {', '.join(f'{n.document.name}: {n.text}' for n in data['nuggets'])}")
        attribute = data["attribute"]

        attribute_name = self._user_attribute_name2dataset_attribute_name[attribute.name]

        # randomly select a nugget to give feedback on
        nugget = random.choice(nuggets)
        document = get_document_by_name(self._documents, nugget.document.name)
        if document is None:
            logger.warning(f"Document {nugget.document.name} not found in documents.")

        # check whether nugget matches attribute
        for mention in document["mentions"][attribute_name]:
            if consider_overlap_as_match(mention["start_char"], mention["end_char"],
                                         nugget.start_char, nugget.end_char):
                # the nugget matches the attribute
                logger.debug(f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> IS MATCH")
                return {
                    "message": "is-match",
                    "nugget": nugget,
                    "not-a-match": None
                }

        # check if any other nugget matches attribute
        for nug in nugget.document.nuggets:
            for mention in document["mentions"][attribute_name]:
                if consider_overlap_as_match(mention["start_char"], mention["end_char"],
                                             nug.start_char, nug.end_char):
                    # there is a matching nugget in nugget's document
                    logger.debug(f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> RETURN OTHER MATCHING NUGGET '{nug.text}'")
                    return {
                        "message": "is-match",
                        "nugget": nug,
                        "not-a-match": nugget
                    }

        # there is no matching nugget in nugget's document

        # check if the value is mentioned in the document
        if document["mentions"][attribute_name] != []:
            # the value is mentioned in the document
            start_char = document["mentions"][attribute_name][0]["start_char"]
            end_char = document["mentions"][attribute_name][0]["end_char"]
            text = nugget.document.text[start_char:end_char]
            logger.debug(f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> RETURN CUSTOM MATCH '{text}'")
            return {
                "message": "custom-match",
                "document": nugget.document,
                "start": start_char,
                "end": end_char
            }

        # the value is not mentioned in the document
        logger.debug(f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> NO MATCH IN DOCUMENT")
        return {
            "message": "no-match-in-document",
            "nugget": nugget,
            "not-a-match": nugget
        }
