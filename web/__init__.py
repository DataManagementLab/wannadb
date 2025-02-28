"""from wannadb.resources import ResourceManager
from wannadb.statistics import Statistics

import random
import time
import os
import json
import logging.config

from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import Counter

from wannadb.data.data import Attribute
from wannadb.matching.custom_match_extraction import DummyCustomMatchExtractor, FaissSentenceSimilarityExtractor
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

resource_manager = ResourceManager()
statistics = Statistics(do_collect=True)

matching_phase = Pipeline(
    [
        SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
        ContextSentenceCacher(),
        SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
        SBERTDocumentSentenceEmbedder("SBERTBertLargeNliMeanTokensResource"),
        RankingBasedMatcher(
            distance=SignalsMeanDistance(
                signal_identifiers=[
                    "LabelEmbeddingSignal",
                    "TextEmbeddingSignal",
                    "ContextSentenceEmbeddingSignal",
                    "RelativePositionSignal"
                ]
            ),
            max_num_feedback=100,
            len_ranked_list=10,
            max_distance=0.2,
            num_random_docs=1,
            sampling_mode="AT_MAX_DISTANCE_THRESHOLD",
            adjust_threshold=True,
            nugget_pipeline=Pipeline(
                [
                    ContextSentenceCacher(),
                    CopyNormalizer(),
                    OntoNotesLabelParaphraser(),
                    SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
                    SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
                    SBERTTextEmbedder("SBERTBertLargeNliMeanTokensResource"),
                    BERTContextSentenceEmbedder("BertLargeCasedResource"),
                    RelativePositionEmbedder()
                ]
            ),
            find_additional_nuggets=FaissSentenceSimilarityExtractor(num_similar_sentences=20,
                                                                     num_phrases_per_sentence=3),
            store_best_guesses=True,
        )
    ]
)
"""
