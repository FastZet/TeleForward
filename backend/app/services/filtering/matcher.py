"""
TeleForward filter matcher.

Combines inclusion and exclusion filter groups into a single decision.

Matching policy:
- If inclusion groups exist, at least one must match.
- If no inclusion groups exist, inclusion is unrestricted.
- If any exclusion group matches, the message is rejected.
- Disabled groups are ignored.
- Evaluation results retain individual group outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.filtering.engine import (
    FilterContext,
    FilterEvaluation,
    FilterEngine,
    FilterGroup,
)


@dataclass(frozen=True, slots=True)
class GroupMatchResult:
    """Evaluation result for one filter group."""

    group_index: int
    matched: bool
    evaluation: FilterEvaluation


@dataclass(frozen=True, slots=True)
class MatchDecision:
    """Final decision produced by the filter matcher."""

    accepted: bool
    inclusion_matched: bool
    exclusion_matched: bool
    inclusion_results: tuple[GroupMatchResult, ...]
    exclusion_results: tuple[GroupMatchResult, ...]
    reason: str


class FilterMatcher:
    """
    Apply inclusion and exclusion rules to a message.

    This class does not access the database or Telegram client.
    It operates exclusively on normalised filter contexts and groups.
    """

    def __init__(
        self,
        engine: FilterEngine | None = None,
    ) -> None:
        self.engine = engine or FilterEngine()

    def match(
        self,
        context: FilterContext,
        *,
        include_groups: tuple[FilterGroup, ...] = (),
        exclude_groups: tuple[FilterGroup, ...] = (),
    ) -> MatchDecision:
        """Evaluate all active inclusion and exclusion groups."""

        active_includes = tuple(
            group
            for group in include_groups
            if group.enabled
        )

        active_excludes = tuple(
            group
            for group in exclude_groups
            if group.enabled
        )

        inclusion_results = self._evaluate_groups(
            context,
            active_includes,
        )

        exclusion_results = self._evaluate_groups(
            context,
            active_excludes,
        )

        # No inclusion groups means that all messages pass
        # the inclusion stage.
        inclusion_matched = (
            not active_includes
            or any(
                result.matched
                for result in inclusion_results
            )
        )

        # A match against any exclusion group rejects the message.
        exclusion_matched = any(
            result.matched
            for result in exclusion_results
        )

        accepted = (
            inclusion_matched
            and not exclusion_matched
        )

        if exclusion_matched:
            reason = "Message matched an exclusion filter."
        elif not inclusion_matched:
            reason = "Message did not match any inclusion filter."
        elif not active_includes and not active_excludes:
            reason = "No active filters; message accepted."
        else:
            reason = "Message passed all filtering stages."

        return MatchDecision(
            accepted=accepted,
            inclusion_matched=inclusion_matched,
            exclusion_matched=exclusion_matched,
            inclusion_results=inclusion_results,
            exclusion_results=exclusion_results,
            reason=reason,
        )

    def _evaluate_groups(
        self,
        context: FilterContext,
        groups: tuple[FilterGroup, ...],
    ) -> tuple[GroupMatchResult, ...]:
        """Evaluate groups independently."""
        results: list[GroupMatchResult] = []

        for index, group in enumerate(groups):
            evaluation = self.engine.evaluate_group(
                context,
                group,
            )

            results.append(
                GroupMatchResult(
                    group_index=index,
                    matched=evaluation.matched,
                    evaluation=evaluation,
                )
            )

        return tuple(results)
