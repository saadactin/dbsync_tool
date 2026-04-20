import logging
import os
import subprocess
import sys
from typing import Optional

from django.conf import settings


logger = logging.getLogger(__name__)


def launch_sync_job_subprocess(job_id: str, *, initiated_by_user_id: Optional[int] = None) -> int:
    """
    Launch sync execution in a detached subprocess so it survives dev-server reloads.
    Returns child pid.
    """
    manage_py = os.path.join(settings.BASE_DIR, "manage.py")
    command = [sys.executable, manage_py, "run_sync_job", "--job-id", str(job_id)]
    if initiated_by_user_id is not None:
        command.extend(["--initiated-by-user-id", str(initiated_by_user_id)])

    creationflags = 0
    popen_kwargs = {}

    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        popen_kwargs["close_fds"] = True
    else:
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=settings.BASE_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        **popen_kwargs,
    )
    logger.info("Launched detached sync subprocess pid=%s for job=%s", process.pid, job_id)
    return process.pid
