# NMA stats
Malý pomocný repozitář pro denní sklizeň metadat z [NMA](https://nma.eosc.cz) a vizualizaci počtu nových záznamů (pole `created`) v kalendářní mřížce.  
Výstup (GitHUb Pages): <https://dmiksik.github.io/nma-stats/>

---
1× denně (v 03:00 UTC) GitHub Actions:
  - stáhne všechna metadata z `https://nma.eosc.cz/api/records` do JSONL souboru `records/nma_records.jsonl.gz`,
  - spočítá denní počty nově vytvořených záznamů podle pole `created`,
  - vytvoří dvě větve statistik:
    - **všechny záznamy**,
    - **jen záznamy s `metadata.publication_date` v letech 2021–2025**,
  - vygeneruje:
    - CSV a JSON souhrny ve složce `stats/`,
    - dva PNG kalendáře ve složce `docs/`,
    - HTML stránku `docs/index.html` pro GitHub Pages.
