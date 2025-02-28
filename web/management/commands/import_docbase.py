from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

import random


from web.models import Collection, Document, Nugget, NuggetLabel, BoxAttribute, BoxAttributeValue

from wannadb.data.data import Attribute
from wannadb.matching.custom_match_extraction import DummyCustomMatchExtractor
from wannadb.matching.distance import SignalsMeanDistance
from wannadb.matching.matching import RankingBasedMatcher
from wannadb.configuration import Pipeline
from wannadb.data.data import DocumentBase
from wannadb.preprocessing.embedding import BERTContextSentenceEmbedder, RelativePositionEmbedder, SBERTTextEmbedder, \
    SBERTLabelEmbedder, SBERTDocumentSentenceEmbedder
from wannadb.preprocessing.extraction import StanzaNERExtractor, SpacyNERExtractor
from wannadb.preprocessing.label_paraphrasing import OntoNotesLabelParaphraser, SplitAttributeNameLabelParaphraser
from wannadb.preprocessing.normalization import CopyNormalizer
from wannadb.preprocessing.other_processing import ContextSentenceCacher
from wannadb.resources import ResourceManager
from wannadb.statistics import Statistics
from wannadb.status import EmptyStatusCallback
from wannadb.interaction import BaseInteractionCallback


class Command(BaseCommand):
    help = "Import everything from a doc base"

    def add_arguments(self, parser):
        parser.add_argument("docbase", type=str)
        parser.add_argument("collection", type=str)
        parser.add_argument("slug", type=str)

    def handle(self, *args, **options):
        with open(options["docbase"], "rb") as file:
            document_base = DocumentBase.from_bson(file.read())

        collection = Collection.objects.create(
            name=options["collection"],
            docbase_file_path=options["docbase"],
            slug=options["slug"])

        self.stdout.write(
            self.style.SUCCESS("Created collection")
        )

        for a in document_base.attributes:
            BoxAttribute.objects.create(
                name=a.name,
                collection=collection
            )

        for i, doc in enumerate(document_base.documents):
            name = doc.name.split('\\')[-1]
            document_in_db = Document.objects.create(
                collection=collection,
                title=name,
                text=doc.text,
                slug=slugify(name)
            )
            n_to_a = {}
            for a_name, a_nuggets in doc.attribute_mappings.items():
                if len(a_nuggets) > 0:
                    n_to_a[(a_nuggets[0].start_char, a_nuggets[0].end_char)] = a_name
            print(n_to_a)

            nuggets_imported = 0
            for nugget in doc.nuggets:
                # Search for corresponding label in db
                label_name = nugget.signals["LabelSignal"]
                try:
                    label = NuggetLabel.objects.get(name=label_name)
                except NuggetLabel.DoesNotExist:
                    label = NuggetLabel.objects.create(name=label_name, color="#000000")

                n = Nugget.objects.create(
                    document=document_in_db,
                    start=nugget.start_char,
                    end=nugget.end_char,
                    value=nugget.text,
                    label=label
                )
                nuggets_imported += 1

                r = (nugget.start_char, nugget.end_char)
                if r in n_to_a.keys():
                    BoxAttributeValue.objects.create(
                        document=document_in_db,
                        box_attribute=BoxAttribute.objects.get(name=n_to_a[r], collection=collection),
                        nugget=n,
                        confidence=random.uniform(0.01, 0.8),
                        #confidence=1 - nugget["CachedDistanceSignal"]
                    )

            self.stdout.write(
                self.style.SUCCESS(f"Imported document {doc.name} with {nuggets_imported} nuggets")
            )
