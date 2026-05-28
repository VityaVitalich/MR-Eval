from enum import Enum
VICUNA_PATH = "/home/pchao/vicuna-13b-v1.5"
LLAMA_PATH = "/home/pchao/Llama-2-7b-chat-hf"

ATTACK_TEMP = 1
TARGET_TEMP = 0
ATTACK_TOP_P = 0.9
TARGET_TOP_P = 1


## MODEL PARAMETERS ##
class Model(Enum):
    vicuna = "vicuna-13b-v1.5"
    llama_2 = "llama-2-7b-chat-hf"
    gpt_3_5 = "gpt-3.5-turbo-1106"
    gpt_4 = "gpt-4-0125-preview"
    claude_1 = "claude-instant-1.2"
    claude_2 = "claude-2.1"
    gemini = "gemini-pro"
    mixtral = "mixtral"
    safelm = "safelm-1.7b"
    safelm_sft = "safelm-1.7b-instruct"
    baseline_pretrain = "baseline-pretrain"
    baseline_filtered_pretrain = "baseline-filtered-pretrain"
    baseline_sft = "baseline-sft"
    baseline_filtered_sft = "baseline-filtered-sft"
    baseline_dpo = "baseline-dpo"
    baseline_pretrain_500B = "baseline-pretrain-500B"
    baseline_sft_500B = "baseline-sft-500B"
    llama32_1B = "llama-3.2-1B"
    llama32_1B_instruct = "llama-3.2-1B-Instruct"
    llama32_3B = "llama-3.2-3B"
    # Attacker option routed through OpenRouter (uses OPENROUTER_API_KEY).
    gpt_3_5_openrouter = "gpt-3.5-turbo-openrouter"
    gpt_4o_openrouter  = "gpt-4o-openrouter"

MODEL_NAMES = [model.value for model in Model]


HF_MODEL_NAMES: dict[Model, str] = {
    Model.llama_2: "meta-llama/Llama-2-7b-chat-hf",
    Model.vicuna: "lmsys/vicuna-13b-v1.5",
    Model.mixtral: "mistralai/Mixtral-8x7B-Instruct-v0.1",
    Model.safelm: "locuslab/safelm-1.7b",
    Model.safelm_sft: "locuslab/safelm-1.7b-instruct",
    # SmolLM2-1.7B baseline variants from Raghav-Singhal
    Model.baseline_pretrain:          "Raghav-Singhal/pretrain-normal-smollm-1p7b-100B-20n-2048sl-960gbsz",
    Model.baseline_filtered_pretrain: "Raghav-Singhal/pretrain-normal-smollm-1p7b-100B-20n-2048sl-960gbsz-no-bad-data",
    Model.baseline_sft:               "Raghav-Singhal/tulu3-normal-fixed-smollm-1p7b-100B-20n-2048sl-960gbsz-4n-gbs128",
    Model.baseline_filtered_sft:      "Raghav-Singhal/tulu3sft-normal-smollm-1p7b-100B-20n-2048sl-960gbsz-no-bad-data",
    Model.baseline_dpo:               "Raghav-Singhal/dpo-tulu3-lr1e-6-beta0.1-tulu3sft-100B-normal-fixed-off-policy-if",
    Model.baseline_pretrain_500B:     "Raghav-Singhal/normal-smollm-1p7b-500B-30n-2048sl-960gbsz",
    Model.baseline_sft_500B:          "Raghav-Singhal/tulu3sft-normal-smollm-1p7b-500B-30n-2048sl-960gbsz",
    # Llama-3.2
    Model.llama32_1B:          "alpindale/Llama-3.2-1B",
    Model.llama32_1B_instruct: "alpindale/Llama-3.2-1B-Instruct",
    Model.llama32_3B:          "meta-llama/Llama-3.2-3B",
}

TOGETHER_MODEL_NAMES: dict[Model, str] = {
    Model.llama_2: "together_ai/togethercomputer/llama-2-7b-chat",
    Model.vicuna: "together_ai/lmsys/vicuna-13b-v1.5",
    Model.mixtral: "together_ai/mistralai/Mixtral-8x7B-Instruct-v0.1"
}

# Fastchat conversation template name to use for each model.
#   - "chatml"     : <|im_start|>role\n...<|im_end|>   (SmolLM2 family, Tulu, etc.)
#   - "llama-3"    : Llama-3 instruct chat template
#   - "zero_shot"  : raw single-turn, used for base / pretrain-only models
#     that have no chat template. PAIR targets won't behave like assistants
#     here; you may want to skip these or accept low-quality continuations.
FASTCHAT_TEMPLATE_NAMES: dict[Model, str] = {
    Model.gpt_3_5: "gpt-3.5-turbo",
    Model.gpt_4: "gpt-4",
    Model.claude_1: "claude-instant-1.2",
    Model.claude_2: "claude-2.1",
    Model.gemini: "gemini-pro",
    Model.vicuna: "vicuna_v1.1",
    Model.llama_2: "llama-2-7b-chat-hf",
    Model.mixtral: "mixtral",
    Model.safelm: "chatml",
    Model.safelm_sft: "chatml",
    Model.baseline_pretrain:          "zero_shot",
    Model.baseline_filtered_pretrain: "zero_shot",
    Model.baseline_sft:               "chatml",
    Model.baseline_filtered_sft:      "chatml",
    Model.baseline_dpo:               "chatml",
    Model.baseline_pretrain_500B:     "zero_shot",
    Model.baseline_sft_500B:          "chatml",
    Model.llama32_1B:          "zero_shot",
    Model.llama32_1B_instruct: "llama-3",
    Model.llama32_3B:          "zero_shot",
    Model.gpt_3_5_openrouter:  "gpt-3.5-turbo",
    Model.gpt_4o_openrouter:   "gpt-4",
}

API_KEY_NAMES: dict[Model, str] = {
    Model.gpt_3_5:  "OPENAI_API_KEY",
    Model.gpt_4:    "OPENAI_API_KEY",
    Model.claude_1: "ANTHROPIC_API_KEY",
    Model.claude_2: "ANTHROPIC_API_KEY",
    Model.gemini:   "GEMINI_API_KEY",
    Model.vicuna:   "TOGETHER_API_KEY",
    Model.llama_2:  "TOGETHER_API_KEY",
    Model.mixtral:  "TOGETHER_API_KEY",
    Model.gpt_3_5_openrouter: "OPENROUTER_API_KEY",
    Model.gpt_4o_openrouter:  "OPENROUTER_API_KEY",
}

LITELLM_TEMPLATES: dict[Model, dict] = {
    Model.vicuna: {"roles":{
                    "system": {"pre_message": "", "post_message": " "},
                    "user": {"pre_message": "USER: ", "post_message": " ASSISTANT:"},
                    "assistant": {
                        "pre_message": "",
                        "post_message": "",
                    },
                },
                "post_message":"</s>",
                "initial_prompt_value" : "",
                "eos_tokens": ["</s>"]         
                },
    Model.llama_2: {"roles":{
                    "system": {"pre_message": "[INST] <<SYS>>\n", "post_message": "\n<</SYS>>\n\n"},
                    "user": {"pre_message": "", "post_message": " [/INST]"},
                    "assistant": {"pre_message": "", "post_message": ""},
                },
                "post_message" : " </s><s>",
                "initial_prompt_value" : "",
                "eos_tokens" :  ["</s>", "[/INST]"]  
            },
    Model.mixtral: {"roles":{
                    "system": {
                        "pre_message": "[INST] ",
                        "post_message": " [/INST]"
                    },
                    "user": { 
                        "pre_message": "[INST] ",
                        "post_message": " [/INST]"
                    }, 
                    "assistant": {
                        "pre_message": " ",
                        "post_message": "",
                    }
                },
                "post_message": "</s>",
                "initial_prompt_value" : "<s>",
                "eos_tokens": ["</s>", "[/INST]"]
    },
    Model.safelm: {"roles": {
                    "system": {"pre_message": "<|im_start|>system\n", "post_message": "<|im_end|>\n"},
                    "user":   {"pre_message": "<|im_start|>user\n",   "post_message": "<|im_end|>\n"},
                    "assistant": {"pre_message": "<|im_start|>assistant\n", "post_message": "<|im_end|>\n"},
                },
                "post_message": "<|im_end|>",
                "initial_prompt_value": "",
                "eos_tokens": ["<|im_end|>", "<|endoftext|>"],
    },
}

# Shared chatml template for all SmolLM2-based instruct variants.
_CHATML_TEMPLATE = {
    "roles": {
        "system":    {"pre_message": "<|im_start|>system\n",    "post_message": "<|im_end|>\n"},
        "user":      {"pre_message": "<|im_start|>user\n",      "post_message": "<|im_end|>\n"},
        "assistant": {"pre_message": "<|im_start|>assistant\n", "post_message": "<|im_end|>\n"},
    },
    "post_message": "<|im_end|>",
    "initial_prompt_value": "",
    "eos_tokens": ["<|im_end|>", "<|endoftext|>"],
}

# Llama-3 instruct chat template
_LLAMA3_TEMPLATE = {
    "roles": {
        "system":    {"pre_message": "<|start_header_id|>system<|end_header_id|>\n\n",    "post_message": "<|eot_id|>"},
        "user":      {"pre_message": "<|start_header_id|>user<|end_header_id|>\n\n",      "post_message": "<|eot_id|>"},
        "assistant": {"pre_message": "<|start_header_id|>assistant<|end_header_id|>\n\n", "post_message": "<|eot_id|>"},
    },
    "post_message": "<|eot_id|>",
    "initial_prompt_value": "<|begin_of_text|>",
    "eos_tokens": ["<|eot_id|>", "<|end_of_text|>"],
}

# Raw / pretrain template — no chat structure, model just continues the user
# turn. Used for base models with no instruction tuning.
_RAW_TEMPLATE = {
    "roles": {
        "system":    {"pre_message": "", "post_message": "\n"},
        "user":      {"pre_message": "", "post_message": "\n"},
        "assistant": {"pre_message": "", "post_message": ""},
    },
    "post_message": "",
    "initial_prompt_value": "",
    "eos_tokens": [],
}

for _m in (
    Model.safelm_sft,
    Model.baseline_sft,
    Model.baseline_filtered_sft,
    Model.baseline_dpo,
    Model.baseline_sft_500B,
):
    LITELLM_TEMPLATES[_m] = _CHATML_TEMPLATE

for _m in (
    Model.baseline_pretrain,
    Model.baseline_filtered_pretrain,
    Model.baseline_pretrain_500B,
    Model.llama32_1B,
    Model.llama32_3B,
):
    LITELLM_TEMPLATES[_m] = _RAW_TEMPLATE

LITELLM_TEMPLATES[Model.llama32_1B_instruct] = _LLAMA3_TEMPLATE