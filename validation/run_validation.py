#!/usr/bin/env python3
"""
THOTH Validation Suite - FLORES+ Benchmark Evaluation

This script evaluates THOTH's translation engines (NLLB-200 and Argos Translate)
using the FLORES+ dataset, calculating chrF and BLEU scores across multiple languages.
"""

import csv
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import sacrebleu

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from translator import Config, NLLBEngine, ArgosEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# LANGUAGE MAPPINGS
# ============================================================================

# FLORES+ uses NLLB-style codes for language identification
# Map from FLORES+ language codes to our internal representation

LANGUAGE_TIERS = {
    "tier1_critical": [
        ("rus_Cyrl", "Russian"),
        ("ukr_Cyrl", "Ukrainian"),
        ("lit_Latn", "Lithuanian"),
        ("lvs_Latn", "Latvian"),
        ("est_Latn", "Estonian"),
    ],
    "tier2_important": [
        ("srp_Cyrl", "Serbian"),
        ("bul_Cyrl", "Bulgarian"),
        ("pol_Latn", "Polish"),
        ("ces_Latn", "Czech"),
        ("ell_Grek", "Greek"),
    ],
    "tier3_coverage": [
        ("zho_Hans", "Chinese (Simplified)"),
        ("jpn_Jpan", "Japanese"),
        ("kor_Hang", "Korean"),
        ("arb_Arab", "Arabic"),  # FLORES+ uses arb_Arab for Modern Standard Arabic
        ("fra_Latn", "French"),
        ("deu_Latn", "German"),
        ("spa_Latn", "Spanish"),
        ("nob_Latn", "Norwegian Bokmål"),
    ],
}

# Map NLLB codes to Argos ISO 639-1 codes
NLLB_TO_ARGOS = {
    "rus_Cyrl": "ru",
    "ukr_Cyrl": "uk",
    "lit_Latn": "lt",
    "lvs_Latn": "lv",
    "est_Latn": "et",
    "srp_Cyrl": "sr",
    "bul_Cyrl": "bg",
    "pol_Latn": "pl",
    "ces_Latn": "cs",
    "ell_Grek": "el",
    "zho_Hans": "zh",
    "jpn_Jpan": "ja",
    "kor_Hang": "ko",
    "arb_Arab": "ar",
    "fra_Latn": "fr",
    "deu_Latn": "de",
    "spa_Latn": "es",
    "nob_Latn": "nb",
}

# FLORES+ column naming convention
# The dataset has columns like 'sentence_rus_Cyrl', 'sentence_eng_Latn', etc.


@dataclass
class TranslationScore:
    """Score for a single translation."""
    source_lang: str
    lang_name: str
    engine: str
    chrf: float
    bleu: float
    num_sentences: int
    translation_time: float
    errors: int = 0
    error_messages: list = field(default_factory=list)


@dataclass
class ValidationResults:
    """Complete validation results."""
    scores: list
    start_time: datetime
    end_time: datetime
    total_translations: int
    total_errors: int

    def get_scores_by_engine(self, engine: str) -> list:
        return [s for s in self.scores if s.engine == engine]

    def get_scores_by_language(self, lang_code: str) -> list:
        return [s for s in self.scores if s.source_lang == lang_code]


class THOTHValidator:
    """Validates THOTH translation engines against FLORES+ benchmark."""

    def __init__(self, sample_size: int = 200, output_dir: str = "validation_results"):
        self.sample_size = sample_size
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Load config and engines
        self.config = Config.load()
        self.nllb_engine: Optional[NLLBEngine] = None
        self.argos_engine: Optional[ArgosEngine] = None

        # Results storage
        self.results: list[TranslationScore] = []
        self.detailed_results: list[dict] = []

    def load_engines(self):
        """Load translation engines."""
        logger.info("Loading NLLB engine...")
        self.nllb_engine = NLLBEngine(str(self.config.get_nllb_path()))
        self.nllb_engine.load_model()
        logger.info("NLLB engine loaded.")

        logger.info("Loading Argos engine...")
        self.argos_engine = ArgosEngine()
        self.argos_engine.load_model()
        installed = self.argos_engine.get_installed_languages()
        logger.info(f"Argos engine loaded. Installed languages: {installed}")

    def load_flores_dataset(self) -> dict:
        """Load FLORES-200 dataset from local files."""
        logger.info("Loading FLORES-200 dataset from local files...")

        # Path to downloaded FLORES-200 data
        flores_dir = Path(__file__).parent / "flores_data" / "flores200_dataset" / "devtest"

        if not flores_dir.exists():
            raise FileNotFoundError(
                f"FLORES-200 data not found at {flores_dir}. "
                "Please download from https://tinyurl.com/flores200dataset"
            )

        # Load all language files into a dictionary
        dataset = {"sentences": {}, "num_sentences": 0}

        for lang_file in flores_dir.glob("*.devtest"):
            lang_code = lang_file.stem  # e.g., 'rus_Cyrl' from 'rus_Cyrl.devtest'
            with open(lang_file, 'r', encoding='utf-8') as f:
                sentences = [line.strip() for line in f.readlines()]
            dataset["sentences"][lang_code] = sentences
            if dataset["num_sentences"] == 0:
                dataset["num_sentences"] = len(sentences)

        logger.info(f"Dataset loaded with {dataset['num_sentences']} sentences per language")
        logger.info(f"Languages available: {len(dataset['sentences'])}")

        # Sample for practical runtime
        if self.sample_size < dataset["num_sentences"]:
            logger.info(f"Sampling {self.sample_size} sentences for evaluation")
            # Use deterministic sampling for reproducibility
            total = dataset["num_sentences"]
            step = total // self.sample_size
            indices = list(range(0, total, step))[:self.sample_size]

            for lang_code in dataset["sentences"]:
                dataset["sentences"][lang_code] = [
                    dataset["sentences"][lang_code][i] for i in indices
                ]
            dataset["num_sentences"] = len(indices)

        return dataset

    def get_sentences(self, dataset: dict, lang_code: str) -> list:
        """Get sentences for a language from the dataset."""
        return dataset["sentences"].get(lang_code, [])

    def evaluate_nllb(self, dataset, source_lang: str, lang_name: str) -> TranslationScore:
        """Evaluate NLLB engine for a language pair."""
        logger.info(f"Evaluating NLLB: {lang_name} ({source_lang}) -> English")

        # Get source and reference sentences
        source_sentences = self.get_sentences(dataset, source_lang)
        reference_translations = self.get_sentences(dataset, "eng_Latn")

        # Check if language exists in dataset
        if not source_sentences:
            logger.warning(f"Language {source_lang} not found in dataset")
            return TranslationScore(
                source_lang=source_lang,
                lang_name=lang_name,
                engine="NLLB",
                chrf=0.0,
                bleu=0.0,
                num_sentences=0,
                translation_time=0.0,
                errors=1,
                error_messages=[f"Language {source_lang} not found in dataset"]
            )

        # Translate
        translations = []
        errors = 0
        error_msgs = []
        start_time = time.time()

        for i, src_text in enumerate(source_sentences):
            try:
                result = self.nllb_engine.translate(src_text, source_lang, "eng_Latn")
                if result.success:
                    translations.append(result.translated_text)
                else:
                    translations.append("")
                    errors += 1
                    if len(error_msgs) < 5:
                        error_msgs.append(result.error or "Unknown error")
            except Exception as e:
                translations.append("")
                errors += 1
                if len(error_msgs) < 5:
                    error_msgs.append(str(e))

            if (i + 1) % 50 == 0:
                logger.info(f"  Translated {i + 1}/{len(source_sentences)} sentences")

        translation_time = time.time() - start_time

        # Calculate scores
        # chrF score
        chrf = sacrebleu.corpus_chrf(translations, [reference_translations])

        # BLEU score
        bleu = sacrebleu.corpus_bleu(translations, [reference_translations])

        # Store sample detailed results
        for i in range(min(10, len(translations))):
            self.detailed_results.append({
                "source_lang": source_lang,
                "lang_name": lang_name,
                "engine": "NLLB",
                "source": source_sentences[i][:200],  # Truncate for readability
                "translation": translations[i][:200],
                "reference": reference_translations[i][:200],
            })

        return TranslationScore(
            source_lang=source_lang,
            lang_name=lang_name,
            engine="NLLB",
            chrf=chrf.score,
            bleu=bleu.score,
            num_sentences=len(translations),
            translation_time=translation_time,
            errors=errors,
            error_messages=error_msgs
        )

    def evaluate_argos(self, dataset, source_lang: str, lang_name: str) -> TranslationScore:
        """Evaluate Argos engine for a language pair."""
        argos_code = NLLB_TO_ARGOS.get(source_lang)

        if argos_code is None:
            logger.warning(f"No Argos mapping for {source_lang}")
            return TranslationScore(
                source_lang=source_lang,
                lang_name=lang_name,
                engine="Argos",
                chrf=0.0,
                bleu=0.0,
                num_sentences=0,
                translation_time=0.0,
                errors=1,
                error_messages=["NOT_SUPPORTED: No language code mapping"]
            )

        installed = self.argos_engine.get_installed_languages()
        if argos_code not in installed:
            logger.warning(f"Argos language pack for {argos_code} not installed")
            return TranslationScore(
                source_lang=source_lang,
                lang_name=lang_name,
                engine="Argos",
                chrf=0.0,
                bleu=0.0,
                num_sentences=0,
                translation_time=0.0,
                errors=1,
                error_messages=[f"NOT_SUPPORTED: Language pack {argos_code} not installed"]
            )

        logger.info(f"Evaluating Argos: {lang_name} ({argos_code}) -> English")

        # Get source and reference sentences
        source_sentences = self.get_sentences(dataset, source_lang)
        reference_translations = self.get_sentences(dataset, "eng_Latn")

        if not source_sentences:
            logger.warning(f"Language {source_lang} not found in dataset")
            return TranslationScore(
                source_lang=source_lang,
                lang_name=lang_name,
                engine="Argos",
                chrf=0.0,
                bleu=0.0,
                num_sentences=0,
                translation_time=0.0,
                errors=1,
                error_messages=[f"Language {source_lang} not found in dataset"]
            )

        # Translate
        translations = []
        errors = 0
        error_msgs = []
        start_time = time.time()

        for i, src_text in enumerate(source_sentences):
            try:
                result = self.argos_engine.translate(src_text, argos_code, "en")
                if result.success:
                    translations.append(result.translated_text)
                else:
                    translations.append("")
                    errors += 1
                    if len(error_msgs) < 5:
                        error_msgs.append(result.error or "Unknown error")
            except Exception as e:
                translations.append("")
                errors += 1
                if len(error_msgs) < 5:
                    error_msgs.append(str(e))

            if (i + 1) % 50 == 0:
                logger.info(f"  Translated {i + 1}/{len(source_sentences)} sentences")

        translation_time = time.time() - start_time

        # Calculate scores
        chrf = sacrebleu.corpus_chrf(translations, [reference_translations])
        bleu = sacrebleu.corpus_bleu(translations, [reference_translations])

        # Store sample detailed results
        for i in range(min(10, len(translations))):
            self.detailed_results.append({
                "source_lang": source_lang,
                "lang_name": lang_name,
                "engine": "Argos",
                "source": source_sentences[i][:200],
                "translation": translations[i][:200],
                "reference": reference_translations[i][:200],
            })

        return TranslationScore(
            source_lang=source_lang,
            lang_name=lang_name,
            engine="Argos",
            chrf=chrf.score,
            bleu=bleu.score,
            num_sentences=len(translations),
            translation_time=translation_time,
            errors=errors,
            error_messages=error_msgs
        )

    def run_validation(self) -> ValidationResults:
        """Run complete validation across all languages."""
        start_time = datetime.now()

        # Load engines
        self.load_engines()

        # Load dataset
        dataset = self.load_flores_dataset()

        available_langs = list(dataset["sentences"].keys())
        logger.info(f"Available languages: {len(available_langs)}")

        # Evaluate all languages
        all_languages = []
        for tier_name, languages in LANGUAGE_TIERS.items():
            logger.info(f"\n{'='*60}")
            logger.info(f"Evaluating {tier_name.upper()}")
            logger.info(f"{'='*60}")
            all_languages.extend(languages)

        for lang_code, lang_name in all_languages:
            logger.info(f"\n--- {lang_name} ({lang_code}) ---")

            # Evaluate NLLB
            nllb_score = self.evaluate_nllb(dataset, lang_code, lang_name)
            self.results.append(nllb_score)
            logger.info(f"NLLB: chrF={nllb_score.chrf:.2f}, BLEU={nllb_score.bleu:.2f}")

            # Evaluate Argos
            argos_score = self.evaluate_argos(dataset, lang_code, lang_name)
            self.results.append(argos_score)
            if argos_score.errors == 0 or "NOT_SUPPORTED" not in str(argos_score.error_messages):
                logger.info(f"Argos: chrF={argos_score.chrf:.2f}, BLEU={argos_score.bleu:.2f}")
            else:
                logger.info(f"Argos: {argos_score.error_messages[0]}")

        end_time = datetime.now()

        return ValidationResults(
            scores=self.results,
            start_time=start_time,
            end_time=end_time,
            total_translations=sum(s.num_sentences for s in self.results),
            total_errors=sum(s.errors for s in self.results)
        )

    def generate_reports(self, results: ValidationResults):
        """Generate all output reports."""
        logger.info("\nGenerating reports...")

        self._generate_scores_by_language_csv()
        self._generate_scores_by_engine_csv()
        self._generate_detailed_results_csv()
        self._generate_engine_recommendations()
        self._generate_summary_report(results)

        logger.info(f"Reports saved to {self.output_dir}")

    def _generate_scores_by_language_csv(self):
        """Generate scores_by_language.csv"""
        filepath = self.output_dir / "scores_by_language.csv"

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Language Code", "Language Name", "Engine",
                "chrF Score", "BLEU Score", "Sentences",
                "Time (s)", "Errors", "Status"
            ])

            for score in self.results:
                status = "OK" if score.errors == 0 else (
                    "NOT_SUPPORTED" if "NOT_SUPPORTED" in str(score.error_messages) else "ERRORS"
                )
                writer.writerow([
                    score.source_lang,
                    score.lang_name,
                    score.engine,
                    f"{score.chrf:.2f}",
                    f"{score.bleu:.2f}",
                    score.num_sentences,
                    f"{score.translation_time:.1f}",
                    score.errors,
                    status
                ])

    def _generate_scores_by_engine_csv(self):
        """Generate scores_by_engine.csv with aggregate statistics."""
        filepath = self.output_dir / "scores_by_engine.csv"

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Engine", "Languages Evaluated", "Mean chrF", "Std chrF",
                "Min chrF", "Max chrF", "Mean BLEU", "Std BLEU",
                "Total Sentences", "Total Errors", "Total Time (s)"
            ])

            for engine in ["NLLB", "Argos"]:
                engine_scores = [s for s in self.results if s.engine == engine and s.num_sentences > 0]

                if not engine_scores:
                    writer.writerow([engine, 0, "N/A", "N/A", "N/A", "N/A", "N/A", "N/A", 0, 0, 0])
                    continue

                chrfs = [s.chrf for s in engine_scores]
                bleus = [s.bleu for s in engine_scores]

                import statistics
                mean_chrf = statistics.mean(chrfs) if chrfs else 0
                std_chrf = statistics.stdev(chrfs) if len(chrfs) > 1 else 0
                mean_bleu = statistics.mean(bleus) if bleus else 0
                std_bleu = statistics.stdev(bleus) if len(bleus) > 1 else 0

                writer.writerow([
                    engine,
                    len(engine_scores),
                    f"{mean_chrf:.2f}",
                    f"{std_chrf:.2f}",
                    f"{min(chrfs):.2f}",
                    f"{max(chrfs):.2f}",
                    f"{mean_bleu:.2f}",
                    f"{std_bleu:.2f}",
                    sum(s.num_sentences for s in engine_scores),
                    sum(s.errors for s in engine_scores),
                    f"{sum(s.translation_time for s in engine_scores):.1f}"
                ])

    def _generate_detailed_results_csv(self):
        """Generate detailed_results.csv with sample translations."""
        filepath = self.output_dir / "detailed_results.csv"

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Source Language", "Language Name", "Engine",
                "Source Text", "Translation", "Reference"
            ])

            for result in self.detailed_results:
                writer.writerow([
                    result["source_lang"],
                    result["lang_name"],
                    result["engine"],
                    result["source"],
                    result["translation"],
                    result["reference"]
                ])

    def _generate_engine_recommendations(self):
        """Generate engine_recommendations.md"""
        filepath = self.output_dir / "engine_recommendations.md"

        # Group results by language
        lang_comparisons = {}
        for score in self.results:
            if score.source_lang not in lang_comparisons:
                lang_comparisons[score.source_lang] = {"name": score.lang_name}
            lang_comparisons[score.source_lang][score.engine] = score

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("# Engine Recommendations by Language\n\n")
            f.write("Based on FLORES+ benchmark evaluation, these are the recommended engines for each language.\n\n")

            f.write("## Recommendation Criteria\n\n")
            f.write("- **Primary metric**: chrF score (better for morphologically rich languages)\n")
            f.write("- **Secondary metric**: BLEU score (for literature comparability)\n")
            f.write("- **Availability**: Argos may not support all languages\n\n")

            # Language families
            families = {
                "Slavic Languages": ["rus_Cyrl", "ukr_Cyrl", "pol_Latn", "ces_Latn", "bul_Cyrl", "srp_Cyrl"],
                "Baltic Languages": ["lit_Latn", "lvs_Latn", "est_Latn"],
                "Western European": ["fra_Latn", "deu_Latn", "spa_Latn", "nob_Latn"],
                "East Asian": ["zho_Hans", "jpn_Jpan", "kor_Hang"],
                "Other": ["ell_Grek", "arb_Arab"]
            }

            for family_name, family_langs in families.items():
                f.write(f"## {family_name}\n\n")
                f.write("| Language | NLLB chrF | Argos chrF | Recommendation |\n")
                f.write("|----------|-----------|------------|----------------|\n")

                for lang_code in family_langs:
                    if lang_code not in lang_comparisons:
                        continue

                    comp = lang_comparisons[lang_code]
                    lang_name = comp["name"]

                    nllb = comp.get("NLLB")
                    argos = comp.get("Argos")

                    nllb_chrf = f"{nllb.chrf:.1f}" if nllb and nllb.num_sentences > 0 else "N/A"
                    argos_chrf = "N/A"
                    argos_supported = False

                    if argos:
                        if argos.num_sentences > 0 and "NOT_SUPPORTED" not in str(argos.error_messages):
                            argos_chrf = f"{argos.chrf:.1f}"
                            argos_supported = True

                    # Determine recommendation
                    if not argos_supported:
                        recommendation = "**NLLB** (Argos not available)"
                    elif nllb and argos and nllb.num_sentences > 0 and argos.num_sentences > 0:
                        if nllb.chrf > argos.chrf + 2:  # NLLB significantly better
                            recommendation = "**NLLB**"
                        elif argos.chrf > nllb.chrf + 2:  # Argos significantly better
                            recommendation = "**Argos**"
                        else:
                            recommendation = "Either (similar quality)"
                    else:
                        recommendation = "**NLLB** (default)"

                    f.write(f"| {lang_name} | {nllb_chrf} | {argos_chrf} | {recommendation} |\n")

                f.write("\n")

            f.write("## Summary\n\n")
            f.write("### Key Findings\n\n")

            # Count recommendations
            nllb_wins = 0
            argos_wins = 0
            ties = 0
            argos_unsupported = 0

            for lang_code, comp in lang_comparisons.items():
                nllb = comp.get("NLLB")
                argos = comp.get("Argos")

                if not argos or argos.num_sentences == 0 or "NOT_SUPPORTED" in str(argos.error_messages):
                    argos_unsupported += 1
                elif nllb and argos and nllb.num_sentences > 0 and argos.num_sentences > 0:
                    if nllb.chrf > argos.chrf + 2:
                        nllb_wins += 1
                    elif argos.chrf > nllb.chrf + 2:
                        argos_wins += 1
                    else:
                        ties += 1

            f.write(f"- NLLB recommended: {nllb_wins} languages\n")
            f.write(f"- Argos recommended: {argos_wins} languages\n")
            f.write(f"- Similar quality: {ties} languages\n")
            f.write(f"- Argos not available: {argos_unsupported} languages\n")

    def _generate_summary_report(self, results: ValidationResults):
        """Generate summary_report.md"""
        filepath = self.output_dir / "summary_report.md"

        # Calculate aggregate stats
        nllb_scores = [s for s in self.results if s.engine == "NLLB" and s.num_sentences > 0]
        argos_scores = [s for s in self.results if s.engine == "Argos" and s.num_sentences > 0
                        and "NOT_SUPPORTED" not in str(s.error_messages)]

        import statistics

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("# THOTH Validation Report\n\n")
            f.write(f"**Generated**: {results.end_time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"**Evaluation Dataset**: FLORES-200 (facebook/flores200)\n\n")
            f.write(f"**Sample Size**: {self.sample_size} sentences per language\n\n")

            f.write("## Executive Summary\n\n")

            duration = (results.end_time - results.start_time).total_seconds()
            f.write(f"This validation evaluated THOTH's two translation engines against the FLORES+ benchmark.\n\n")
            f.write(f"- **Total translations**: {results.total_translations:,}\n")
            f.write(f"- **Total errors**: {results.total_errors}\n")
            f.write(f"- **Evaluation time**: {duration/60:.1f} minutes\n\n")

            f.write("## Score Comparison Table\n\n")
            f.write("### All Languages (chrF Score)\n\n")
            f.write("| Language | NLLB chrF | NLLB BLEU | Argos chrF | Argos BLEU | Winner |\n")
            f.write("|----------|-----------|-----------|------------|------------|--------|\n")

            # Group by language
            lang_map = {}
            for score in self.results:
                if score.source_lang not in lang_map:
                    lang_map[score.source_lang] = {"name": score.lang_name}
                lang_map[score.source_lang][score.engine] = score

            for lang_code in lang_map:
                comp = lang_map[lang_code]
                lang_name = comp["name"]
                nllb = comp.get("NLLB")
                argos = comp.get("Argos")

                nllb_chrf = f"{nllb.chrf:.1f}" if nllb and nllb.num_sentences > 0 else "N/A"
                nllb_bleu = f"{nllb.bleu:.1f}" if nllb and nllb.num_sentences > 0 else "N/A"

                if argos and argos.num_sentences > 0 and "NOT_SUPPORTED" not in str(argos.error_messages):
                    argos_chrf = f"{argos.chrf:.1f}"
                    argos_bleu = f"{argos.bleu:.1f}"

                    # Determine winner
                    if nllb and nllb.num_sentences > 0:
                        if nllb.chrf > argos.chrf + 2:
                            winner = "NLLB"
                        elif argos.chrf > nllb.chrf + 2:
                            winner = "Argos"
                        else:
                            winner = "Tie"
                    else:
                        winner = "Argos"
                else:
                    argos_chrf = "N/A"
                    argos_bleu = "N/A"
                    winner = "NLLB*"

                f.write(f"| {lang_name} | {nllb_chrf} | {nllb_bleu} | {argos_chrf} | {argos_bleu} | {winner} |\n")

            f.write("\n*\\* Argos not available for this language*\n\n")

            f.write("## Aggregate Statistics\n\n")
            f.write("### NLLB-200\n\n")
            if nllb_scores:
                chrfs = [s.chrf for s in nllb_scores]
                bleus = [s.bleu for s in nllb_scores]
                f.write(f"- **Languages evaluated**: {len(nllb_scores)}\n")
                f.write(f"- **Mean chrF**: {statistics.mean(chrfs):.2f} (std: {statistics.stdev(chrfs) if len(chrfs) > 1 else 0:.2f})\n")
                f.write(f"- **Mean BLEU**: {statistics.mean(bleus):.2f} (std: {statistics.stdev(bleus) if len(bleus) > 1 else 0:.2f})\n")
                f.write(f"- **chrF range**: {min(chrfs):.1f} - {max(chrfs):.1f}\n")
                f.write(f"- **Total translation time**: {sum(s.translation_time for s in nllb_scores):.1f}s\n\n")

            f.write("### Argos Translate\n\n")
            if argos_scores:
                chrfs = [s.chrf for s in argos_scores]
                bleus = [s.bleu for s in argos_scores]
                f.write(f"- **Languages evaluated**: {len(argos_scores)}\n")
                f.write(f"- **Mean chrF**: {statistics.mean(chrfs):.2f} (std: {statistics.stdev(chrfs) if len(chrfs) > 1 else 0:.2f})\n")
                f.write(f"- **Mean BLEU**: {statistics.mean(bleus):.2f} (std: {statistics.stdev(bleus) if len(bleus) > 1 else 0:.2f})\n")
                f.write(f"- **chrF range**: {min(chrfs):.1f} - {max(chrfs):.1f}\n")
                f.write(f"- **Total translation time**: {sum(s.translation_time for s in argos_scores):.1f}s\n\n")
            else:
                f.write("*No Argos languages were successfully evaluated*\n\n")

            f.write("## Tier Analysis\n\n")

            for tier_name, tier_display in [
                ("tier1_critical", "Tier 1 - Critical Languages"),
                ("tier2_important", "Tier 2 - Important Languages"),
                ("tier3_coverage", "Tier 3 - Coverage Languages")
            ]:
                f.write(f"### {tier_display}\n\n")
                tier_langs = [l[0] for l in LANGUAGE_TIERS[tier_name]]

                tier_nllb = [s for s in nllb_scores if s.source_lang in tier_langs]
                tier_argos = [s for s in argos_scores if s.source_lang in tier_langs]

                if tier_nllb:
                    mean_nllb = statistics.mean([s.chrf for s in tier_nllb])
                    f.write(f"- **NLLB mean chrF**: {mean_nllb:.2f} ({len(tier_nllb)} languages)\n")

                if tier_argos:
                    mean_argos = statistics.mean([s.chrf for s in tier_argos])
                    f.write(f"- **Argos mean chrF**: {mean_argos:.2f} ({len(tier_argos)} languages)\n")

                f.write("\n")

            f.write("## Recommendations\n\n")
            f.write("Based on this evaluation:\n\n")

            f.write("1. **Default Engine**: Use NLLB-200 as the primary engine due to:\n")
            f.write("   - Broader language coverage (200 languages vs ~45 for Argos)\n")
            f.write("   - Consistent quality across language families\n")
            f.write("   - Support for all critical Tier 1 languages\n\n")

            f.write("2. **When to consider Argos**:\n")

            # Find languages where Argos is better
            argos_better = []
            for lang_code, comp in lang_map.items():
                nllb = comp.get("NLLB")
                argos = comp.get("Argos")
                if (argos and argos.num_sentences > 0 and
                    "NOT_SUPPORTED" not in str(argos.error_messages) and
                    nllb and nllb.num_sentences > 0):
                    if argos.chrf > nllb.chrf + 2:
                        argos_better.append(f"{comp['name']} (+{argos.chrf - nllb.chrf:.1f} chrF)")

            if argos_better:
                f.write(f"   - Languages where Argos outperforms: {', '.join(argos_better)}\n")
            else:
                f.write("   - No languages where Argos significantly outperforms NLLB in this evaluation\n")

            f.write("\n3. **Language-specific notes**:\n")

            # Note any low-performing languages
            low_perf = [s for s in nllb_scores if s.chrf < 40]
            if low_perf:
                f.write(f"   - Lower quality observed for: {', '.join(s.lang_name for s in low_perf)}\n")

            f.write("\n## Output Files\n\n")
            f.write("| File | Description |\n")
            f.write("|------|-------------|\n")
            f.write("| `summary_report.md` | This executive summary |\n")
            f.write("| `scores_by_language.csv` | Per-language chrF and BLEU scores |\n")
            f.write("| `scores_by_engine.csv` | Aggregate statistics per engine |\n")
            f.write("| `detailed_results.csv` | Sample sentence-level results |\n")
            f.write("| `engine_recommendations.md` | Engine recommendations by language |\n")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="THOTH Validation Suite")
    parser.add_argument(
        "--sample-size", "-n",
        type=int,
        default=200,
        help="Number of sentences to evaluate per language (default: 200)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="validation_results",
        help="Output directory for results (default: validation_results)"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("THOTH Validation Suite")
    print("FLORES+ Benchmark Evaluation")
    print("=" * 60)
    print()

    validator = THOTHValidator(
        sample_size=args.sample_size,
        output_dir=args.output_dir
    )

    try:
        results = validator.run_validation()
        validator.generate_reports(results)

        print()
        print("=" * 60)
        print("Validation Complete!")
        print("=" * 60)
        print(f"Results saved to: {validator.output_dir}")
        print()
        print("Generated files:")
        for f in validator.output_dir.iterdir():
            print(f"  - {f.name}")

    except KeyboardInterrupt:
        print("\nValidation interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        raise


if __name__ == "__main__":
    main()
