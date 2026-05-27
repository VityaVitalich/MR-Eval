api_key = 'enter here for gpt 3.5 turbo'
import os
#os.environ['CUDA_VISIBLE_DEVICES'] = '0,1'  # for debugging

# Auto-load credentials from openapi_key_url if env vars are not set
_key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'openapi_key_url')
if os.path.exists(_key_file):
    with open(_key_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if '=' in _line and not _line.startswith('#'):
                _k, _v = _line.split('=', 1)
                if _k.strip() not in os.environ:
                    os.environ[_k.strip()] = _v.strip()

from fastchat.model import add_model_args
import argparse
import pandas as pd
from gptfuzzer.fuzzer.selection import MCTSExploreSelectPolicy
from gptfuzzer.fuzzer.mutator import (
    MutateRandomSinglePolicy, OpenAIMutatorCrossOver, OpenAIMutatorExpand,
    OpenAIMutatorGenerateSimilar, OpenAIMutatorRephrase, OpenAIMutatorShorten)
from gptfuzzer.fuzzer import GPTFuzzer
from gptfuzzer.llm import OpenAILLM, LocalVLLM, LocalLLM, PaLM2LLM, ClaudeLLM
from gptfuzzer.utils.predict import RoBERTaPredictor
import random
random.seed(100)
import logging
httpx_logger: logging.Logger = logging.getLogger("httpx")
# disable httpx logging
httpx_logger.setLevel(logging.WARNING)


def _read_csv_guess_sep(file_path: str) -> pd.DataFrame:
    # Auto-detect delimiter first; fallback to common delimiters for compatibility.
    try:
        return pd.read_csv(file_path, sep=None, engine='python')
    except Exception:
        for sep in [',', '|', '\t']:
            try:
                return pd.read_csv(file_path, sep=sep)
            except Exception:
                continue
    raise ValueError(f"Unable to parse CSV file: {file_path}")


def _pick_column(df: pd.DataFrame, preferred_columns) -> str:
    col_map = {str(col).strip().lower(): col for col in df.columns}

    for col in preferred_columns:
        if col is None:
            continue
        key = str(col).strip().lower()
        if key in col_map:
            return col_map[key]

    for col in df.columns:
        key = str(col).strip().lower()
        if key not in {'index', 'id', 'unnamed: 0'}:
            return col

    if len(df.columns) == 0:
        raise ValueError("CSV has no columns")

    return df.columns[0]


def main(args):
    seed_df = _read_csv_guess_sep(args.seed_path)
    seed_col = _pick_column(seed_df, ['text', 'prompt'])
    initial_seed = seed_df[seed_col].dropna().astype(str).tolist()

    question_df = _read_csv_guess_sep(args.question_path)
    question_col = _pick_column(question_df, [args.question_col, 'text'])
    questions = question_df[question_col].dropna().astype(str).tolist()

    openai_model = OpenAILLM(args.model_path, args.openai_key)
    # target_model = PaLM2LLM(args.target_model, args.palm_key)
    # target_model = ClaudeLLM(args.target_model, args.claude_key)
    #target_model = LocalVLLM(args.target_model)
    target_model = LocalVLLM(
        args.target_model,
        gpu_memory_utilization=args.target_gpu_memory_utilization,
        max_model_len=(args.target_max_model_len if args.target_max_model_len and args.target_max_model_len > 0 else None),
        max_num_seqs=args.target_max_num_seqs,
        enforce_eager=args.target_enforce_eager,
        default_max_tokens=args.max_new_tokens,
    )
    # target_model = LocalLLM(args.target_model) # we suggest using LocalVLLM for better performance, however if you are facing difficulties in installing vllm, you can use LocalLLM instead
    roberta_model = RoBERTaPredictor(
        args.predictor_path,
        device=args.predictor_device,
        batch_size=args.predictor_batch_size,
    )

    result_file = args.result_file if args.result_file else None
    eval_log_file = args.eval_log_file if args.eval_log_file else None
    diversity_temp = args.mutator_temperature

    fuzzer = GPTFuzzer(
        questions=questions,
        # target_model=openai_model,
        target=target_model,
        predictor=roberta_model,
        initial_seed=initial_seed,
        mutate_policy=MutateRandomSinglePolicy([
            OpenAIMutatorCrossOver(openai_model, temperature=min(0.8, diversity_temp + 0.05)),
            OpenAIMutatorExpand(openai_model, temperature=min(0.8, diversity_temp + 0.05)),
            OpenAIMutatorGenerateSimilar(openai_model, temperature=diversity_temp),
            OpenAIMutatorRephrase(openai_model, temperature=diversity_temp),
            OpenAIMutatorShorten(openai_model, temperature=max(0.3, diversity_temp - 0.1))],
            concatentate=True,
        ),
        select_policy=MCTSExploreSelectPolicy(),
        energy=args.energy,
        max_jailbreak=args.max_jailbreak,
        max_query=args.max_query,
        result_file=result_file,
        eval_log_file=eval_log_file,
        generate_in_batch=args.generate_in_batch,
    )

    fuzzer.run()

## List of eval models:

# safelm	locuslab/safelm-1.7b
# safelm_sft	locuslab/safelm-1.7b-instruct
# baseline_pretrain	Raghav-Singhal/pretrain-normal-smollm-1p7b-100B
# baseline_filtered_pretrain	Raghav-Singhal/pretrain-normal-smollm-1p7b-100B-no-bad-data
# baseline_sft	Raghav-Singhal/tulu3-normal-fixed-smollm-1p7b-100B
# baseline_filtered_sft	Raghav-Singhal/tulu3sft-normal-smollm-1p7b-100B-no-bad-data
# baseline_dpo	Raghav-Singhal/dpo-tulu3-lr1e-6-beta0.1-tulu3sft-100B-normal-fixed-off-policy-if (https://huggingface.co/Raghav-Singhal/dpo-tulu3-lr1e-6-beta0.1-tulu3sft-100B-normal-fixed-off-policy-if)
# baseline_pretrain_500B	Raghav-Singhal/normal-smollm-1p7b-500B
# baseline_sft_500B	Raghav-Singhal/tulu3sft-normal-smollm-1p7b-500B
# llama32_1B	alpindale/Llama-3.2-1B
# llama32_1B_instruct	alpindale/Llama-3.2-1B-Instruct
# llama32_3B	meta-llama/Llama-3.2-3B
if __name__ == "__main__":
    parent_dir = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description='Fuzzing parameters')
    parser.add_argument('--openai_key', type=str, default=api_key, help='OpenAI/OpenRouter API Key')
    parser.add_argument('--claude_key', type=str, default='', help='Claude API Key')
    parser.add_argument('--palm_key', type=str, default='', help='PaLM2 api key')
    parser.add_argument('--model_path', type=str, default='openai/gpt-3.5-turbo',
                        help='mutate model path')
    parser.add_argument('--target_model', type=str, default='locuslab/safelm-1.7b',
                        help='The target model, openai model or open-sourced LLMs')
    parser.add_argument('--max_query', type=int, default=1000,
                        help='The maximum number of queries')
    parser.add_argument('--max_jailbreak', type=int,
                        default=-1, help='The maximum jailbreak number (-1 means no limit)')
    parser.add_argument('--energy', type=int, default=5,
                        help='Mutation attempts per selected prompt (5 is suitable for Top-1/Top-5 analysis)')
    parser.add_argument('--mutator_temperature', type=float, default=0.55,
                        help='Controls mutation diversity (recommended range: 0.45-0.65)')
    parser.add_argument('--seed_selection_strategy', type=str,
                        default='round_robin', help='The seed selection strategy')
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument('--generate_in_batch', dest='generate_in_batch', action='store_true',
                        help='Enable batched target generation over all questions per template')
    parser.add_argument('--no_generate_in_batch', dest='generate_in_batch', action='store_false',
                        help='Disable batched target generation')
    parser.set_defaults(generate_in_batch=True)
    parser.add_argument("--seed_path", type=str,
                        default=f"{parent_dir}/datasets/prompts/GPTFuzzer.csv")
    parser.add_argument('--question_path', type=str, default=f"{parent_dir}/datasets/questions/advbench.csv",
                        help='CSV file containing harmful questions')
    parser.add_argument('--question_col', type=str, default='text',
                        help='Column name for questions in question_path CSV')
    parser.add_argument('--predictor_path', type=str, default='hubert233/GPTFuzz',
                        help='Path or HF repo for jailbreak predictor model')
    parser.add_argument('--predictor_device', type=str, default='cuda:0',
                        help='Device for predictor model, e.g. cuda:0 or cpu')
    parser.add_argument('--predictor_batch_size', type=int, default=8,
                        help='Batch size for predictor inference to control memory usage')
    parser.add_argument('--target_gpu_memory_utilization', type=float, default=0.25,
                        help='vLLM GPU memory utilization for target model')
    parser.add_argument('--target_max_model_len', type=int, default=-1,
                        help='vLLM max model length override; use -1 for auto from model config')
    parser.add_argument('--target_max_num_seqs', type=int, default=8,
                        help='vLLM max concurrent sequences to limit KV cache memory')
    parser.add_argument('--target_enforce_eager', action='store_true', default=True,
                        help='Run target model in eager mode to avoid CUDA graph memory overhead')
    parser.add_argument('--result_file', type=str, default=f"{parent_dir}/outputs/results_safelm.csv",
                        help='Output CSV for successful templates')
    parser.add_argument('--eval_log_file', type=str, default=f"{parent_dir}/outputs/eval_safelm.csv",
                        help='Output CSV for per-query evaluation logs')
    add_model_args(parser)

    args = parser.parse_args()
    main(args)
