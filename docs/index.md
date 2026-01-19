# ChipCompiler Documentation

## File Format Specifications

ChipCompiler supports various EDA file formats. These specifications document
parser implementations:

- **[Filelist Grammar](specification/filelist-grammar.md)** - EBNF grammar for EDA tool filelists
  - Supports file paths, +incdir directives, comments, and quoted paths
  - Parser implementation: `chipcompiler/utility/filelist.py`

