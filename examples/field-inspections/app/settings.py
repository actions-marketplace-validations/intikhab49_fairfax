"""Backend settings for the field inspection app (synthetic example for govgap).

Copied from a commercial-cloud tutorial, which is how most of these endpoints end up in gov code.
"""

import os

TENANT_ID = os.environ["TENANT_ID"]
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
KEY_VAULT_URL = "https://inspections-kv.vault.azure.net/"
OPENAI_ENDPOINT = "https://inspections-ai.openai.azure.com/"
