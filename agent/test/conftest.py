import os

# Fake-flow tests drive step execution in process; disable the per-candidate
# worker subprocess for the unit suite.
os.environ["ECC_CANDIDATE_STEP_ISOLATION"] = "0"
