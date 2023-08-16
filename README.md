# WannaDB: Ad-hoc SQL Queries over Text Collections

![Document collection and corresponding table.](header_image.svg)

WannaDB allows users to explore unstructured text collections by automatically organizing the relevant information nuggets in a table. It supports ad-hoc SQL queries over text collections using a novel two-phased approach: First, a superset of information nuggets is extracted from the texts using existing extractors such as named entity recognizers. The extractions are then interactively matched to a structured table definition as requested by the user.

Watch our [demo video](https://link.tuda.systems/aset-video) or [read our paper](https://doi.org/10.18420/BTW2023-08) to learn more about the usage and underlying concepts.

## Usage

Run `main.py` to start the WannaDB GUI.

There are also various auxiliary scripts in `scripts/` and the experimentation repository (coming soon).

## Installation

This project requires Python 3.9.

##### 1. Create a virtual environment.

```
python -m venv venv
source venv/bin/activate
export PYTHONPATH="."
```

##### 2. Install the dependencies.

```
pip install --upgrade pip
pip install --use-pep517 -r requirements.txt
pip install --use-pep517 pytest
```

You may have to install `torch` by hand if you want to use CUDA:

https://pytorch.org/get-started/locally/

##### 3. Run the tests.

```
pytest
```

## Citing WannaDB

The code in this repository is the result of several scientific publications. If you build upon WannaDB, please cite:

```
@inproceedings{wannadb@BTW23,
author = {Hättasch, Benjamin AND Bodensohn, Jan-Micha AND Vogel, Liane AND Urban, Matthias AND Binnig, Carsten},
title = {WannaDB: Ad-hoc SQL Queries over Text Collections},
booktitle = {BTW 2023},
year = {2023},
editor = {König-Ries, Birgitta AND Scherzinger, Stefanie AND Lehner, Wolfgang AND Vossen, Gottfried} ,
doi = { 10.18420/BTW2023-08 },
publisher = {Gesellschaft für Informatik e.V.},
address = {}
}
```

If you want to reference specific features/parts, our further publications might be relevant:

```
@inproceedings{aset@SIGMOD22,
author = {H\"{a}ttasch, Benjamin and Bodensohn, Jan-Micha and Binnig, Carsten},
title = {Demonstrating ASET: Ad-Hoc Structured Exploration of Text Collections},
year = {2022},
isbn = {9781450392495},
publisher = {Association for Computing Machinery},
address = {New York, NY, USA},
url = {https://doi.org/10.1145/3514221.3520174},
doi = {10.1145/3514221.3520174},
abstract = {In this demo, we present ASET, a novel tool to explore the contents of unstructured data (text) by automatically transforming relevant parts into tabular form. ASET works in an ad-hoc manner without the need to curate extraction pipelines for the (unseen) text collection or to annotate large amounts of training data. The main idea is to use a new two-phased approach that first extracts a superset of information nuggets from the texts using existing extractors such as named entity recognizers. In a second step, it leverages embeddings and a novel matching strategy to match the extractions to a structured table definition as requested by the user. This demo features the ASET system with a graphical user interface that allows people without machine learning or programming expertise to explore text collections efficiently. This can be done in a self-directed and flexible manner, and ASET provides an intuitive impression of the result quality.},
booktitle = {Proceedings of the 2022 International Conference on Management of Data},
pages = {2393–2396},
numpages = {4},
keywords = {matching embeddings, text to table, interactive text exploration},
location = {Philadelphia, PA, USA},
series = {SIGMOD '22}
}
```

```
@inproceedings{aset@AIDB21,
    author = {H{\"a}ttasch, Benjamin and Bodensohn, Jan-Micha and Binnig, Carsten},
    year = "2021",
    title = "ASET: Ad-hoc Structured Exploration of Text Collections",
    eventdate = "16.-20.08.2021",
    language = "en",
    booktitle = "3rd International Workshop on Applied AI for Database Systems and Applications (AIDB21). In conjunction with the 47th International Conference on Very Large Data Bases, Copenhagen, Denmark, August 16 - 20, 2021.",
    location = "Copenhagen, Denmark"
}
```

```
@inproceedings{wannadb@DESIRES21,
    author = {H{\"{a}}ttasch, Benjamin},
    title = "WannaDB: Ad-hoc Structured Exploration of Text Collections Using Queries",
    booktitle = "Proceedings of the Second International Conference on Design of Experimental Search Information REtrieval Systems, Padova, Italy, September 15-18, 2021",
    series = "{CEUR} Workshop Proceedings",
    volume = "2950",
    pages = "179--180",
    publisher = "CEUR-WS.org",
    year = "2021",
    url = "http://ceur-ws.org/Vol-2950/paper-23.pdf",
    timestamp = "Mon, 25 Oct 2021 15:03:55 +0200",
    biburl = "https://dblp.org/rec/conf/desires/Hattasch21.bib",
    bibsource = "dblp computer science bibliography, https://dblp.org"
}
```

## License

WannaDB is dually licensed under both AGPLv3 for the free usage by end users or the embedding in Open Source projects, and a commercial license for the integration in industrial projects and closed-source tool chains. More details can be found in [our licence agreement](LICENSE.md).


## Availability of Code & Datasets

We publish the source code four our system as discussed in the papers here. Additionally, we publish code to reproduce our experiments in a separate repository (coming soon).

Unfortunately, we cannot publish the datasets online due to copyright issues. We will send them via email on request to everyone interested and hope they can be of benefit for other research, too.


## Implementation details

The core of WannaDB (extraction and matching) was previously developed by us under the name [ASET (Ad-hoc Structured Exploration of Text Collections)](https://link.tuda.systems/aset). To better reflect the whole application cycle vision we present with this paper, we switchted the name to WannaDB. 

### Repository structure

This repository is structured as follows:

* `wannadb`, `wannadb_parsql`, and `wannadb_ui` contain the implementation of ASET and the GUI.
* `scripts` contains helpers, like a stand-alone preprocessing script.
* `tests` contains pytest tests.

### Architecture: Core

The core implementation of WannaDB is in the `wannadb` package and implemented as a library. The implementation allows you to construct pipelines of different data processors that work with the data model and may involve user feedback.

**Data model**

`data` contains WannaDB's data model. The entities are `InformationNugget`s, `Attribute`s, `Document`s, and the `DocumentBase`. 

A nugget is an information piece obtained from a document. An attribute is a table column that gets
populated with information from the documents. A document is a textual document, and the document base is a collection of documents and provides facilities for `BSON` serialization, consistency checks, and data access.

`InformationNugget`s, `Attribute`s, and `Document`s can have `BaseSignal`s, which provide a way to easily store additional information with them. Each signal is identified with a unique identifier and implements the serialization and deserialization. Furthermore, some signals may not be serialized. There are base implementations for different data types like floats or numpy arrays.

**Configurations**

`configuration.py` contains the abstract pipeline code. An `Pipeline` allows you to execute multiple
`BasePipelineElement`s one after the other. These pipeline elements work on an `DocumentBase` and receive a
`BaseInteractionCallback` and `BaseStatusCallback` to facilitate user interactions and convey status updates.
Furthermore, they receive a `Statistics` object that allows them to record information during runtime.

Both `BasePipelineElement`s and the `Pipeline` are `BaseConfigurableElement`s. This means that they come with a unique identifier and provide methods to instantiate them from a given configuration dictionary and to serialize their configuration as a dictionary.

Each `BasePipelineElement` specifies which `BaseSignal`s it requires and generates for the nuggets, attributes, and documents. This ensures the consistency of the pipeline. In other words, when a pipeline element is executed, all signals it requires must be set.

**Callbacks**

`interaction.py` and `status.py` contain `BaseInteractionCallback` and `BaseStatusCallback`, which allow the pipeline elements to request user interactions and convey status updates. They come with default implementations `InteractionCallback` and `StatusCallback` that receive a callback function when initialized, and `EmptyInteractionCallback` and `EmptyStatusCallback` that simply do nothing.

**Resources**

`resources.py` contains a resource manager that allows different parts of WannaDB to share resources like embeddings or transformer models. The module implements the singleton pattern, so there is always only one `ResourceManager` accessed via `resources.MANAGER`, which handles the loading, access, and unloading of `BaseResource`s. You should use a context manager (`with ResourceManager() as resource_manager:`) to ensure that all resources are properly closed when the program stops/crashes.

Each `BaseResource` comes with a unique identifier and implements methods for loading, unloading, and access.

**Statistics**

The `Statistics` object allows you to easily record information during runtime. It is handed from the `Pipeline` to the `BasePipelineElement`s, and from the `BasePipelineElement`s to other components like distance functions.

### Architecture: GUI

The GUI implementation can be found in the `wannadb_ui` package. `wannadb_api.py` provides an asynchronous API for the `wannadb` library using PyQt's slots and signals mechanism. `main_window.py`, `document_base.py`, and `interactive_window.py` contain different parts of the user interface, and `common.py` contains base classes for some recurring user interface elements.
