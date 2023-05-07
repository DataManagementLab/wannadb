from typing import List

import pytest

from wannadb.data.data import Attribute, Document, DocumentBase, InformationNugget
from wannadb.data.signals import CachedDistanceSignal, LabelSignal, SentenceStartCharsSignal, CurrentMatchIndexSignal


@pytest.fixture
def documents() -> List[Document]:
    return [
        Document(
            "document-0",
            "Wilhelm Conrad Röntgen (/ˈrɛntɡən, -dʒən, ˈrʌnt-/; [ˈvɪlhɛlm ˈʁœntɡən]; 27 March 1845 – 10 "
            "February 1923) was a German physicist, who, on 8 November 1895, produced and detected "
            "electromagnetic radiation in a wavelength range known as X-rays or Röntgen rays, an achievement "
            "that earned him the first Nobel Prize in Physics in 1901. In honour of his accomplishments, in "
            "2004 the International Union of Pure and Applied Chemistry (IUPAC) named element 111, "
            "roentgenium, a radioactive element with multiple unstable isotopes, after him."
        ),
        Document(
            "document-1",
            "Wilhelm Carl Werner Otto Fritz Franz Wien ([ˈviːn]; 13 January 1864 – 30 August 1928) was a "
            "German physicist who, in 1893, used theories about heat and electromagnetism to deduce Wien's "
            "displacement law, which calculates the emission of a blackbody at any temperature from the "
            "emission at any one reference temperature. He also formulated an expression for the black-body "
            "radiation which is correct in the photon-gas limit. His arguments were based on the notion of "
            "adiabatic invariance, and were instrumental for the formulation of quantum mechanics. Wien "
            "received the 1911 Nobel Prize for his work on heat radiation. He was a cousin of Max Wien, "
            "inventor of the Wien bridge."
        ),
        Document(
            "document-2",
            "Heike Kamerlingh Onnes ([ˈɔnəs]; 21 September 1853 – 21 February 1926) was a Dutch physicist and "
            "Nobel laureate. He exploited the Hampson-Linde cycle to investigate how materials behave when "
            "cooled to nearly absolute zero and later to liquefy helium for the first time. His production "
            "of extreme cryogenic temperatures led to his discovery of superconductivity in 1911: for "
            "certain materials, electrical resistance abruptly vanishes at very low temperatures."
        ),
        Document(
            "document-2",
            "Heike Kamerlingh Onnes ([ˈɔnəs]; 21 September 1853 – 21 February 1926) was a Dutch physicist and "
            "Nobel laureate. He exploited the Hampson-Linde cycle to investigate how materials behave when "
            "cooled to nearly absolute zero and later to liquefy helium for the first time. His production "
            "of extreme cryogenic temperatures led to his discovery of superconductivity in 1911: for "
            "certain materials, electrical resistance abruptly vanishes at very low temperatures."
        )
    ]


@pytest.fixture
def information_nuggets(documents) -> List[InformationNugget]:
    return [
        InformationNugget(documents[0], 0, 22),
        InformationNugget(documents[0], 56, 123),
        InformationNugget(documents[1], 165, 176),
        InformationNugget(documents[1], 234, 246),
        InformationNugget(documents[2], 434, 456),
        InformationNugget(documents[2], 123, 234),
        InformationNugget(documents[2], 123, 234)
    ]


@pytest.fixture
def attributes() -> List[Attribute]:
    return [
        Attribute("name"),
        Attribute("field"),
        Attribute("field")
    ]


@pytest.fixture
def document_base(documents, information_nuggets, attributes) -> DocumentBase:
    # link nuggets to documents
    for nugget in information_nuggets:
        nugget.document.nuggets.append(nugget)

    # set up some dummy attribute mappings for documents 0 and 1
    documents[0].attribute_mappings[attributes[0].name] = [information_nuggets[0]]
    documents[0].attribute_mappings[attributes[1].name] = []

    return DocumentBase(
        documents=documents[:-1],
        attributes=attributes[:-1]
    )


def test_information_nugget(documents, information_nuggets, attributes, document_base) -> None:
    # test __eq__
    assert information_nuggets[0] == information_nuggets[0]
    assert information_nuggets[0] != information_nuggets[1]
    assert information_nuggets[1] != information_nuggets[0]
    assert information_nuggets[0] != object()
    assert object() != information_nuggets[0]

    # test __str__ and __repr__ and __hash__
    for nugget in information_nuggets:
        assert str(nugget) == f"'{nugget.text}'"
        assert repr(nugget) == f"InformationNugget({repr(nugget.document)}, {nugget.start_char}, {nugget.end_char})"
        assert hash(nugget) == hash((nugget.document, nugget.start_char, nugget.end_char))

    # test document
    assert information_nuggets[0].document is documents[0]

    # test start_char and end_char
    assert information_nuggets[0].start_char == 0
    assert information_nuggets[0].end_char == 22

    # test text
    assert information_nuggets[0].text == "Wilhelm Conrad Röntgen"

    # test signals
    information_nuggets[5][LabelSignal] = "my-label-signal"
    assert information_nuggets[5].signals[LabelSignal.identifier].value == "my-label-signal"
    assert information_nuggets[5][LabelSignal.identifier] == "my-label-signal"
    assert information_nuggets[5][LabelSignal] == "my-label-signal"
    assert information_nuggets[5] != information_nuggets[6]
    assert information_nuggets[6] != information_nuggets[5]

    information_nuggets[5][LabelSignal] = "new-value"
    assert information_nuggets[5][LabelSignal] == "new-value"

    information_nuggets[5][LabelSignal.identifier] = "new-new-value"
    assert information_nuggets[5][LabelSignal] == "new-new-value"

    information_nuggets[5][LabelSignal] = LabelSignal("another-value")
    assert information_nuggets[5][LabelSignal] == "another-value"

    information_nuggets[5][CachedDistanceSignal] = CachedDistanceSignal(0.23)
    assert information_nuggets[5][CachedDistanceSignal] == 0.23


def test_attribute(documents, information_nuggets, attributes, document_base) -> None:
    # test __eq__
    assert attributes[0] == attributes[0]
    assert attributes[0] != attributes[1]
    assert attributes[1] != attributes[0]
    assert attributes[0] != object()
    assert object() != attributes[0]

    # test __str__ and __repr__ and __hash__
    for attribute in attributes:
        assert str(attribute) == f"'{attribute.name}'"
        assert repr(attribute) == f"Attribute('{attribute.name}')"
        assert hash(attribute) == hash(attribute.name)

    # test name
    assert attributes[0].name == "name"

    # test signals
    attributes[1][LabelSignal] = "my-label-signal"
    assert attributes[1].signals[LabelSignal.identifier].value == "my-label-signal"
    assert attributes[1][LabelSignal.identifier] == "my-label-signal"
    assert attributes[1][LabelSignal] == "my-label-signal"
    assert attributes[1] != attributes[2]
    assert attributes[2] != attributes[1]

    attributes[1][LabelSignal] = "new-value"
    assert attributes[1][LabelSignal] == "new-value"

    attributes[1][LabelSignal.identifier] = "new-new-value"
    assert attributes[1][LabelSignal] == "new-new-value"

    attributes[1][LabelSignal] = LabelSignal("another-value")
    assert attributes[1][LabelSignal] == "another-value"

    attributes[1][CachedDistanceSignal] = CachedDistanceSignal(0.23)
    assert attributes[1][CachedDistanceSignal] == 0.23


def test_document(documents, information_nuggets, attributes, document_base) -> None:
    # test __eq__
    assert documents[0] == documents[0]
    assert documents[0] != documents[1]
    assert documents[1] != documents[0]
    assert documents[0] != object()
    assert object() != documents[0]

    # test __str__ and __repr__ and __hash__
    for document in documents:
        assert str(document) == f"'{document.text}'"
        assert repr(document) == f"Document('{document.name}', '{document.text}')"
        assert hash(document) == hash(document.name)

    # test name
    assert documents[0].name == "document-0"

    # test text
    assert documents[0].text[:40] == "Wilhelm Conrad Röntgen (/ˈrɛntɡən, -dʒən"

    # test nuggets
    assert documents[0].nuggets == [information_nuggets[0], information_nuggets[1]]

    # test attribute mappings
    assert documents[0].attribute_mappings[attributes[0].name] == [information_nuggets[0]]
    assert documents[0].attribute_mappings[attributes[1].name] == []

    # test signals
    documents[2][SentenceStartCharsSignal] = [0, 10, 20]
    assert documents[2].signals[SentenceStartCharsSignal.identifier].value == [0, 10, 20]
    assert documents[2][SentenceStartCharsSignal.identifier] == [0, 10, 20]
    assert documents[2][SentenceStartCharsSignal] == [0, 10, 20]
    assert documents[2] != documents[3]
    assert documents[3] != documents[2]

    documents[2][SentenceStartCharsSignal] = [1, 2, 3]
    assert documents[2][SentenceStartCharsSignal] == [1, 2, 3]

    documents[2][SentenceStartCharsSignal.identifier] = [3, 4, 5]
    assert documents[2][SentenceStartCharsSignal] == [3, 4, 5]

    documents[2][SentenceStartCharsSignal.identifier] = SentenceStartCharsSignal([6, 7])
    assert documents[2][SentenceStartCharsSignal] == [6, 7]

    documents[2][CurrentMatchIndexSignal] = CurrentMatchIndexSignal(2)
    assert documents[2][CurrentMatchIndexSignal] == 2


def test_document_base(documents, information_nuggets, attributes, document_base) -> None:
    # test __eq__
    assert document_base == document_base
    assert document_base != DocumentBase(documents, attributes[:1])
    assert DocumentBase(documents, attributes[:1]) != document_base
    assert document_base != object()
    assert object() != document_base

    # test __str__
    assert str(document_base) == "(3 documents, 7 nuggets, 2 attributes)"

    # test __repr__
    assert repr(document_base) == "DocumentBase([{}], [{}])".format(
        ", ".join(repr(document) for document in document_base.documents),
        ", ".join(repr(attribute) for attribute in document_base.attributes)
    )

    # test documents
    assert document_base.documents == documents[:-1]

    # test attributes
    assert document_base.attributes == attributes[:-1]

    # test nuggets
    assert document_base.nuggets == information_nuggets

    # test to_table_dict
    assert document_base.to_table_dict() == {
        "document-name": ["document-0", "document-1", "document-2"],
        "name": [[information_nuggets[0]], None, None],
        "field": [[], None, None]
    }

    assert document_base.to_table_dict("text") == {
        "document-name": ["document-0", "document-1", "document-2"],
        "name": [["Wilhelm Conrad Röntgen"], None, None],
        "field": [[], None, None]
    }

    assert document_base.to_table_dict("value") == {
        "document-name": ["document-0", "document-1", "document-2"],
        "name": [[None], None, None],
        "field": [[], None, None]
    }

    # test get_nuggets_for_attribute
    assert document_base.get_nuggets_for_attribute(attributes[0]) == [information_nuggets[0]]

    # test get_column_for_attribute
    assert document_base.get_column_for_attribute(attributes[0]) == [[information_nuggets[0]], None, None]

    # test validate_consistency
    assert document_base.validate_consistency()

    # test to_bson and from_bson
    bson_bytes: bytes = document_base.to_bson()
    copied_document_base: DocumentBase = DocumentBase.from_bson(bson_bytes)
    assert document_base == copied_document_base
    assert copied_document_base == document_base
