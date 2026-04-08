from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

from score import load_yaml, resolve_venue_data, score_venue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render venue comparison markdown")
    parser.add_argument("--requirements", default=None, help="Path to requirements.yaml")
    parser.add_argument("--venues-dir", default=None, help="Path to venues directory")
    parser.add_argument("--output", default=None, help="Path to output markdown file")
    return parser.parse_args()


def discover_venues(venues_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in venues_dir.glob("*.yaml")
        if not path.name.startswith("_") and path.name != "requirements.yaml"
    )


def load_results(requirements_path: Path, venues_dir: Path) -> tuple[dict, list[dict]]:
    requirements = load_yaml(requirements_path)
    criteria = requirements.get("criteria", [])
    results: list[dict] = []

    for venue_path in discover_venues(venues_dir):
        raw = load_yaml(venue_path)
        if not isinstance(raw, dict):
            continue

        data = resolve_venue_data(raw)
        if "name" not in data:
            continue

        results.append(
            {
                "path": venue_path,
                "raw": raw,
                "data": data,
                "result": score_venue(data, criteria),
            }
        )

    results.sort(
        key=lambda entry: (
            entry["result"].get("status") == "DISQUALIFIED",
            -entry["result"].get("pct", 0),
            entry["result"].get("name", "").lower(),
        )
    )
    return requirements, results


def fmt_percent(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.1f}%"
    return "—"


def fmt_number(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.0f}" if value.is_integer() else f"{value:,.1f}"
    return str(value)


def fmt_cost_nok(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return "—"
    if isinstance(value, (int, float)):
        rounded = int(value) if float(value).is_integer() else round(float(value), 1)
        return f"NOK {rounded:,}"
    return str(value)


def fmt_text(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value.replace("|", "\\|")
    return str(value)


def build_header(requirements: dict) -> list[str]:
    event = requirements.get("event", {})
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# {event.get('name', 'Venue Comparison')}",
        "",
        f"Generated: {generated}",
    ]

    event_bits = []
    if event.get("expected_attendance") is not None:
        event_bits.append(f"Expected attendance: {event['expected_attendance']}")
    if event.get("budget_range_nok") is not None:
        event_bits.append(f"Budget range: {event['budget_range_nok']} NOK")
    if event_bits:
        lines.extend(["", "- " + "\n- ".join(event_bits)])

    return lines


def build_main_table(qualified: list[dict]) -> list[str]:
    lines = [
        "## Ranked Comparison",
        "",
        "| Rank | Venue | Score (%) | Capacity | Villages | Sponsors | Cost (NOK) | Vibe | Transport | Blockers |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]

    if not qualified:
        lines.append("| — | No qualified venues | — | — | — | — | — | — | — | — |")
        return lines

    for index, entry in enumerate(qualified, start=1):
        data = entry["data"]
        result = entry["result"]
        lines.append(
            "| {rank} | {name} | {score} | {capacity} | {villages} | {sponsors} | {cost} | {vibe} | {transport} | 0 |".format(
                rank=index,
                name=fmt_text(result.get("name")),
                score=fmt_percent(result.get("pct")),
                capacity=fmt_number(data.get("arena_capacity")),
                villages=fmt_number(data.get("village_spaces")),
                sponsors=fmt_number(data.get("sponsor_spaces")),
                cost=fmt_text(fmt_cost_nok(data.get("total_cost"))),
                vibe=fmt_text(data.get("atmosphere")),
                transport=fmt_text(data.get("transport_access")),
            )
        )

    return lines


def build_category_sections(qualified: list[dict], requirements: dict) -> list[str]:
    lines = ["## Per-Category Breakdown", ""]
    criteria = requirements.get("criteria", [])
    ordered_categories: list[str] = []
    for criterion in criteria:
        if criterion.get("requirement") == "must":
            continue
        category = criterion.get("category", "Other")
        if category not in ordered_categories:
            ordered_categories.append(category)

    if not qualified:
        lines.append("No qualified venues to compare by category.")
        return lines

    if not ordered_categories:
        lines.append("No scored categories defined in requirements.")
        return lines

    for category in ordered_categories:
        lines.extend(
            [
                f"### {category}",
                "",
                "| Venue | Score | Max | Percent |",
                "| --- | ---: | ---: | ---: |",
            ]
        )

        ranked = sorted(
            qualified,
            key=lambda entry: category_percent(entry["result"].get("categories", {}).get(category, {})),
            reverse=True,
        )
        for entry in ranked:
            category_result = entry["result"].get("categories", {}).get(category, {})
            score = category_result.get("score")
            max_score = category_result.get("max")
            lines.append(
                "| {venue} | {score} | {max_score} | {percent} |".format(
                    venue=fmt_text(entry["result"].get("name")),
                    score=fmt_number(score),
                    max_score=fmt_number(max_score),
                    percent=fmt_percent(category_percent(category_result)),
                )
            )

        lines.append("")

    if lines[-1] == "":
        lines.pop()
    return lines


def category_percent(category_result: dict) -> float:
    score = category_result.get("score")
    max_score = category_result.get("max")
    if isinstance(score, (int, float)) and isinstance(max_score, (int, float)) and max_score > 0:
        return round(score / max_score * 100, 1)
    return 0.0


def build_disqualified_section(disqualified: list[dict]) -> list[str]:
    lines = ["## Disqualified Venues", ""]
    if not disqualified:
        lines.append("No venues were disqualified.")
        return lines

    for entry in disqualified:
        result = entry["result"]
        failures = result.get("must_failures", [])
        lines.append(f"### {result.get('name', 'Unknown Venue')}")
        lines.append("")
        if not failures:
            lines.append("- No blocker details provided.")
        else:
            for failure in failures:
                label = failure.get("label", failure.get("id", "Unknown criterion"))
                reason = failure.get("reason", "unspecified")
                lines.append(f"- **{label}**: {reason}")
        lines.append("")

    if lines[-1] == "":
        lines.pop()
    return lines


def render_markdown(requirements: dict, results: list[dict]) -> str:
    qualified = [entry for entry in results if entry["result"].get("status") != "DISQUALIFIED"]
    disqualified = [entry for entry in results if entry["result"].get("status") == "DISQUALIFIED"]

    sections = [
        build_header(requirements),
        build_main_table(qualified),
        build_category_sections(qualified, requirements),
        build_disqualified_section(disqualified),
    ]
    return "\n\n".join("\n".join(section) for section in sections if section).strip() + "\n"


def main() -> None:
    args = parse_args()
    base = PIPELINE_DIR.parent
    requirements_path = Path(args.requirements) if args.requirements else base / "venues" / "requirements.yaml"
    venues_dir = Path(args.venues_dir) if args.venues_dir else base / "venues"
    output_path = Path(args.output) if args.output else base / "VENUES.md"

    requirements, results = load_results(requirements_path, venues_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_markdown(requirements, results), encoding="utf-8")


if __name__ == "__main__":
    main()
