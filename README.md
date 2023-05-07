# WannaDB: Ad-hoc SQL Queries over Text Collections

![Document collection and corresponding table.](header_image.svg)

WannaDB allows users to explore unstructured text collections by automatically organizing the relevant information
nuggets in a table. It supports ad-hoc SQL queries over text collections using a novel two-phased approach. First, a
superset of information nuggets is extracted from the texts using existing extractors such as named entity recognizers.
The extractions are then interactively matched to a structured table definition as requested by the user.

## Usage

Run `main.py` to start the WannaDB GUI.

There are also various auxiliary scripts in `scripts/` and the experimentation repository.

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

The code in this repository is the result of several scientific publications:

```
@inproceedings{mci/Hättasch2023,
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

```
@inproceedings{10.1145/3514221.3520174,
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
@article{Httasch2022ASETAS,
  title={ASET: Ad-hoc Structured Exploration of Text Collections [Extended Abstract]},
  author={Benjamin H{\"a}ttasch and Jan-Micha Bodensohn and Carsten Binnig},
  journal={ArXiv},
  year={2022},
  volume={abs/2203.04663}
}
```

```
@inproceedings{Httasch2021WannaDBAS,
  title={WannaDB: Ad-hoc Structured Exploration of Text Collections Using Queries},
  author={Benjamin H{\"a}ttasch},
  booktitle={Biennial Conference on Design of Experimental Search \& Information Retrieval Systems},
  year={2021}
}
```
