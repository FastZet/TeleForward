"""
TeleForward message filtering services.

Responsible for evaluating incoming Telegram messages against configured
filter rules before they enter the forwarding pipeline.

Filtering capabilities include:
- Text and keyword matching.
- Regular-expression matching.
- Sender and chat filtering.
- Media-type filtering.
- Message-length constraints.
- Include and exclude conditions.
- Combined AND/OR filter expressions.
- Filter-rule evaluation and execution results.
"""

from __future__ import annotations

__all__: list[str] = []
