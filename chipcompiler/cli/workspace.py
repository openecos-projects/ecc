from chipcompiler.cli.workspace_request import InputError, create_request
from chipcompiler.cli.workspace_response import (
    exit_code_for_response,
    workspace_response,
)
from chipcompiler.cli.workspace_service import (
    create_workspace_from_request,
    get_workspace_home,
    get_workspace_info,
    load_workspace,
    run_workspace_flow,
    run_workspace_step,
)


def dispatch(args) -> tuple[dict, int]:
    handlers = {
        "create": create,
        "load": load,
        "run-flow": run_flow,
        "run-step": run_step,
        "get-info": get_info,
        "get-home": get_home,
    }
    handler = handlers.get(args.workspace_command)
    if handler is None:
        result = workspace_response("", "error", message=["unknown workspace command"])
    else:
        result = handler(args)
    return result, exit_code_for_response(result["response"])


def create(args) -> dict:
    try:
        request = create_request(
            input_json=args.input_json,
            directory=args.directory,
            pdk=args.pdk,
            pdk_root=args.pdk_root,
            origin_def=args.origin_def,
            origin_verilog=args.origin_verilog,
            filelist=args.filelist,
            rtl=args.rtl,
            param_json=args.param_json,
        )
    except InputError as exc:
        return workspace_response("create_workspace", exc.response, message=[str(exc)])
    return create_workspace_from_request(request)


def load(args) -> dict:
    return load_workspace(args.directory)


def run_flow(args) -> dict:
    return run_workspace_flow(args.directory, args.rerun)


def run_step(args) -> dict:
    return run_workspace_step(args.directory, args.step, args.rerun)


def get_info(args) -> dict:
    return get_workspace_info(args.directory, args.step, args.id)


def get_home(args) -> dict:
    return get_workspace_home(args.directory)
