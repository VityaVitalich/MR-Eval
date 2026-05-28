import subprocess
import os
import time
from queue import Queue, Empty
from threading import Thread, Lock
from tqdm import tqdm
import atexit
import signal

# ---------------- CONFIG ----------------
PARENT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(PARENT_DIR, "outputs")
LOG_DIR = os.path.join(PARENT_DIR, "outputs")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

GPUS = ["cuda:0", "cuda:1", "cuda:2"]  # 3 GPUs
LOCK_FILE = os.path.join(PARENT_DIR, ".run_all_evals.lock")
MIN_FREE_GPU_MEM_MB = 18000
TARGET_MAX_NEW_TOKENS = 512

MODELS = {
    "safelm": "locuslab/safelm-1.7b",
    "safelm_instruct": "locuslab/safelm-1.7b-instruct",
    "baseline_pretrain": "Raghav-Singhal/pretrain-normal-smollm-1p7b-100B-20n-2048sl-960gbsz",
    "baseline_filtered_pretrain": "Raghav-Singhal/pretrain-normal-smollm-1p7b-100B-20n-2048sl-960gbsz-no-bad-data",
    "baseline_sft": "Raghav-Singhal/tulu3-normal-fixed-smollm-1p7b-100B-20n-2048sl-960gbsz-4n-gbs128",
    "baseline_filtered_sft": "Raghav-Singhal/tulu3sft-normal-smollm-1p7b-100B-20n-2048sl-960gbsz-no-bad-data",
    "baseline_dpo": "Raghav-Singhal/dpo-tulu3-lr1e-6-beta0.1-tulu3sft-100B-normal-fixed-off-policy-if",
    "baseline_pretrain_500B": "Raghav-Singhal/normal-smollm-1p7b-500B-30n-2048sl-960gbsz",
    "baseline_sft_500B": "Raghav-Singhal/tulu3sft-normal-smollm-1p7b-500B-30n-2048sl-960gbsz",
    "llama32_1B": "alpindale/Llama-3.2-1B",
    "llama32_1B_instruct": "alpindale/Llama-3.2-1B-Instruct",
    "llama32_3B": "meta-llama/Llama-3.2-3B",
}


def _pid_is_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_run_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                content = f.read().strip()
            old_pid = int(content) if content else -1
        except Exception:
            old_pid = -1

        if old_pid > 0 and _pid_is_alive(old_pid):
            raise RuntimeError(
                f"Another run_all_evals.py instance is already running (pid={old_pid}). "
                "Stop it before starting a new batch."
            )

        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def _release_run_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except OSError:
        pass


def _get_free_gpu_mem_mb(gpu_num):
    output = subprocess.check_output(
        [
            "nvidia-smi",
            f"--id={gpu_num}",
            "--query-gpu=memory.free",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    ).strip()
    return int(output.splitlines()[0].strip())


def _wait_for_gpu_headroom(gpu_num, min_free_mb=MIN_FREE_GPU_MEM_MB):
    while True:
        try:
            free_mb = _get_free_gpu_mem_mb(gpu_num)
        except Exception:
            # If nvidia-smi query transiently fails, wait and retry.
            time.sleep(5)
            continue

        if free_mb >= min_free_mb:
            return

        print(
            f"[GPU cuda:{gpu_num}] waiting for free memory: "
            f"{free_mb} MiB available, need >= {min_free_mb} MiB"
        )
        time.sleep(10)

# ---------------- WORKER ----------------
def worker(gpu_id, task_queue, pbar, pbar_lock, stats):
    # Extract just the number from "cuda:X" (e.g., "0", "1", "2")
    gpu_num = gpu_id.split(":")[1]

    while True:
        try:
            name, model = task_queue.get_nowait()
        except Empty:
            break

        print(f"\n[GPU {gpu_id}] Starting: {name}")

        _wait_for_gpu_headroom(gpu_num)

        log_file = os.path.join(LOG_DIR, f"{name}_fuzzing.log")

        cmd = [
            "python", os.path.join(PARENT_DIR, "gptfuzz.py"),
            "--question_path", os.path.join(PARENT_DIR, "datasets/questions/advbench.csv"),
            "--target_model", model,
            "--generate_in_batch",
            "--max-new-tokens", str(TARGET_MAX_NEW_TOKENS),
            "--predictor_device", "cuda:0",
            "--predictor_batch_size", "1",
            "--target_gpu_memory_utilization", "0.25",
            "--target_max_num_seqs", "8",
            "--target_enforce_eager",
            "--result_file", os.path.join(OUTPUT_DIR, f"results_{name}.csv"),
            "--eval_log_file", os.path.join(OUTPUT_DIR, f"eval_{name}.csv"),
        ]

        cmd += [
            "--max_query", "10000",
            "--max_jailbreak", "-1",
            "--energy", "5",
            "--mutator_temperature", "0.55",
        ]
        worker_env = os.environ.copy()
        worker_env["CUDA_VISIBLE_DEVICES"] = gpu_num
        worker_env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

        return_code = 1
        with open(log_file, "w") as f:
            process = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, env=worker_env)
            return_code = process.wait()

        if return_code == 0:
            print(f"[GPU {gpu_id}] Finished: {name}")
        else:
            print(f"[GPU {gpu_id}] Failed ({return_code}): {name}")

        with pbar_lock:
            if return_code != 0:
                stats['failed'] += 1
            pbar.update(1)
            pbar.set_postfix(failed=stats['failed'])

        task_queue.task_done()


# ---------------- MAIN ----------------
def main():
    _acquire_run_lock()
    atexit.register(_release_run_lock)

    # Release lock on Ctrl+C / termination.
    signal.signal(signal.SIGINT, lambda *_: (_release_run_lock(), exit(130)))
    signal.signal(signal.SIGTERM, lambda *_: (_release_run_lock(), exit(143)))

    task_queue = Queue()
    total_tasks = len(MODELS)
    start_time = time.perf_counter()

    # Fill queue
    for name, model in MODELS.items():
        task_queue.put((name, model))

    pbar = tqdm(
        total=total_tasks,
        desc="Model evaluations",
        unit="model",
        dynamic_ncols=True,
        mininterval=1.0,
    )
    pbar_lock = Lock()
    stats = {'failed': 0}

    # Start one worker per GPU
    threads = []
    for gpu in GPUS:
        t = Thread(target=worker, args=(gpu, task_queue, pbar, pbar_lock, stats))
        t.start()
        threads.append(t)

    # Wait for all to finish
    for t in threads:
        t.join()

    pbar.close()
    elapsed = time.perf_counter() - start_time
    h = int(elapsed // 3600)
    m = int((elapsed % 3600) // 60)
    s = int(elapsed % 60)

    print(f"\nAll models completed in {h:02d}:{m:02d}:{s:02d} (failed: {stats['failed']}/{total_tasks})")


if __name__ == "__main__":
    main()