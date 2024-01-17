import random
from typing import Dict, Any, List

from wannadb.interaction import BaseInteractionCallback
from evaluation.util import consider_overlap_as_match


class AutomaticRandomCustomMatchingFeedback(BaseInteractionCallback):
    """
        Interaction callback that gives feedback on a random nugget of the ranked list if possible. If no already
        extracted nugget is found that matches the current attribute in the document, we retrieve the annotation
        for that attribute in that document. If none is given, we return that no match is given. If there is any,
        we use this as a custom match and return a custom match event!
   """

    def __init__(
            self,
            documents: List[Dict[str, Any]],
            user_attribute_name2dataset_attribute_name: Dict[str, str],
            attribute: str
    ):
        self._documents: List[Dict[str, Any]] = documents
        self._user_attribute_name2dataset_attribute_name: Dict[str, str] = user_attribute_name2dataset_attribute_name
        self._current_attribute = attribute

    def _call(self, pipeline_element_identifier: str, data: Dict[str, Any]) -> Dict[str, Any]:
        # Catch the call that decides whether this attribute should be matched and just return true for it
        if "nuggets" not in data.keys():
            return {"do-attribute": self._current_attribute == data["attribute"].name}

        # Extract the needed data
        nuggets = data["nuggets"]
        attribute = data["attribute"]

        attribute_name = self._user_attribute_name2dataset_attribute_name[attribute.name]

        # Randomly select any nugget to give feedback on
        nugget = random.choice(nuggets)

        # Fetch the document, since we have the Document object given through the nugget, but not directly the
        # annotation document from the .jsons (stored in self._documents), so we need to map the id to another
        document = None
        for doc in self._documents:
            if doc["id"] == nugget.document.name:
                document = doc

        # Check whether nugget matches attribute, if so, return that a match has been found
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

        # Check if any other nugget that has been extracted matches attribute
        for nug in nugget.document.nuggets:
            for mention in document["mentions"][attribute_name]:
                if consider_overlap_as_match(mention["start_char"], mention["end_char"],
                                             nug.start_char, nug.end_char):
                    # there is a matching nugget in nugget's document
                    print(
                        f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> RETURN OTHER MATCHING NUGGET '{nug.text}'")
                    return {
                        "message": "is-match",
                        "nugget": nug,
                        "not-a-match": nugget
                    }

        # If no nugget that has been extracted is a match, so if we reach this bit of code
        # Take the annotation from mentions (mention means whether the attribute is actually contained within the
        # document and gives us the span) and use it as a custom match!
        annotations = document["mentions"][attribute_name]

        # If no annotation is given, there is no match in the document
        if len(annotations) == 0:
            print(f"NO MATCH FOR ATTRIBUTE {attribute_name} in DOCUMENT {document['id']}!")
            return {
                "message": "no-match-in-document",
                "nugget": nugget,
                "not-a-match": nugget
            }

        # Otherwise, use a random one of it as a custom match!
        custom_match_nugget = random.choice(annotations)

        # Extract the annotation text and print that a custom match is found
        custom_match_text = nugget.document.text[custom_match_nugget['start_char']:custom_match_nugget['end_char']]
        print(f"CUSTOM ANNOTATION {custom_match_text} USED FOR ATTRIBUTE {attribute_name} IN DOCUMENT {document['id']}!")

        # Create the return type: Contains document, start and end, the matching pipeline them embeds it and invokes
        # one of our extractors!
        return {
            "message": "custom-match",
            "document": nugget.document,
            "start": custom_match_nugget["start_char"],
            "end": custom_match_nugget["end_char"]
        }


class AutomaticRandomRankingBasedMatchingFeedback(BaseInteractionCallback):
    """Interaction callback that gives feedback on a random nugget of the ranked list."""

    def __init__(self, documents: List[Dict[str, Any]], user_attribute_name2dataset_attribute_name: Dict[str, str]):
        self._documents: List[Dict[str, Any]] = documents
        self._user_attribute_name2dataset_attribute_name: Dict[str, str] = user_attribute_name2dataset_attribute_name

    def _call(self, pipeline_element_identifier: str, data: Dict[str, Any]) -> Dict[str, Any]:
        # Catch the call that decides whether this attribute should be matched and just return true for it
        if "nuggets" not in data.keys():
            return {"do-attribute": True}

        # Extract the needed data
        nuggets = data["nuggets"]
        attribute = data["attribute"]

        attribute_name = self._user_attribute_name2dataset_attribute_name[attribute.name]

        # randomly select any nugget to give feedback on
        nugget = random.choice(nuggets)
        document = None
        for doc in self._documents:
            if doc["id"] == nugget.document.name:
                document = doc

        # check whether nugget matches attribute, if so, return that a match has been found
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
                    print(
                        f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> RETURN OTHER MATCHING NUGGET '{nug.text}'")
                    return {
                        "message": "is-match",
                        "nugget": nug,
                        "not-a-match": nugget
                    }

        # there is no matching nugget in nugget's document
        print(f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> NO MATCH IN DOCUMENT")
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
                            print(
                                f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> RETURN OTHER MATCHING NUGGET '{nug.text}'")
                            return {
                                "message": "is-match",
                                "nugget": nug,
                                "not-a-match": nugget
                            }

                # there is no matching nugget in nugget's document
                print(f"{data['max-distance']:.2f} {attribute_name}: '{nugget.text}' ==> NO MATCH IN DOCUMENT")
                return {
                    "message": "no-match-in-document",
                    "nugget": nugget,
                    "not-a-match": nugget
                }

        # all nuggets are matches
        print(f"{data['max-distance']:.2f} {attribute_name}: '{nuggets[0].text}' ==> IS MATCH")
        return {
            "message": "is-match",
            "nugget": nuggets[0],
            "not-a-match": None
        }