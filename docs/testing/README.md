# HAZ-v2 user testing

Material for testing HAZ-v2 with the association's staff, one tester per demo login (password `Demo@2026`, demo data only).

| File | What it is |
|---|---|
| `protocol.html` | The full protocol: 46 step-by-step test cases for every department, access checks, end-to-end scenarios and a results summary. Open it in a browser; results are kept in that browser and can be exported to CSV. |
| `pdf/HAZ-v2 test guide NN - <login>.pdf` | One printable guide per demo login: that person's cases in order, tick boxes per step, scoring and a feedback page. |
| `source/` | Rebuilds the PDFs from `protocol.html` after the test cases change. |

## Rebuilding the PDFs

```
cd docs/testing/source
pip install playwright && playwright install chromium
python fetch_fonts.py
python make.py
```

Edit the test cases in `protocol.html` (the `DEPTS` list), then run `make.py` again.

Tax, insurance and leave values in the demo are SAMPLE DATA, not legal values.
