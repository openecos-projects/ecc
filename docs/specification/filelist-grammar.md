# Filelist Grammar Specification

This document defines the formal grammar for the filelist parser used in ChipCompiler.

## Scope

Filelist files are used by EDA tools to specify RTL source files and compiler
options. The ChipCompiler parser supports a subset of common filelist syntax.

## Supported Syntax

- File paths (relative and absolute)
- Comments (`#`, `//`, `` ` ``)
- Empty lines
- Quoted paths (single and double quotes)
- Include directory directives (`+incdir+`)
- Inline comments

## Unsupported or Ignored

- `-f`, `-v`, `-y` are rejected with `ValueError`
- Other `+` or `-` options are ignored

## EBNF Grammar

```ebnf
(* Top-level structure *)
filelist = { line } ;

(* Line types *)
line = empty_line
     | comment_line
     | incdir_directive
     | file_path
     | unsupported_option
     | unknown_option ;

(* Empty line *)
empty_line = [ whitespace ] ;

(* Comment line *)
comment_line = [ whitespace ] comment_marker { any_char } ;
comment_marker = "#" | "//" | "`" ;

(* +incdir directive *)
incdir_directive = [ whitespace ] "+incdir+" path_value [ inline_comment ] ;

(* File path *)
file_path = [ whitespace ] path_value [ inline_comment ] ;

(* Unsupported options (raise ValueError) *)
unsupported_option = [ whitespace ] unsupported_flag { any_char } ;
unsupported_flag = "-f" | "-v" | "-y" ;

(* Other options (skipped silently) *)
unknown_option = [ whitespace ] ( "+" | "-" ) { any_char } ;

(* Path value (quoted or unquoted) *)
path_value = quoted_path | unquoted_path ;
quoted_path = ( '"' { any_char - '"' } '"' )
            | ( "'" { any_char - "'" } "'" ) ;
unquoted_path = { any_char - whitespace - "#" - "//" } ;

(* Inline comment *)
inline_comment = [ whitespace ] comment_marker { any_char } ;

(* Whitespace *)
whitespace = " " | "\t" ;

(* Any character *)
any_char = ? any Unicode character ? ;
```

## Testing

See `test/test_filelist.py` for test coverage:

- Basic filelist parsing
- `+incdir` directive parsing
- Comment handling (all types)
- Quote handling (single/double)
- Inline comment removal
- Whitespace handling (leading, trailing, tabs)
- Unsupported option detection
- Path resolution (relative/absolute)
- File validation
- Edge cases (empty files, missing files, mixed paths)

## References

- VCS User Guide - [User Guide](https://picture.iczhiku.com/resource/eetop/WhKDeOKWsJfQibVv.pdf)