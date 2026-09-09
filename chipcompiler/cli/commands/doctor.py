from chipcompiler.cli.command_handlers import doctor as doctor_handlers
from chipcompiler.cli.core.inputs import DoctorInput, output_options, project_options
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import PlainOption, ProjectOption


def register_doctor_commands(app) -> None:
    app.command("doctor", help="Check host environment: PDK, tools, and components")(doctor_cmd)


def doctor_cmd(
    *,
    project: ProjectOption = None,
    plain: PlainOption = False,
) -> None:
    command_input = DoctorInput(
        output=output_options(plain=plain),
        project=project_options(project),
    )
    execute_command("doctor", command_input, doctor_handlers.doctor)
