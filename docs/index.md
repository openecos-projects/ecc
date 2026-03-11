# ChipCompiler Documentation

Welcome to the ChipCompiler documentation center.

## Core Documentation

- **[Architecture](architecture.md)** - Detailed system architecture and design patterns
  - Layered architecture explanation
  - Core design patterns
  - Data flow and execution paths
  - Module details

- **[Development Guide](development.md)** - Development environment setup and workflows
  - Environment configuration
  - Code quality tools
  - Adding new EDA tools
  - Debugging and testing

## Technical Specifications

### File Format Specifications

ChipCompiler supports various EDA file formats. Technical specifications for parser implementations:

- **[Filelist Grammar](specification/filelist-grammar.md)** - EBNF grammar for EDA tool filelists
  - Supports file paths, +incdir directives, comments, quoted paths
  - Parser implementation: `chipcompiler/utility/filelist.py`

## Quick Navigation

### I want to...

- **Get started with ChipCompiler** → See main [README](../README.md)
- **Understand the architecture** → [Architecture](architecture.md)
- **Set up development environment** → [Development Guide](development.md)
- **Add new tools** → [Development Guide - Adding EDA Tools](development.md#adding-new-eda-tools)
- **Debug workflows** → [Development Guide - Debugging](development.md#debugging-workflow-steps)

## Additional Resources

- [Main README](../README.md)
