# Visualizations

## 3D-Grid
The 3D-Grid aims to visualize how text snippets are interpreted by the system.  
Each text snippet extracted from one of the provided documents is represented by a vector of numbers within the system. This vector contains information about the meaning of the text snippet and is called *embedding vector* or just *embedding*.  
These embedding vectors are displayed in the 3D-Grid which makes it possible to recognize that words with similar meaning are also mapped to similar embedding vectors.  
Furthermore, the grid shows where a text snippet lies relative to the current threshold. The threshold basically determines whether a found text snippet should be considered as a match or not. To learn more about it, check [this section](#threshold). 

## Cosine-Distance Bar-Chart
This bar-chart attempts to display the system-calculated confidence with which a text snippet from a document matches an attribute.  
In order to determine this certainty, the system uses the similarity between the embedding of a text snippet and the embedding of either the attribute to match or an already confirmed match for this attribute. What exactly is used the comparative value (attribute or already confirmed match) depends on which value results in a higher similarity score.  
To learn more about how this similarity is calculated, check the *Underlying architecture and ideas* help section.