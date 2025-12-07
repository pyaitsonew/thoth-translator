# Engine Recommendations by Language

Based on FLORES+ benchmark evaluation, these are the recommended engines for each language.

## Recommendation Criteria

- **Primary metric**: chrF score (better for morphologically rich languages)
- **Secondary metric**: BLEU score (for literature comparability)
- **Availability**: Argos may not support all languages

## Slavic Languages

| Language | NLLB chrF | Argos chrF | Recommendation |
|----------|-----------|------------|----------------|
| Russian | 60.3 | 62.5 | **Argos** |
| Ukrainian | 62.1 | 50.7 | **NLLB** |
| Polish | 56.6 | 56.0 | Either (similar quality) |
| Czech | 63.9 | 62.9 | Either (similar quality) |
| Bulgarian | 66.1 | N/A | **NLLB** (Argos not available) |
| Serbian | 65.6 | N/A | **NLLB** (Argos not available) |

## Baltic Languages

| Language | NLLB chrF | Argos chrF | Recommendation |
|----------|-----------|------------|----------------|
| Lithuanian | 57.6 | N/A | **NLLB** (Argos not available) |
| Latvian | 58.7 | N/A | **NLLB** (Argos not available) |
| Estonian | 61.9 | N/A | **NLLB** (Argos not available) |

## Western European

| Language | NLLB chrF | Argos chrF | Recommendation |
|----------|-----------|------------|----------------|
| French | 69.4 | 69.2 | Either (similar quality) |
| German | 67.0 | 64.2 | **NLLB** |
| Spanish | 59.9 | 53.9 | **NLLB** |
| Norwegian Bokmål | 63.9 | N/A | **NLLB** (Argos not available) |

## East Asian

| Language | NLLB chrF | Argos chrF | Recommendation |
|----------|-----------|------------|----------------|
| Chinese (Simplified) | 56.1 | 54.6 | Either (similar quality) |
| Japanese | 53.0 | 46.4 | **NLLB** |
| Korean | 55.4 | 45.6 | **NLLB** |

## Other

| Language | NLLB chrF | Argos chrF | Recommendation |
|----------|-----------|------------|----------------|
| Greek | 59.5 | 58.1 | Either (similar quality) |
| Arabic | 63.8 | 57.2 | **NLLB** |

## Summary

### Key Findings

- NLLB recommended: 6 languages
- Argos recommended: 1 languages
- Similar quality: 5 languages
- Argos not available: 6 languages
