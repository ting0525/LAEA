import signal
import subprocess
import sys
import time

from iottalk_project_bootstrap import BootstrapError, ensure_iottalk_project


processes = []
shutting_down = False


def start_process(script_name):
    process = subprocess.Popen([sys.executable, script_name])
    processes.append(process)
    return process


def terminate_all_proc():
    global shutting_down
    if shutting_down:
        return
    shutting_down = True
    print("Stopping AIoTtalk_plus subprocesses")
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def handle_signal(_signum, _frame):
    terminate_all_proc()
    raise SystemExit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        bootstrap_result = ensure_iottalk_project()
    except BootstrapError as error:
        print("IoTtalk bootstrap failed: {}".format(error))
        raise SystemExit(1)

    print(
        "IoTtalk project ready: {} (p_id={})".format(
            bootstrap_result.p_name,
            bootstrap_result.p_id,
        )
    )

    start_process("SIPSignalingHandler.py")
    time.sleep(3)
    start_process("RTPEstablisher.py")
    time.sleep(1)
    start_process("RTPDevice/RTPDevice.py")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        terminate_all_proc()
