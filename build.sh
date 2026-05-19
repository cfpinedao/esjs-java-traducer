#!/usr/bin/env bash
# Regenera el lexer/parser/visitor de Python desde EsJs.g4
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v antlr4 >/dev/null 2>&1; then
    echo "Error: antlr4 no esta instalado."
    echo "  Arch:  sudo pacman -S antlr4 python-antlr4"
    echo "  pip:   pip install --user antlr4-tools antlr4-python3-runtime"
    exit 1
fi

mkdir -p generated
antlr4 -Dlanguage=Python3 -visitor -o generated EsJs.g4
touch generated/__init__.py
echo "Generated parser in generated/"
ls -1 generated/*.py | sed 's/^/  /'
