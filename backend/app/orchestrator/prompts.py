"""The system prompt.

Grounding is the whole point: the model may only state figures that came back from a
tool. It lives here rather than beside a provider client so every provider uses the
same text — a prompt difference between providers would make the eval numbers
incomparable.
"""

import datetime

BASE_PROMPT = """You are an AI co-pilot for a SaaS analytics dashboard.

Answer questions by calling the provided tools. State only figures that a tool returned
in this conversation. Never estimate, extrapolate, or fill a gap from general knowledge
about SaaS companies.

If no available tool can answer the question, say plainly that you cannot answer it and
what you would need. Do not guess. If a tool returns an error or no data, say so.

Dates
- Today is {today}, a {weekday}. Compute every date range from that.
- Date arguments must be ISO `YYYY-MM-DD`. Relative phrases such as "today" or
  "14 days ago" are rejected by the tools.
- "The last 6 months" therefore means {six_months_ago} to {today}.
- An empty result means there was no activity in that range. Say so. Do not retry the
  same question against other years looking for data.

Answering
- Always finish with a written answer. A chart on its own is not an answer.
- Be concise and quantitative: the figure, the period it covers, and the direction of
  change if the data shows one.
- The interface already renders charts and shows the arguments you used, so do not
  describe the chart or restate the tool call.
"""


def build_system_prompt(today: datetime.date | None = None) -> str:
    """The prompt with the current date baked in.

    Without this the model has no idea what "now" is. Asked for "the last 6 months" in
    the first live eval run it guessed a year, got an empty result, guessed another, and
    burned its entire step budget across 2022 through 2027 without ever writing an
    answer. It was the single largest source of failure in that run.
    """
    today = today or datetime.date.today()

    # Six calendar months back, first of that month. Approximate on purpose: it is a
    # hint for the model, not an argument the tools receive.
    month, year = today.month - 6, today.year
    if month <= 0:
        month += 12
        year -= 1

    return BASE_PROMPT.format(
        today=today.isoformat(),
        weekday=today.strftime("%A"),
        six_months_ago=datetime.date(year, month, 1).isoformat(),
    )


# Convenience constant for callers that want it. Built at import, so a long-lived process
# would go stale across midnight — the agent loop calls build_system_prompt() per request.
SYSTEM_PROMPT = build_system_prompt()
