# Documentazione Tecnica

## Struttura
- `docs/technical/main.tex` documento principale LaTeX
- `docs/technical/sections/*.tex` sezioni modulari

## Build (Windows PowerShell)

```powershell
# Dalla root del progetto
latexmk -pdf -interaction=nonstopmode -file-line-error .\docs\technical\main.tex
```

Se non hai `latexmk`, puoi usare `pdflatex` due volte:

```powershell
pdflatex .\docs\technical\main.tex
pdflatex .\docs\technical\main.tex
```
