"""Use measured stage evidence for advisory selection before full validation."""

from pathlib import Path

from ecc_experience.files import digest
from ecc_experience.modeling.predict import predict_case, read_model_release
from ecc_experience.models import ExperienceError


def check_model(plan: dict, model_release: str | Path) -> dict:
    release = read_model_release(model_release)
    model = release["model"]
    if model["target"] != "final_qor":
        raise ExperienceError(
            "Model-guided DSE currently requires a final_qor target",
            code="experience_model_invalid",
        )
    if (
        model["through_step"] != plan["through_step"]
        or plan["process"].get("fingerprint") not in model["process_fingerprints"]
        or digest(plan["runtime"]) not in model["runtime_fingerprints"]
    ):
        raise ExperienceError(
            "DSE plan is outside the model stage, process or runtime scope",
            code="experience_model_incompatible",
        )
    return release


def predict_trial(plan: dict, record: dict, model_release: str | Path, release_id: str) -> dict:
    prediction = predict_case(
        model_release, record["case_id"], plan["store"], through_step=plan["through_step"]
    )
    if prediction["model_release_id"] != release_id:
        raise ExperienceError("DSE model release changed", code="experience_source_changed")
    return prediction
