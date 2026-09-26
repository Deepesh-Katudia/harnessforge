import os

# The original unit tests target the MongoDB benchmark; support-domain tests pass their spec explicitly.
os.environ["HF_DOMAIN"] = "mongodb"
