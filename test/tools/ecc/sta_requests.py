"""STA steps written with the req.json the parent writes for them."""

from chipcompiler.data import EccStep, StepEnum
from chipcompiler.data.handshake import StepInputs, StepRequest, write_request
from test.flow_fixture import publish_response


def sta_step_with_request(workspace_dir, upstream):
    """An STA step whose req.json links *upstream* ({item: directory}) to published runs."""
    request = StepRequest(
        workspace_directory=workspace_dir,
        step=StepEnum.STA.value,
        tool="ecc",
        step_directory="sta_ecc",
        attempt_id="attempt-sta",
        inputs=StepInputs(),
        design_source=None,
        upstream={
            item: publish_response(workspace_dir, directory) for item, directory in upstream.items()
        },
        final_step=False,
        layout_image=False,
    )
    write_request(request)
    return EccStep(name=StepEnum.STA.value, directory=request.directory)
