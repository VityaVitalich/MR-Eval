import os 
import litellm
from config import TOGETHER_MODEL_NAMES, LITELLM_TEMPLATES, API_KEY_NAMES, Model, HF_MODEL_NAMES, FASTCHAT_TEMPLATE_NAMES
from loggers import logger
from common import get_api_key

class LanguageModel():
    def __init__(self, model_name):
        self.model_name = Model(model_name)
    
    def batched_generate(self, prompts_list: list, max_n_tokens: int, temperature: float):
        """
        Generates responses for a batch of prompts using a language model.
        """
        raise NotImplementedError
    
class APILiteLLM(LanguageModel):
    API_RETRY_SLEEP = 10
    API_ERROR_OUTPUT = "ERROR: API CALL FAILED."
    API_QUERY_SLEEP = 1
    API_MAX_RETRY = 5
    API_TIMEOUT = 20

    def __init__(self, model_name):
        super().__init__(model_name)
        self.api_key = get_api_key(self.model_name)
        self.litellm_model_name = self.get_litellm_model_name(self.model_name)
        litellm.drop_params=True
        self.set_eos_tokens(self.model_name)
        
    def get_litellm_model_name(self, model_name):
        # Models routed through OpenRouter (uses OPENROUTER_API_KEY).
        OPENROUTER_MAP = {
            Model.gpt_3_5_openrouter: "openrouter/openai/gpt-3.5-turbo",
            Model.gpt_4o_openrouter:  "openrouter/openai/gpt-4o",
        }
        if model_name in OPENROUTER_MAP:
            self.use_open_source_model = False
            return OPENROUTER_MAP[model_name]
        if model_name in TOGETHER_MODEL_NAMES:
            litellm_name = TOGETHER_MODEL_NAMES[model_name]
            self.use_open_source_model = True
        else:
            self.use_open_source_model =  False
            #if self.use_open_source_model:
                # Output warning, there should be a TogetherAI model name
                #logger.warning(f"Warning: No TogetherAI model name for {model_name}.")
            litellm_name = model_name.value 
        return litellm_name
    
    def set_eos_tokens(self, model_name):
        if self.use_open_source_model:
            self.eos_tokens = LITELLM_TEMPLATES[model_name]["eos_tokens"]     
        else:
            self.eos_tokens = []

    def _update_prompt_template(self):
        # We manually add the post_message later if we want to seed the model response
        if self.model_name in LITELLM_TEMPLATES:
            litellm.register_prompt_template(
                initial_prompt_value=LITELLM_TEMPLATES[self.model_name]["initial_prompt_value"],
                model=self.litellm_model_name,
                roles=LITELLM_TEMPLATES[self.model_name]["roles"]
            )
            self.post_message = LITELLM_TEMPLATES[self.model_name]["post_message"]
        else:
            self.post_message = ""
        
    
    
    def batched_generate(self, convs_list: list[list[dict]], 
                         max_n_tokens: int, 
                         temperature: float, 
                         top_p: float,
                         extra_eos_tokens: list[str] = None) -> list[str]: 
        
        eos_tokens = self.eos_tokens 

        if extra_eos_tokens:
            eos_tokens.extend(extra_eos_tokens)
        if self.use_open_source_model:
            self._update_prompt_template()
        
        outputs = litellm.batch_completion(
            model=self.litellm_model_name, 
            messages=convs_list,
            api_key=self.api_key,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_n_tokens,
            num_retries=self.API_MAX_RETRY,
            seed=0,
            stop=eos_tokens,
        )
        
        responses = [output["choices"][0]["message"].content for output in outputs]

        return responses

# class LocalvLLM(LanguageModel):
#     pass

class LocalvLLM(LanguageModel):
    """Local vLLM backend used as the attacker model when --evaluate-locally is set.

    Mirrors the subset of APILiteLLM's interface that conversers.AttackLM depends on:
      - .batched_generate(convs_list, max_n_tokens, temperature, top_p, extra_eos_tokens)
      - .use_open_source_model (bool)
      - .post_message (str, re-appended to the JSON-seeded assistant turn)
      - .eos_tokens (list[str])
    `convs_list` items are OpenAI-format message lists (role/content dicts).
    """

    _SHARED: dict = {}  # cache vLLM engines keyed by HF model path

    def __init__(self, model_name):
        super().__init__(model_name)
        if self.model_name not in HF_MODEL_NAMES:
            raise ValueError(
                f"No HF model path configured for {model_name}. "
                f"Add it to HF_MODEL_NAMES in config.py."
            )
        if self.model_name not in LITELLM_TEMPLATES:
            raise ValueError(
                f"No prompt template configured for {model_name}. "
                f"Add it to LITELLM_TEMPLATES in config.py."
            )

        self.hf_model_name = HF_MODEL_NAMES[self.model_name]
        self.fastchat_template_name = FASTCHAT_TEMPLATE_NAMES[self.model_name]
        self.use_open_source_model = True

        tmpl = LITELLM_TEMPLATES[self.model_name]
        self.eos_tokens = list(tmpl["eos_tokens"])
        self.post_message = tmpl["post_message"]

        # Lazily create / reuse a vLLM engine
        if self.hf_model_name not in LocalvLLM._SHARED:
            import vllm
            logger.info(f"Loading local vLLM engine for {self.hf_model_name}")
            LocalvLLM._SHARED[self.hf_model_name] = vllm.LLM(
                model=self.hf_model_name,
                dtype="bfloat16",
                trust_remote_code=True,
            )
        self.engine = LocalvLLM._SHARED[self.hf_model_name]

    def _messages_to_prompt(self, messages):
        """Render OpenAI-format messages into a single string using the fastchat template.

        The attacker code may seed the last assistant turn with an unterminated JSON
        fragment (e.g. `{"improvement": "...","prompt": "`). We must preserve that
        seed in the prompt without appending an empty assistant trailer.
        """
        from common import conv_template

        conv = conv_template(self.fastchat_template_name)

        # Strip system messages out of the role pairs and apply via set_system_message
        sys_parts = [m["content"] for m in messages if m["role"] == "system"]
        if sys_parts:
            conv.set_system_message("\n\n".join(sys_parts))

        seeded = False
        last_user = None
        for m in messages:
            role = m["role"]
            content = m["content"]
            if role == "system":
                continue
            if role == "user":
                conv.append_message(conv.roles[0], content)
                last_user = content
            elif role == "assistant":
                conv.append_message(conv.roles[1], content)
                seeded = True
            else:
                # Treat unknown roles as user turns
                conv.append_message(conv.roles[0], content)

        if not seeded:
            # Open the assistant turn so the model continues from there
            conv.append_message(conv.roles[1], None)

        prompt = conv.get_prompt()

        if seeded:
            # Fastchat templates (e.g. vicuna's ADD_COLON_TWO) append the
            # end-of-turn separator (often "</s>") AFTER a populated assistant
            # message. If we leave that in, vLLM will generate *after* the EOS,
            # which produces unrelated training-data continuations instead of
            # continuing our seeded JSON. Strip any trailing separator(s) /
            # known EOS tokens so generation resumes immediately after the seed.
            trailers = []
            for sep_attr in ("sep2", "sep"):
                sep = getattr(conv, sep_attr, None)
                if sep:
                    trailers.append(sep)
            trailers.extend(self.eos_tokens)
            # Try longest first to avoid partial matches
            trailers = sorted({t for t in trailers if t}, key=len, reverse=True)
            changed = True
            while changed:
                changed = False
                for t in trailers:
                    if prompt.endswith(t):
                        prompt = prompt[: -len(t)]
                        changed = True
                        break
            # Also remove any trailing whitespace that fastchat may have added
            prompt = prompt.rstrip("\n")
        return prompt

    def batched_generate(self, convs_list, max_n_tokens, temperature, top_p, extra_eos_tokens=None):
        import vllm

        stop = list(self.eos_tokens)
        if extra_eos_tokens:
            stop.extend(extra_eos_tokens)

        prompts = [self._messages_to_prompt(c) for c in convs_list]

        sampling_params = vllm.SamplingParams(
            temperature=float(temperature),
            top_p=float(top_p),
            max_tokens=int(max_n_tokens),
            stop=stop,
        )
        outputs = self.engine.generate(prompts, sampling_params, use_tqdm=False)
        # vLLM may reorder by internal request id; .generate returns in input order
        # in current versions, but to be safe we map by request_id if available.
        texts = []
        for out in outputs:
            txt = out.outputs[0].text
            # Strip a single leading space, matching the commented prototype's behavior
            if txt.startswith(" "):
                txt = txt[1:]
            texts.append(txt)
        return texts


class LocalHF(LanguageModel):
    """HuggingFace transformers backend (no pre-reservation of GPU memory).

    Mirrors the interface that conversers.AttackLM / TargetLM rely on:
      - .batched_generate(convs_list, max_n_tokens, temperature, top_p, extra_eos_tokens)
      - .use_open_source_model (bool)
      - .post_message (str)
      - .eos_tokens (list[str])

    Unlike vLLM (which pre-allocates a large fraction of VRAM up-front for its
    paged KV cache), transformers allocates only what the weights + per-step
    activations require, so VRAM usage scales with batch size and seq length.
    """

    _SHARED: dict = {}  # cache (model, tokenizer) keyed by HF model path

    def __init__(self, model_name, dtype: str = "bfloat16", device: str = "cuda:0"):
        super().__init__(model_name)
        if self.model_name not in HF_MODEL_NAMES:
            raise ValueError(
                f"No HF model path configured for {model_name}. "
                f"Add it to HF_MODEL_NAMES in config.py."
            )
        if self.model_name not in LITELLM_TEMPLATES:
            raise ValueError(
                f"No prompt template configured for {model_name}. "
                f"Add it to LITELLM_TEMPLATES in config.py."
            )

        self.hf_model_name = HF_MODEL_NAMES[self.model_name]
        self.fastchat_template_name = FASTCHAT_TEMPLATE_NAMES[self.model_name]
        self.use_open_source_model = True

        tmpl = LITELLM_TEMPLATES[self.model_name]
        self.eos_tokens = list(tmpl["eos_tokens"])
        self.post_message = tmpl["post_message"]

        key = (self.hf_model_name, dtype, device)
        if key not in LocalHF._SHARED:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            torch_dtype = {
                "bfloat16": torch.bfloat16,
                "float16": torch.float16,
                "float32": torch.float32,
            }.get(dtype, torch.bfloat16)

            logger.info(f"Loading HF model {self.hf_model_name} (dtype={dtype}, device={device})")
            tokenizer = AutoTokenizer.from_pretrained(
                self.hf_model_name, use_fast=True, trust_remote_code=True
            )
            # Prefer a pad token that is DIFFERENT from eos. Reusing eos as pad
            # is a common cause of subtle CUDA asserts on llama/vicuna with
            # left padding because the attention mask can't disambiguate
            # padding from real EOS during generation.
            if tokenizer.pad_token_id is None:
                if tokenizer.unk_token_id is not None and tokenizer.unk_token_id != tokenizer.eos_token_id:
                    tokenizer.pad_token = tokenizer.unk_token
                else:
                    tokenizer.pad_token = tokenizer.eos_token
            tokenizer.padding_side = "left"

            model = AutoModelForCausalLM.from_pretrained(
                self.hf_model_name,
                torch_dtype=torch_dtype,
                trust_remote_code=True,
                # SDPA / flash-attention with left-padded batches has produced
                # NaN logits on llama-2 / vicuna in bf16 in some torch+HF
                # versions (manifests as `torch.multinomial` device assert
                # "probability tensor contains either inf, nan or element < 0").
                # Eager attention is numerically safer here; PAIR batches are
                # small so the perf cost is negligible.
                attn_implementation="eager",
            )
            model.to(device)
            model.eval()
            # Make sure generation_config knows the pad token; otherwise
            # transformers can warn/error and some kernels misbehave.
            try:
                model.generation_config.pad_token_id = tokenizer.pad_token_id
                if tokenizer.eos_token_id is not None:
                    model.generation_config.eos_token_id = tokenizer.eos_token_id
            except Exception:
                pass
            LocalHF._SHARED[key] = (model, tokenizer)

        self.model, self.tokenizer = LocalHF._SHARED[key]

    def _messages_to_prompt(self, messages):
        """Render OpenAI-format messages into a single string using the fastchat template.

        The attacker code may seed the last assistant turn with an unterminated JSON
        fragment. We must preserve that seed and avoid any trailing EOS/sep that
        the fastchat template appends after a populated assistant message.
        """
        from common import conv_template

        conv = conv_template(self.fastchat_template_name)

        sys_parts = [m["content"] for m in messages if m["role"] == "system"]
        if sys_parts:
            conv.set_system_message("\n\n".join(sys_parts))

        seeded = False
        for m in messages:
            role = m["role"]
            content = m["content"]
            if role == "system":
                continue
            if role == "user":
                conv.append_message(conv.roles[0], content)
            elif role == "assistant":
                conv.append_message(conv.roles[1], content)
                seeded = True
            else:
                conv.append_message(conv.roles[0], content)

        if not seeded:
            conv.append_message(conv.roles[1], None)

        prompt = conv.get_prompt()

        if seeded:
            trailers = []
            for sep_attr in ("sep2", "sep"):
                sep = getattr(conv, sep_attr, None)
                if sep:
                    trailers.append(sep)
            trailers.extend(self.eos_tokens)
            trailers = sorted({t for t in trailers if t}, key=len, reverse=True)
            changed = True
            while changed:
                changed = False
                for t in trailers:
                    if prompt.endswith(t):
                        prompt = prompt[: -len(t)]
                        changed = True
                        break
            prompt = prompt.rstrip("\n")
        return prompt

    @staticmethod
    def _make_stopping_criteria(tokenizer, stop_strings, input_lens):
        """Build a StoppingCriteriaList that stops each sequence when any stop
        string appears in its newly generated text."""
        from transformers import StoppingCriteria, StoppingCriteriaList

        class _StopOnStrings(StoppingCriteria):
            def __init__(self, tokenizer, stops, input_lens):
                self.tokenizer = tokenizer
                self.stops = [s for s in stops if s]
                self.input_lens = input_lens
                self.done = [False] * len(input_lens)

            def __call__(self, input_ids, scores, **kwargs):
                if not self.stops:
                    return False
                for i in range(input_ids.shape[0]):
                    if self.done[i]:
                        continue
                    gen_ids = input_ids[i, self.input_lens[i]:]
                    if gen_ids.numel() == 0:
                        continue
                    # Move to CPU and clamp to vocab range defensively before decode
                    gen_ids_cpu = gen_ids.detach().to("cpu")
                    vocab_size = getattr(self.tokenizer, "vocab_size", None)
                    if vocab_size:
                        gen_ids_cpu = gen_ids_cpu.clamp(min=0, max=vocab_size - 1)
                    try:
                        text = self.tokenizer.decode(gen_ids_cpu, skip_special_tokens=True)
                    except Exception:
                        continue
                    if any(s in text for s in self.stops):
                        self.done[i] = True
                return all(self.done)

        return StoppingCriteriaList([_StopOnStrings(tokenizer, stop_strings, input_lens)])

    def batched_generate(self, convs_list, max_n_tokens, temperature, top_p, extra_eos_tokens=None):
        import torch
        from transformers import LogitsProcessor, LogitsProcessorList

        stop = list(self.eos_tokens)
        if extra_eos_tokens:
            stop.extend(extra_eos_tokens)

        prompts = [self._messages_to_prompt(c) for c in convs_list]

        # Strip a literal BOS string from the template output if fastchat
        # included one, so we don't end up with a doubled BOS when the
        # tokenizer adds its own.
        bos_str = getattr(self.tokenizer, "bos_token", None)
        if bos_str:
            prompts = [p[len(bos_str):] if p.startswith(bos_str) else p for p in prompts]

        if os.environ.get("PAIR_DEBUG_PROMPT"):
            print("=" * 80, flush=True)
            print(f"[LocalHF DEBUG] first prompt (len={len(prompts[0])} chars):", flush=True)
            print(prompts[0], flush=True)
            print("=" * 80, flush=True)

        enc = self.tokenizer(
            prompts,
            return_tensors="pt",
            padding=True,
            # IMPORTANT: must be True so the tokenizer prepends the BOS token
            # for llama/vicuna. Fastchat templates do NOT emit a literal `<s>`,
            # so disabling this leaves the model with no BOS and produces
            # pure token-salad continuations.
            add_special_tokens=True,
        ).to(self.model.device)

        input_lens = enc["input_ids"].shape[1]
        per_seq_input_lens = [input_lens] * enc["input_ids"].shape[0]

        do_sample = float(temperature) > 0.0
        gen_kwargs = dict(
            max_new_tokens=int(max_n_tokens),
            do_sample=do_sample,
            pad_token_id=self.tokenizer.pad_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
        )
        if do_sample:
            gen_kwargs["temperature"] = float(temperature)
            gen_kwargs["top_p"] = float(top_p)

        if stop:
            gen_kwargs["stopping_criteria"] = self._make_stopping_criteria(
                self.tokenizer, stop, per_seq_input_lens
            )

        # Safety net: if a kernel/dtype path produces NaN/inf logits, replace
        # them with finite values so torch.multinomial cannot device-assert
        # ("probability tensor contains either inf, nan or element < 0").
        class _SanitizeLogits(LogitsProcessor):
            def __call__(self, input_ids, scores):
                if not torch.isfinite(scores).all():
                    scores = torch.nan_to_num(scores, nan=-1e4, posinf=1e4, neginf=-1e4)
                return scores

        gen_kwargs["logits_processor"] = LogitsProcessorList([_SanitizeLogits()])

        with torch.inference_mode():
            out = self.model.generate(**enc, **gen_kwargs)

        texts = []
        for i in range(out.shape[0]):
            gen_ids = out[i, input_lens:].detach().to("cpu")
            vocab_size = getattr(self.tokenizer, "vocab_size", None)
            if vocab_size:
                gen_ids = gen_ids.clamp(min=0, max=vocab_size - 1)
            text = self.tokenizer.decode(gen_ids, skip_special_tokens=True)
            # Truncate at the earliest stop string occurrence
            cut = len(text)
            for s in stop:
                idx = text.find(s)
                if idx != -1 and idx < cut:
                    cut = idx
            text = text[:cut]
            if text.startswith(" "):
                text = text[1:]
            texts.append(text)
        return texts
    






