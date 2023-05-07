import json
import logging
from typing import Any, Dict, List, Optional, Union

logger: logging.Logger = logging.getLogger(__name__)


class Statistics:
    """
    Statistics to collect information during execution.

    A statistics object allows the pipeline and its pipeline elements to record information during their execution. The
    statistics object is provided to the pipeline or pipeline element when applying it to the document base.

    In contrast to a basic Python dictionary, the statistics object can easily be configured as to whether it actually
    should record any information. This unclutters the code required in the pipeline / pipeline element implementation.
    Furthermore, it can be used as a counter for integer and float values without requiring initialization.
    """

    def __init__(self, do_collect: bool = True) -> None:
        """
        Initialize the Statistics.

        :param do_collect: whether to actually collect statistics
        """
        super(Statistics, self).__init__()
        self._do_collect: bool = do_collect
        if self._do_collect:
            self._entries: Optional[Dict[str, Union[Statistics, Any]]] = {}
        else:
            self._entries: Optional[Dict[str, Union[Statistics, Any]]] = None

    def __str__(self) -> str:
        if self._do_collect:
            return json.dumps(self.to_serializable(), indent=4)
        else:
            return "not-collecting-statistics"

    def __repr__(self) -> str:
        return f"Statistics({self._do_collect})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Statistics) and \
            self._do_collect == other._do_collect and self._entries == other._entries

    def __getitem__(self, item: str) -> Union["Statistics", Any]:
        if self._do_collect:
            if item not in self._entries.keys():
                self._entries[item] = Statistics(True)
            return self._entries[item]
        else:
            return Statistics(False)

    def __setitem__(self, key: str, value: Union["Statistics", Any]) -> None:
        if self._do_collect:
            self._entries[key] = value

    def __iadd__(self, other: Union[int, float]) -> Union[int, float]:
        return other

    def __isub__(self, other: Union[int, float]) -> Union[int, float]:
        return -other

    def add(self, other):
        # dummy method in case this is a no-collect statistics object that replaces a set
        pass

    def append(self, other):
        # dummy method in case this is a no-collect statistics object that replaces a list
        pass

    def all_keys(self) -> List[str]:
        return list(self._entries.keys())

    def all_values(self) -> List[Union["Statistics", Any]]:
        return list(self._entries.values())

    def to_serializable(self) -> Dict[str, Any]:
        if self._do_collect:
            d: Dict[str, Union[Dict, Any]] = {}
            for key, entry in self._entries.items():
                if isinstance(entry, Statistics):
                    d[key] = entry.to_serializable()
                elif isinstance(entry, set):
                    d[key] = list(entry)
                else:
                    d[key] = entry
            return d
        else:
            return {"message": "not-collecting-statistics"}
