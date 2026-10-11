"""Posts a Teams message when an inspection report is approved (synthetic example)."""

import requests

GRAPH = "https://graph.microsoft.com/v1.0"


def post_to_channel(token: str, team_id: str, channel_id: str, text: str) -> None:
    url = f"{GRAPH}/teams/{team_id}/channels/{channel_id}/messages"
    requests.post(url, headers={"Authorization": f"Bearer {token}"}, json={"body": {"content": text}}, timeout=30)
